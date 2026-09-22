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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import referenced_task
from support import SCRIPTS, WORKFLOWS, load_yaml, run_tests


class VariableTests(unittest.TestCase):
    def source_task(self):
        graph = load_yaml(WORKFLOWS / 'ascendc/basic.yaml')
        task = load_yaml(referenced_task('ascendc/basic.yaml', graph['nodes'][0]))
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

    def test_real_tasks_bind_selected_skills_to_the_assigned_phase_only(self):
        graph = load_yaml(WORKFLOWS / 'ascendc/basic.yaml')
        originals = {}
        previous_bindings = {}
        for node in graph['nodes']:
            task_path = (referenced_task('ascendc/basic.yaml', node)).resolve()
            originals[task_path] = task_path.read_bytes()
            node['yaml'] = str(task_path)
            declarations = load_yaml(task_path).get('variables', {})
            if 'executor_skills' not in declarations:
                continue
            previous_bindings[node['id']] = {**declarations, **node.get('variables', {})}
            node['variables'].update(
                executor_skills=(f"EXECUTOR_{node['id']}: 必须加载 `ascendc-simt-tiling-design` Skill，按其中的要求执行。\n"
                                 "候选：出现精度错误时，必须加载 `ascendc-precision-debug` Skill，按其中的要求执行。"),
                verifier_skills=f"VERIFIER_{node['id']}: 必须加载 `ascendc-mc2-best-practice` Skill，按其中的要求执行。")
        with tempfile.TemporaryDirectory(prefix='workflow-skill-binding-') as temp:
            template, output = Path(temp) / 'template.yaml', Path(temp) / 'workflow.yaml'
            template.write_text(yaml.safe_dump(graph, allow_unicode=True))
            result = subprocess.run([sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                                     '--template', str(template), '--output', str(output)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = load_yaml(output)['nodes']
            for selected, node in zip(graph['nodes'], generated):
                if node['id'] in previous_bindings:
                    self.assert_skill_binding(selected, node, previous_bindings, graph)
            self.assertEqual(load_yaml(template), graph)
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def assert_skill_binding(self, selected, node, previous_bindings, graph):
        executor = selected['variables']['executor_skills']
        verifier = selected['variables']['verifier_skills']
        self.assertIn(executor, node['approach'])
        self.assertIn(verifier, node['procedure'])
        self.assertNotIn(executor, node['procedure'])
        self.assertNotIn(verifier, node['approach'])
        for variable, field in [('executor_skills', 'approach'), ('verifier_skills', 'procedure')]:
            self.assertNotIn(previous_bindings[node['id']][variable], node[field],
                             'dispatch bindings replace template defaults rather than append candidates')
        shared = node['goal'] + node['acceptance'] + node['out_of_scope']
        self.assertNotIn(executor, shared)
        self.assertNotIn(verifier, shared)
        self.assertNotIn('variables', node)
        self.assertNotIn('{{var:', json.dumps(node))
        for other in graph['nodes']:
            if other['id'] != node['id'] and other['id'] in previous_bindings:
                self.assertNotIn(other['variables']['executor_skills'], node['approach'])
                self.assertNotIn(other['variables']['verifier_skills'], node['procedure'])

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
