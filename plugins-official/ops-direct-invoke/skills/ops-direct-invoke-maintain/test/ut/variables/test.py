#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------

"""Exercise task-local prompt binding through the assembler CLI."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
from support import SCRIPTS, load_yaml, run_tests, task_fixture


class VariableTests(unittest.TestCase):
    def source_task(self):
        task = task_fixture()
        task['variables'] = {'message': None, 'suffix': 'default'}
        for field in ['goal', 'approach', 'procedure', 'acceptance', 'out_of_scope']:
            task[field] = ['{{id}}: {{var:message}} / {{var:suffix}}']
        return task

    def compile(self, folder, task, nodes):
        (folder / 'task.yaml').write_text(yaml.safe_dump(task, allow_unicode=True))
        source, output = folder / 'template.yaml', folder / 'workflow.yaml'
        source.write_text(yaml.safe_dump({'workflow': 'variables', 'max_parallel': 2, 'nodes': nodes}))
        result = subprocess.run([sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                                 '--template', str(source), '--output', str(output)],
                                cwd='/', capture_output=True, text=True, timeout=60)
        return result, output

    def test_node_isolation_defaults_multiline_and_literal_values(self):
        with tempfile.TemporaryDirectory(prefix='workflow-vars-') as temp:
            folder = Path(temp)
            literal = '中文: "quoted"\n$WORK_DIR $(false) `false` \\1 {{var:suffix}} {{id}}'
            nodes = [
                {'id': '0.0', 'yaml': 'task.yaml', 'depends_on': [], 'max_retries': 0,
                 'variables': {'message': literal}},
                {'id': '0.1', 'yaml': 'task.yaml', 'depends_on': [], 'max_retries': 2,
                 'variables': {'message': 'second', 'suffix': 'override'}}]
            result, output = self.compile(folder, self.source_task(), nodes)
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = load_yaml(output)['nodes']
            for node, expected in zip(generated, [f'0.0: {literal} / default', '0.1: second / override']):
                self.assertNotIn('variables', node)
                for field in ['goal', 'approach', 'procedure', 'acceptance', 'out_of_scope']:
                    self.assertEqual(node[field], [expected])
            self.assertEqual(load_yaml(folder / 'task.yaml')['variables']['message'], None)
            self.assertEqual(load_yaml(folder / 'template.yaml')['nodes'], nodes)


    def test_invalid_bindings_are_rejected_before_output(self):
        cases = [
            ('missing', {'suffix': 'x'}, None),
            ('empty_required', {'message': '  '}, None),
            ('non_string', {'message': 12}, None),
            ('unknown_assignment', {'message': 'ok', 'typo': 'x'}, None),
            ('not_mapping', [], None),
            ('undeclared_reference', {'message': 'ok'}, '{{var:typo}}'),
            ('malformed', {'message': 'ok'}, '{{var:message'),
        ]
        for name, values, prompt in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory(prefix='workflow-vars-') as temp:
                task = self.source_task()
                if prompt is not None:
                    task['approach'] = [prompt]
                result, output = self.compile(Path(temp), task, [
                    {'id': '0', 'yaml': 'task.yaml', 'depends_on': [], 'max_retries': 1, 'variables': values}])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('variable', result.stderr)
                self.assertFalse(output.exists())

    def test_invalid_declarations_and_empty_prompt_are_rejected(self):
        for declarations, prompt in [
            ({'bad-name': 'x'}, 'ok'), ({'message': 1}, 'ok'),
            ({'message': ''}, '{{var:message}}'), (None, 'ok')]:
            with self.subTest(variables=declarations), tempfile.TemporaryDirectory(prefix='workflow-vars-') as temp:
                task = self.source_task()
                task['variables'] = declarations
                task['approach'] = [prompt]
                result, output = self.compile(Path(temp), task, [
                    {'id': '0', 'yaml': 'task.yaml', 'depends_on': [], 'max_retries': 0}])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    run_tests()
