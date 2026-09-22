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

"""Guard the guide inventory, node IDs, dependencies and task references."""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import referenced_task
from support import SCRIPTS, WORKFLOWS, assert_graph, load_yaml, available_workflows, run_tests


class WorkflowGuideTests(unittest.TestCase):
    def test_guide_covers_all_workflow_templates(self):
        entries = available_workflows()
        for field in ['file']:
            values = [entry[field] for entry in entries]
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in values))
            self.assertEqual(len(values), len(set(values)), f'duplicate workflow {field}')
        files = {str(path.relative_to(WORKFLOWS)) for path in WORKFLOWS.rglob('*')
                 if path.suffix in {'.yaml', '.yml'}}
        self.assertEqual({entry['file'] for entry in entries}, files, 'missing or obsolete guide entry')

    def generate_guide(self, root, output):
        return subprocess.run([sys.executable, str(SCRIPTS / 'generate_workflow_guide.py'),
                               '--workflows-dir', str(root), '--output', str(output)],
                              cwd='/', capture_output=True, text=True, timeout=60)

    def read_guide(self, path):
        with path.open(encoding='utf-8', newline='') as stream:
            return list(csv.DictReader(stream))

    def test_guide_regenerates_from_nested_templates_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root, output = Path(temp) / 'workflows', Path(temp) / 'run/guide.csv'
            (root / 'ascendc').mkdir(parents=True)
            first = root / 'ascendc/first.yaml'
            original = '# template\nuse_when: "含逗号,和换行\\n的场景"\n'
            first.write_text(original, encoding='utf-8')
            result = self.generate_guide(root, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.read_guide(output), [
                {'file': 'ascendc/first.yaml', 'use_when': '含逗号,和换行\n的场景'}])
            self.assertEqual(first.read_text(), original)
            second = root / 'ascendc/second.yml'
            second.write_text('use_when: 新场景\n', encoding='utf-8')
            first.unlink()
            self.assertEqual(self.generate_guide(root, output).returncode, 0)
            self.assertEqual(self.read_guide(output), [{'file': 'ascendc/second.yml', 'use_when': '新场景'}])
            second.write_text('use_when: 更新场景\n', encoding='utf-8')
            self.assertEqual(self.generate_guide(root, output).returncode, 0)
            self.assertEqual(self.read_guide(output)[0]['use_when'], '更新场景')

    def test_invalid_metadata_does_not_overwrite_previous_guide(self):
        for text in ['workflow: missing', 'use_when: null', 'use_when: "  "', 'use_when: [bad]',
                     'use_when: one\nuse_when: two', 'use_when: [invalid', None]:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp:
                root, output = Path(temp) / 'workflows', Path(temp) / 'guide.csv'
                root.mkdir()
                output.write_text('previous guide', encoding='utf-8')
                if text is not None:
                    (root / 'invalid.yaml').write_text(text, encoding='utf-8')
                result = self.generate_guide(root, output)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(output.read_text(), 'previous guide')

    def test_guide_cannot_overwrite_shared_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root / 'template.yaml'
            original = 'use_when: 示例场景\n'
            template.write_text(original, encoding='utf-8')
            result = self.generate_guide(root, template)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(template.read_text(), original)

    def test_basic_keeps_research_implementation_whitebox_and_repair_order(self):
        entries = available_workflows()
        self.assertEqual({entry['file'] for entry in entries}, {'ascendc/basic.yaml', 'ascendc/feasibility.yaml'})
        graph = load_yaml(WORKFLOWS / 'ascendc/basic.yaml')['nodes']
        actual = [(node['id'], load_yaml(referenced_task('ascendc/basic.yaml', node))['title'], node['depends_on'])
                  for node in graph]
        self.assertEqual(actual, [
            ('0.0', '知识搜集', []), ('0.1', '黑盒测试设计', []),
            ('1', '测试工程开发', ['0.0', '0.1']), ('2', '算子开发', ['1']),
            ('3', '白盒测试设计', ['2']), ('4', '代码修复', ['3']), ('5', '文档准备', ['4'])])
        self.assertTrue(all(node['max_retries'] == 3 for node in graph))
        for node in graph[:2]:
            task = load_yaml(referenced_task('ascendc/basic.yaml', node))
            self.assertEqual(task['executor'], 'ops-direct-invoke-architect')

    def test_every_discovered_graph_and_task_reference(self):
        for entry in available_workflows():
            with self.subTest(workflow=entry['file']):
                self.assertEqual(set(entry), {'file', 'use_when'})
                self.assertTrue(entry['use_when'].strip())
                path = (WORKFLOWS / entry['file']).resolve()
                self.assertTrue(path.is_relative_to(WORKFLOWS.resolve()), 'workflow escapes template directory')
                self.assertTrue(path.is_file(), path)
                self.assertNotIn('nodes', entry, 'graph belongs only in the referenced template')
                template = load_yaml(path)
                self.assertEqual(set(template), {'workflow', 'use_when', 'max_parallel', 'nodes'})
                self.assertEqual(entry['use_when'], template['use_when'])
                self.assertTrue(path.read_text().splitlines()[1].startswith('use_when:'))
                assert_graph(self, template['nodes'])
                for node in template['nodes']:
                    self.assertEqual(set(node) - {'variables'}, {'id', 'yaml', 'depends_on', 'max_retries'})
                    self.assertIsInstance(node['yaml'], str)
                    task = load_yaml((referenced_task(entry['file'], node)).resolve())
                    self.assertIsInstance(task, dict)
                    self.assertNotIn('max_retries', task)
                    self.assertIs(type(node['max_retries']), int)
                    self.assertEqual(node['max_retries'], 3, 'discovered templates default to three retries')
                    self.assertNotIn('id', task, 'identity belongs in the workflow, not the task')
                    self.assertNotIn('depends_on', task, 'dependencies belong in the workflow, not the task')


if __name__ == '__main__':
    run_tests()
