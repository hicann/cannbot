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

"""Run all registered templates and generated YAML through the blackbox harness."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support
from support import referenced_task
from support import SCRIPTS, WORKFLOWS, load_yaml, generate_workflow, available_workflows, run_tests, run_workflow


class WorkflowExecutionTests(unittest.TestCase):
    def test_every_registered_template_runs(self):
        for entry in available_workflows():
            with self.subTest(workflow=entry['file']), tempfile.TemporaryDirectory(prefix='workflow-ut-') as temp:
                source = WORKFLOWS / entry['file']
                before = source.read_bytes()
                run_workflow(self, '--template', entry['file'], Path(temp) / 'run',
                             [node['id'] for node in load_yaml(WORKFLOWS / entry['file'])['nodes']])
                self.assertEqual(source.read_bytes(), before, 'launcher modified a shared template')

    def test_spike_failure_is_isolated_and_uses_three_retries(self):
        with tempfile.TemporaryDirectory(prefix='workflow-spike-fail-') as temp:
            work = Path(temp) / 'workflow1'
            (work / '.workflow').mkdir(parents=True)
            (work / '.workflow/dry_replies.json').write_text(json.dumps({
                '0': ['executed', '$VERDICT:fail'] * 4}))
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / 'run_workflow.py'), '--template', 'ascendc/feasibility.yaml',
                 '--work-dir', str(work), '--provider', 'codex', '--prompt', 'spike failure simulation',
                 '--harness-skill', str(support.HARNESS_SKILL), '--foreground', '--dry-run'],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            state = json.loads((work / '.workflow/status.json').read_text())['tasks']
            self.assertEqual(set(state), {'0'})
            self.assertEqual(state['0']['status'], 'fail')
            self.assertEqual(state['0']['retries'], 4)
            workflow = load_yaml(work / 'workflow1.yaml')
            self.assertEqual([node['title'] for node in workflow['nodes']], ['技术穿刺'])
            self.assertFalse((work.parent / 'workflow2').exists())

    def test_either_initial_failure_blocks_implementation_and_delivery(self):
        entry = next(item for item in available_workflows() if item['file'] == 'ascendc/basic.yaml')
        for failed_id in ['0.0', '0.1']:
            with self.subTest(node=failed_id), tempfile.TemporaryDirectory(prefix='workflow-design-fail-') as temp:
                work = Path(temp) / 'run'
                (work / '.workflow').mkdir(parents=True)
                (work / '.workflow/dry_replies.json').write_text(json.dumps({
                    failed_id: ['executed', '$VERDICT:fail'] * 4}))
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / 'run_workflow.py'), '--template', entry['file'],
                     '--work-dir', str(work), '--provider', 'codex', '--prompt', 'design failure simulation',
                     '--harness-skill', str(support.HARNESS_SKILL), '--foreground', '--dry-run'],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                status = json.loads((work / '.workflow/status.json').read_text())['tasks']
                self.assertEqual(status[failed_id]['status'], 'fail')
                self.assertEqual(status[failed_id]['retries'], 4)
                for identifier in ['1', '2', '3', '4', '5']:
                    self.assertEqual(status[identifier]['status'], 'pending', identifier)

    def test_default_repair_runs_after_whitebox_and_blocks_delivery_on_failure(self):
        entry = available_workflows()[0]
        with tempfile.TemporaryDirectory(prefix='workflow-repair-') as temp:
            work = Path(temp) / 'workflow1'
            (work / '.workflow').mkdir(parents=True)
            (work / '.workflow/dry_replies.json').write_text(json.dumps({
                '4': ['executed', '$VERDICT:fail'] * 4}))
            result = subprocess.run([sys.executable, str(SCRIPTS / 'run_workflow.py'), '--template', entry['file'],
                                     '--work-dir', str(work), '--provider', 'codex', '--prompt', 'repair simulation',
                                     '--harness-skill', str(support.HARNESS_SKILL), '--foreground', '--dry-run'],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 1, result.stderr)
            state = json.loads((work / '.workflow/status.json').read_text())['tasks']
            self.assertEqual(state['3']['status'], 'pass')
            self.assertEqual(state['4']['status'], 'fail')
            self.assertEqual(state['5']['status'], 'pending')
            repair = next(node for node in load_yaml(work / 'workflow1.yaml')['nodes'] if node['id'] == '4')
            self.assertNotIn('variables', repair)
            self.assertNotIn('{{var:', json.dumps(repair))

    def test_template_launch_freezes_input_and_requires_yaml_for_resume(self):
        entry = available_workflows()[0]
        with tempfile.TemporaryDirectory(prefix='workflow-freeze-') as temp:
            work = Path(temp) / 'workflow1'
            nodes = load_yaml(WORKFLOWS / entry['file'])['nodes']
            run_workflow(self, '--template', entry['file'], work, [node['id'] for node in nodes])
            definition = work / 'workflow1.yaml'
            frozen = definition.read_bytes()
            self.assertNotIn('yaml', load_yaml(definition)['nodes'][0])
            result = subprocess.run([sys.executable, str(SCRIPTS / 'run_workflow.py'), '--template', entry['file'],
                                     '--work-dir', str(work), '--provider', 'codex',
                                     '--harness-skill', str(support.HARNESS_SKILL), '--foreground', '--dry-run'],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('resume with --yaml', result.stderr)
            run_workflow(self, '--yaml', definition, work, [node['id'] for node in nodes])
            self.assertEqual(definition.read_bytes(), frozen)

    def test_basic_can_omit_documents_in_a_run_specific_graph(self):
        entry = available_workflows()[0]
        with tempfile.TemporaryDirectory(prefix='workflow-no-docs-') as temp:
            folder = Path(temp)
            template = load_yaml(WORKFLOWS / entry['file'])
            template['nodes'] = template['nodes'][:-1]
            for node in template['nodes']:
                node['yaml'] = str((referenced_task(entry['file'], node)).resolve())
            source, output = folder / 'selected.yaml', folder / 'workflow.yaml'
            source.write_text(json.dumps(template))
            result = subprocess.run([sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                                     '--template', str(source), '--output', str(output)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            run_workflow(self, '--yaml', output, folder / 'run', [node['id'] for node in template['nodes']])
            self.assertNotIn('文档准备', [node['title'] for node in load_yaml(output)['nodes']])

    def graph_without_research(self, notes):
        graph = load_yaml(WORKFLOWS / 'ascendc/basic.yaml')
        graph['nodes'] = graph['nodes'][1:]
        graph['nodes'][0]['id'] = '0'
        graph['nodes'][1]['depends_on'] = ['0']
        for node in graph['nodes']:
            node['yaml'] = str((referenced_task('ascendc/basic.yaml', node)).resolve())
        operator = next(node for node in graph['nodes'] if node['id'] == '2')
        operator['variables'].pop('knowledge_documents')
        if notes:
            operator['variables']['knowledge_documents'] = notes
        return graph

    def test_development_without_research_with_or_without_previous_notes(self):
        for notes in [None, '/previous/workflow/0-知识搜集.md']:
            with self.subTest(notes=notes), tempfile.TemporaryDirectory(prefix='workflow-no-research-') as temp:
                folder = Path(temp)
                graph = self.graph_without_research(notes)
                source, output = folder / 'selected.yaml', folder / 'workflow.yaml'
                source.write_text(json.dumps(graph))
                result = subprocess.run([sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                                         '--template', str(source), '--output', str(output)],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                nodes = load_yaml(output)['nodes']
                self.assertNotIn('知识搜集', [node['title'] for node in nodes])
                operator = next(node for node in nodes if node['title'] == '算子开发')
                self.assertIn(notes or '无补充文档。', '\n'.join(operator['approach']))
                self.assertNotIn('$WORK_DIR/0.0-知识搜集.md', '\n'.join(operator['approach']))
                run_workflow(self, '--yaml', output, folder / 'run', [node['id'] for node in nodes])

    def test_every_generated_workflow_runs(self):
        for entry in available_workflows():
            with self.subTest(workflow=entry['file']), tempfile.TemporaryDirectory(prefix='workflow-ut-') as temp:
                generated = generate_workflow(self, entry, Path(temp))
                before = generated.read_bytes()
                run_workflow(self, '--yaml', generated, Path(temp) / 'run',
                             [node['id'] for node in load_yaml(WORKFLOWS / entry['file'])['nodes']])
                self.assertEqual(generated.read_bytes(), before, 'launcher modified generated YAML')


if __name__ == '__main__':
    run_tests()
