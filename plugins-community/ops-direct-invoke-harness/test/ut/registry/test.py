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

"""Guard the registry inventory, node IDs, dependencies and task references."""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import WORKFLOWS, assert_graph, load_yaml, registered_workflows, run_tests


class RegistryTests(unittest.TestCase):
    def test_registry_covers_all_workflow_templates(self):
        entries = registered_workflows()
        for field in ['file']:
            values = [entry[field] for entry in entries]
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in values))
            self.assertEqual(len(values), len(set(values)), f'duplicate workflow {field}')
        files = {str(path.relative_to(WORKFLOWS)) for path in WORKFLOWS.rglob('*')
                 if path.suffix in {'.yaml', '.yml'}}
        self.assertEqual({entry['file'] for entry in entries}, files, 'missing or obsolete registry entry')

    def test_basic_keeps_research_implementation_whitebox_and_repair_order(self):
        entries = registered_workflows()
        self.assertEqual({entry['file'] for entry in entries}, {'basic.yaml', 'feasibility.yaml'})
        graph = load_yaml(WORKFLOWS / 'basic.yaml')['nodes']
        actual = [(node['id'], load_yaml(WORKFLOWS / node['yaml'])['title'], node['depends_on'])
                  for node in graph]
        self.assertEqual(actual, [
            ('0.0', '知识搜集', []), ('0.1', '黑盒测试设计', []),
            ('1', '测试工程开发', ['0.0', '0.1']), ('2', '算子开发', ['1']),
            ('3', '白盒测试设计', ['2']), ('4', '代码修复', ['3']), ('5', '文档准备', ['4'])])
        self.assertTrue(all(node['max_retries'] == 3 for node in graph))
        for node in graph[:2]:
            self.assertEqual(load_yaml(WORKFLOWS / node['yaml'])['executor'], 'ops-direct-invoke-architect')

    def test_every_registered_graph_and_task_reference(self):
        for entry in registered_workflows():
            with self.subTest(workflow=entry['file']):
                self.assertEqual(set(entry), {'file', 'use_when'})
                self.assertTrue(entry['use_when'].strip())
                path = (WORKFLOWS / entry['file']).resolve()
                self.assertTrue(path.is_relative_to(WORKFLOWS.resolve()), 'workflow escapes template directory')
                self.assertTrue(path.is_file(), path)
                self.assertNotIn('nodes', entry, 'graph belongs only in the referenced template')
                template = load_yaml(path)
                self.assertEqual(set(template), {'workflow', 'max_parallel', 'nodes'})
                assert_graph(self, template['nodes'])
                for node in template['nodes']:
                    self.assertEqual(set(node), {'id', 'yaml', 'depends_on', 'max_retries', 'variables'})
                    self.assertIsInstance(node['yaml'], str)
                    task = load_yaml((WORKFLOWS / node['yaml']).resolve())
                    self.assertIsInstance(task, dict)
                    self.assertNotIn('max_retries', task)
                    self.assertIs(type(node['max_retries']), int)
                    self.assertEqual(node['max_retries'], 3, 'registered templates default to three retries')
                    self.assertNotIn('id', task, 'identity belongs in the registry, not the task')
                    self.assertNotIn('depends_on', task, 'dependencies belong in the registry, not the task')


if __name__ == '__main__':
    run_tests()
