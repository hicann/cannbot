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

"""Assemble every registry entry and verify its full public YAML contract."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import (NODE_FIELDS, SCRIPTS, WORKFLOWS, assert_workflow_schema, generate_workflow,
                     load_yaml, registered_workflows, run_tests)


class WorkflowGenerationTests(unittest.TestCase):
    def test_every_generated_workflow_expands_references_and_task_content(self):
        for entry in registered_workflows():
            with self.subTest(workflow=entry['file']), tempfile.TemporaryDirectory(prefix='workflow-ut-') as temp:
                template_path = WORKFLOWS / entry['file']
                template = load_yaml(template_path)
                task_paths = [(template_path.parent / node['yaml']).resolve() for node in template['nodes']]
                before = {path: path.read_bytes() for path in [template_path, *task_paths]}
                generated = load_yaml(generate_workflow(self, entry, Path(temp)))
                assert_workflow_schema(self, generated)
                self.assertEqual(len(generated['nodes']), len(template['nodes']))
                producer_ids = {node['title']: node['id'] for node in generated['nodes']}
                for node, reference, task_path in zip(generated['nodes'], template['nodes'], task_paths):
                    self.assert_expanded_node(node, reference, task_path, producer_ids)
                for path, contents in before.items():
                    self.assertEqual(path.read_bytes(), contents)

    def assert_expanded_node(self, node, reference, task_path, producer_ids):
        task = load_yaml(task_path)
        expected_fields = (NODE_FIELDS - {'id', 'depends_on', 'max_retries'}) | {'procedure', 'variables'}
        self.assertEqual(set(task), expected_fields)
        values = {**task.pop('variables'), **reference.get('variables', {})}
        rendered = json.dumps(task, ensure_ascii=False).replace('{{id}}', node['id'])
        for title, identifier in producer_ids.items():
            rendered = rendered.replace('{{id:' + title + '}}', identifier)
        resolved = json.loads(rendered)
        for field in ['goal', 'approach', 'procedure', 'acceptance', 'out_of_scope']:
            for key, value in values.items():
                resolved[field] = [item.replace('{{var:' + key + '}}', value) for item in resolved[field]]
        self.assertEqual(node, {**resolved, 'id': reference['id'],
                               'depends_on': reference['depends_on'],
                               'max_retries': reference['max_retries']})

    def test_all_nodes_separate_executor_deliverables_from_verifier_reports(self):
        for entry in registered_workflows():
            with self.subTest(template=entry['file']), tempfile.TemporaryDirectory() as temp:
                output = generate_workflow(self, entry, Path(temp))
                for node in load_yaml(output)['nodes']:
                    self.assert_report_ownership(node)

    def assert_report_ownership(self, node):
        report = f"$WORK_DIR/{node['id']}-验收报告.md"
        self.assertIn(report, '\n'.join(node['approach']))
        self.assertIn(f'test -s "{report}"', '\n'.join(node['procedure']))
        self.assertNotIn(report, '\n'.join(node['acceptance']))
        self.assertNotIn('代码检视报告.md', '\n'.join(node['acceptance']))
        if node['title'] in ['技术穿刺', '算子开发', '白盒测试设计', '代码修复']:
            evidence = f"$WORK_DIR/{node['id']}-测试执行记录.md"
            for phase in ['approach', 'procedure', 'acceptance']:
                self.assertIn(evidence, '\n'.join(node[phase]))

    def test_code_tasks_dispatch_compatible_quality_rules_to_both_roles(self):
        code_tasks = {'技术穿刺', '测试工程开发', '算子开发', '白盒测试设计', '代码修复'}
        seen = set()
        for entry in registered_workflows():
            with tempfile.TemporaryDirectory(prefix='workflow-quality-') as temp:
                nodes = load_yaml(generate_workflow(self, entry, Path(temp)))['nodes']
                for node in (item for item in nodes if item['title'] in code_tasks):
                    seen.add(node['title'])
                    self.assert_quality_skills(node)
        self.assertEqual(seen, code_tasks)

    def assert_quality_skills(self, node):
        for phase in ['approach', 'procedure']:
            with self.subTest(node=node['title'], phase=phase):
                instructions = '\n'.join(node[phase])
                self.assertIn('`repo-coding-rules`', instructions)
                self.assertNotIn('`ascendc-direct-invoke-template`', instructions)
                self.assertNotIn('`ascendc-whitebox-design`', instructions)

    def write_report_tasks(self, folder):
        entry = registered_workflows()[0]
        base = load_yaml((WORKFLOWS / load_yaml(WORKFLOWS / entry['file'])['nodes'][0]['yaml']).resolve())
        files = {}
        for title in ['producer', 'other', 'consumer']:
            task = {**base, 'title': title,
                    'approach': ['write $WORK_DIR/{{id}}-report.md; template templates/docs/report.md'],
                    'procedure': ['verify $WORK_DIR/{{id}}-report.md'],
                    'acceptance': ['test -s "$WORK_DIR/{{id}}-report.md"']}
            if title == 'consumer':
                task['approach'].append('read $WORK_DIR/{{id:producer}}-report.md')
            path = folder / f'{title}.yaml'
            path.write_text(yaml.safe_dump(task), encoding='utf-8')
            files[title] = path
        return files

    def assemble_report_tasks(self, output, files, titles, dependencies):
        args = [sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                '--max-retries', '1', '--output', str(output)]
        for dependency in dependencies:
            args.extend(['--depends-on', dependency])
        paths = [files.get(title) for title in titles]
        self.assertNotIn(None, paths, 'unknown report task fixture')
        return subprocess.run(args + list(map(str, paths)), capture_output=True, text=True, timeout=60)

    def assert_report_paths(self, node, identifier):
        self.assertEqual(node['approach'][0],
                         f'write $WORK_DIR/{identifier}-report.md; template templates/docs/report.md')
        self.assertEqual(node['procedure'], [f'verify $WORK_DIR/{identifier}-report.md'])
        self.assertEqual(node['acceptance'], [f'test -s "$WORK_DIR/{identifier}-report.md"'])

    def assert_report_workflow(self, nodes, ids, producer):
        self.assertEqual([node['id'] for node in nodes], ids)
        for node, identifier in zip(nodes, ids):
            self.assert_report_paths(node, identifier)
        consumer = next(node for node in nodes if node['title'] == 'consumer')
        self.assertEqual(consumer['approach'][1], f'read $WORK_DIR/{producer}-report.md')

    def test_report_paths_follow_ids_and_upstream_producer(self):
        with tempfile.TemporaryDirectory(prefix='workflow-report-ut-') as temp:
            folder = Path(temp)
            files = self.write_report_tasks(folder)
            before = {p: p.read_bytes() for p in files.values()}
            cases = [
                ('serial', ['producer', 'consumer'], [], ['0', '1'], '0'),
                ('reordered', ['consumer', 'other', 'producer'], ['1:3', '2:', '3:'], ['1', '0.0', '0.1'], '0.1'),
                ('repeated', ['producer', 'producer', 'consumer'], [], ['0', '1', '2'], '1'),
            ]
            for name, titles, dependencies, ids, producer in cases:
                with self.subTest(case=name):
                    output = folder / f'{name}.yaml'
                    result = self.assemble_report_tasks(output, files, titles, dependencies)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    nodes = load_yaml(output)['nodes']
                    self.assert_report_workflow(nodes, ids, producer)
                    self.assertNotIn('{{id', output.read_text())
            for name, titles, dependencies in [
                ('missing', ['consumer'], []),
                ('not_upstream', ['producer', 'consumer'], ['2:']),
                ('ambiguous', ['producer', 'producer', 'consumer'], ['2:', '3:1,2']),
            ]:
                with self.subTest(case=name):
                    output = folder / f'{name}.yaml'
                    result = self.assemble_report_tasks(output, files, titles, dependencies)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn('report producer', result.stderr)
                    self.assertFalse(output.exists())
            for path, contents in before.items():
                self.assertEqual(path.read_bytes(), contents)

    def test_unsafe_tags_and_invalid_mapping_keys_are_rejected(self):
        cases = [
            ('duplicate', 'workflow: first\nworkflow: second\n', 'duplicate YAML key'),
            ('nested_duplicate', 'nodes:\n- id: a\n  id: b\n', 'duplicate YAML key'),
            ('non_string_key', '1: value\n', 'non-string'),
            ('python_tag', '!!python/object/apply:builtins.str [unsafe]\n', 'constructor'),
        ]
        for name, payload, message in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / 'input.yaml'
                source.write_text(payload, encoding='utf-8')
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    load_yaml(source)
                self.assert_assembler_rejects_yaml(source, message)

    def assert_assembler_rejects_yaml(self, source, message):
        for mode in [[], ['--template']]:
            with self.subTest(mode=mode):
                output = source.parent / 'workflow.yaml'
                options = mode or ['--max-retries', '1']
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / 'assemble_workflow.py'), *options, str(source),
                     '--output', str(output)], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse(output.exists())

    def test_template_retries_and_latest_task_content_are_used(self):
        entry = registered_workflows()[0]
        source = load_yaml(WORKFLOWS / load_yaml(WORKFLOWS / entry['file'])['nodes'][0]['yaml'])
        with tempfile.TemporaryDirectory(prefix='workflow-ut-') as temp:
            folder = Path(temp)
            task = folder / 'task.yaml'
            task.write_text(yaml.safe_dump({**source, 'goal': ['LATEST_TASK_CONTENT']}))
            reference = {'workflow': 'custom', 'max_parallel': 3, 'nodes': [
                {'id': '0', 'yaml': 'task.yaml', 'depends_on': [], 'max_retries': 0},
                {'id': '1', 'yaml': 'task.yaml', 'depends_on': ['0'], 'max_retries': 4}]}
            template = folder / 'reference.yaml'
            template.write_text(yaml.safe_dump(reference))
            output = folder / 'workflow.yaml'
            result = subprocess.run([sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                                     '--template', str(template), '--output', str(output)],
                                    cwd='/', capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            definition = load_yaml(output)
            self.assertEqual(definition['workflow'], 'custom')
            self.assertEqual(definition['max_parallel'], 3)
            self.assertEqual([node['max_retries'] for node in definition['nodes']], [0, 4])
            self.assertTrue(all(node['goal'] == ['LATEST_TASK_CONTENT'] for node in definition['nodes']))
            self.assertNotIn('max_retries', load_yaml(task))

    def test_invalid_reference_graphs_are_rejected_without_output(self):
        entry = registered_workflows()[0]
        base = load_yaml(WORKFLOWS / entry['file'])
        for node in base['nodes']:
            node['yaml'] = str((WORKFLOWS / node['yaml']).resolve())
        mutations = [
            ('missing_retry', lambda graph: graph['nodes'][0].pop('max_retries')),
            *[(f'retry_{value!r}', lambda graph, value=value: graph['nodes'][0].update(max_retries=value))
              for value in [-1, True, 1.5, '1', None, []]],
            ('unknown_dependency', lambda graph: graph['nodes'][2].update(depends_on=['missing'])),
            ('duplicate_dependency', lambda graph: graph['nodes'][2].update(depends_on=['0.0', '0.0'])),
            ('cycle', lambda graph: graph['nodes'][0].update(depends_on=['1'])),
            ('duplicate_id', lambda graph: graph['nodes'][1].update(id='0.0')),
            ('wrong_id', lambda graph: graph['nodes'][-1].update(id='99')),
            ('task_missing', lambda graph: graph['nodes'][0].update(yaml='missing.yaml')),
            ('inline_task', lambda graph: graph['nodes'][0].update(goal=['invalid inline content'])),
        ]
        for name, mutate in mutations:
            with self.subTest(case=name), tempfile.TemporaryDirectory(prefix='workflow-invalid-') as temp:
                graph = json.loads(json.dumps(base))
                mutate(graph)
                template, output = Path(temp) / 'reference.yaml', Path(temp) / 'workflow.yaml'
                template.write_text(yaml.safe_dump(graph))
                result = subprocess.run([sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                                         '--template', str(template), '--output', str(output)],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(output.exists())

    def test_positional_tasks_require_dispatch_retry_budget(self):
        entry = registered_workflows()[0]
        source = load_yaml(WORKFLOWS / load_yaml(WORKFLOWS / entry['file'])['nodes'][0]['yaml'])
        for budget, inline_retry, valid in [(None, False, False), ('-1', False, False),
                                           ('2', True, False), ('2', False, True)]:
            with self.subTest(budget=budget, inline=inline_retry), tempfile.TemporaryDirectory() as temp:
                task = {**source}
                if inline_retry:
                    task['max_retries'] = 1
                path, output = Path(temp) / 'task.yaml', Path(temp) / 'out.yaml'
                path.write_text(yaml.safe_dump(task))
                args = [sys.executable, str(SCRIPTS / 'assemble_workflow.py'), str(path), '--output', str(output)]
                if budget is not None:
                    args += ['--max-retries', budget]
                result = subprocess.run(args, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0 if valid else 2, result.stderr)
                if valid:
                    self.assertEqual(load_yaml(output)['nodes'][0]['max_retries'], 2)
                else:
                    self.assertFalse(output.exists())

    def test_optional_procedure_is_preserved_or_rejected_when_invalid(self):
        entry = registered_workflows()[0]
        source = load_yaml((WORKFLOWS / load_yaml(WORKFLOWS / entry['file'])['nodes'][0]['yaml']).resolve())
        for present, value, valid in [(False, None, True), (True, ['VERIFY_ONLY_SENTINEL'], True),
                                     (True, [], False), (True, None, False), (True, 'check', False),
                                     (True, [''], False), (True, ['   '], False),
                                     (True, [1], False), (True, {}, False)]:
            with self.subTest(present=present, value=value), tempfile.TemporaryDirectory(prefix='workflow-ut-') as temp:
                task = {key: item for key, item in source.items() if key != 'procedure'}
                if present:
                    task['procedure'] = value
                task_path, output = Path(temp) / 'task.yaml', Path(temp) / 'workflow.yaml'
                task_path.write_text(yaml.safe_dump(task, allow_unicode=True), encoding='utf-8')
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / 'assemble_workflow.py'), '--max-retries', '1', str(task_path),
                     '--output', str(output)],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0 if valid else 2, result.stdout + result.stderr)
                self.assert_procedure_result(result, output, present, value, valid)

    def assert_procedure_result(self, result, output, present, value, valid):
        if valid:
            workflow = load_yaml(output)
            assert_workflow_schema(self, workflow)
            node = workflow['nodes'][0]
            self.assertEqual('procedure' in node, present)
            if present:
                self.assertEqual(node['procedure'], value)
                self.assertNotIn(value[0], node['approach'] + node['acceptance'])
        else:
            self.assertIn('procedure', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    run_tests()
