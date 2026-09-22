# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------

"""Shared fixtures for workflow public-interface tests; no harness internals imported."""
import argparse
import csv
import graphlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PLUGIN_ROOT / 'skills/ops-direct-invoke'
SCRIPTS = SKILL_ROOT / 'scripts'
WORKFLOWS = SKILL_ROOT / 'workflows'
_bundled_harness = PLUGIN_ROOT / 'skills/workflow-orchestrator'
HARNESS_SKILL = (_bundled_harness if _bundled_harness.exists()
                 else PLUGIN_ROOT.parents[1] / 'harness/workflow-orchestrator')
NODE_FIELDS = {'id', 'task_type', 'title', 'goal', 'approach', 'acceptance', 'out_of_scope',
               'depends_on', 'executor', 'verifier', 'max_retries', 'on_exhaust'}


class StrictLoader(yaml.SafeLoader):
    """Do not let duplicate keys hide mistakes in committed YAML."""


def strict_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError(f'non-string or duplicate YAML key: {key!r}')
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, strict_mapping)


def load_yaml(path):
    loader = StrictLoader(path.read_text(encoding='utf-8'))
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def referenced_task(template_file, node):
    """Task references are relative to their workflow file, including category folders."""
    return (WORKFLOWS / template_file).parent / node['yaml']


def available_workflows():
    with tempfile.TemporaryDirectory(prefix='workflow-guide-') as temp:
        output = Path(temp) / 'workflow-guide.csv'
        result = subprocess.run([sys.executable, str(SCRIPTS / 'generate_workflow_guide.py'),
                                 '--output', str(output)], cwd=temp, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError(result.stdout + result.stderr)
        with output.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != ['file', 'use_when']:
                raise ValueError('guide requires file and use_when columns')
            return list(reader)


def numeric_id(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'\d+(?:\.\d+)?', identifier):
        raise ValueError(f'node id must be a numeric string, got {identifier!r}')
    return tuple(map(int, identifier.split('.')))


def assert_graph(case, nodes):
    case.assertIsInstance(nodes, list)
    case.assertTrue(nodes, 'empty workflow graph')
    identifiers = [node['id'] for node in nodes]
    for identifier in identifiers:
        numeric_id(identifier)
    case.assertEqual(len(set(identifiers)), len(identifiers), 'duplicate node id')
    case.assertEqual(identifiers, sorted(identifiers, key=numeric_id), 'nodes must be sorted numerically')
    for node in nodes:
        parents = node['depends_on']
        case.assertIsInstance(parents, list)
        case.assertTrue(all(isinstance(parent, str) for parent in parents), 'dependencies must be strings')
        case.assertEqual(len(parents), len(set(parents)), 'duplicate dependency')
        case.assertTrue(set(parents) <= set(identifiers), f'unknown dependency in {node["id"]}')
    # Uses only the published graph, not the assembler's own cycle checker.
    list(graphlib.TopologicalSorter({node['id']: node['depends_on'] for node in nodes}).static_order())


def assert_workflow_schema(case, workflow):
    case.assertIsInstance(workflow, dict)
    case.assertEqual(set(workflow), {'workflow', 'max_parallel', 'nodes'})
    case.assertIsInstance(workflow['workflow'], str)
    case.assertTrue(workflow['workflow'].strip())
    case.assertIs(type(workflow['max_parallel']), int)
    case.assertGreaterEqual(workflow['max_parallel'], 1)
    assert_graph(case, workflow['nodes'])
    for node in workflow['nodes']:
        case.assertEqual(set(node) - {'procedure'}, NODE_FIELDS, f'incorrect node fields: {node.get("id")}')
        case.assertEqual(node['task_type'], 'normal')
        for key in ['title', 'executor', 'verifier']:
            case.assertIsInstance(node[key], str)
            case.assertTrue(node[key].strip(), f'empty {key}')
        for key in ['goal', 'approach', 'acceptance', 'out_of_scope'] + (['procedure'] if 'procedure' in node else []):
            case.assertIsInstance(node[key], list)
            case.assertTrue(node[key], f'empty {key}')
            case.assertTrue(all(isinstance(item, str) and item.strip() for item in node[key]), key)
        case.assertIs(type(node['max_retries']), int)
        case.assertGreaterEqual(node['max_retries'], 0)
        case.assertIn(node['on_exhaust'], ['exit', 'continue'])


def run_command(case, arguments, cwd):
    command = [sys.executable, *map(str, arguments)]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=60)
    case.assertEqual(result.returncode, 0,
                     f'Command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}')
    return result


def generate_workflow(case, entry, directory):
    arguments = [SCRIPTS / 'assemble_workflow.py', '--template', WORKFLOWS / entry['file'],
                 '--output', directory / 'workflow.yaml']
    run_command(case, arguments, directory)
    return directory / 'workflow.yaml'


def run_workflow(case, definition_flag, definition, work, expected_ids):
    case.assertTrue((HARNESS_SKILL / 'scripts/orchestrator.py').is_file(),
                    f'harness CLI missing: {HARNESS_SKILL}; pass --harness-skill')
    arguments = [SCRIPTS / 'run_workflow.py', definition_flag, definition,
                 '--work-dir', work, '--provider', 'codex', '--prompt', 'registry UT simulation only',
                 '--harness-skill', HARNESS_SKILL, '--foreground', '--dry-run']
    # Deliberately launch outside the Skill directory to check resource path resolution.
    run_command(case, arguments, work.parent)
    status = json.loads((work / '.workflow/status.json').read_text(encoding='utf-8'))
    case.assertEqual(set(status['tasks']), set(expected_ids), 'empty or incomplete execution')
    for identifier in expected_ids:
        case.assertEqual(status['tasks'][identifier]['status'], 'pass', identifier)


def run_tests():
    """Every category exposes the same CLI, plus normal unittest options."""
    import unittest
    global HARNESS_SKILL
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--harness-skill', type=Path)
    args, remaining = parser.parse_known_args()
    if args.harness_skill:
        HARNESS_SKILL = args.harness_skill.resolve()
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
