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

"""Assemble task files, assigning numeric IDs by dependency layer and parallel branch."""
import argparse
import logging
import re
import sys
from pathlib import Path

import yaml

LOGGER = logging.getLogger(__name__)

TASK_FIELDS = {'task_type', 'title', 'goal', 'approach', 'acceptance',
               'out_of_scope', 'executor', 'verifier', 'on_exhaust'}


VARIABLE_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
VARIABLE_REFERENCE = re.compile(r'\{\{var:([A-Za-z_][A-Za-z0-9_]*)\}\}')


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently losing task instructions."""


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError(f'non-string or duplicate YAML key: {key!r}')
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(path):
    """Use only SafeLoader constructors, with duplicate-key validation."""
    loader = UniqueLoader(path.read_text(encoding='utf-8'))
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def bind_variables(declarations, supplied):
    """Bind task-local string variables; null declarations require a value."""
    if not isinstance(declarations, dict) or not isinstance(supplied, dict):
        raise ValueError('variables must be a mapping')
    if any(not isinstance(key, str) or not VARIABLE_NAME.fullmatch(key) for key in declarations):
        raise ValueError('variable names must be identifiers')
    unknown = set(supplied) - set(declarations)
    if unknown:
        raise ValueError(f'undeclared variables: {sorted(unknown)}')
    values = {**declarations, **supplied}
    for key, default in declarations.items():
        if default is not None and not isinstance(default, str):
            raise ValueError(f'variable {key}: default must be a string or null')
        value = values.get(key)
        if not isinstance(value, str) or (default is None and not value.strip()):
            raise ValueError(f'variable {key}: a string value is required (null declarations require nonempty input)')
    return values


def expand_variables(text, values):
    """Replace only explicit placeholders once, without evaluating supplied text."""
    if '{{var' in VARIABLE_REFERENCE.sub('', text):
        raise ValueError('malformed variable placeholder')

    def replace(match):
        name = match.group(1)
        if name not in values:
            raise ValueError(f'undeclared variable reference: {name}')
        return values[name]

    result = VARIABLE_REFERENCE.sub(replace, text)
    if not result.strip():
        raise ValueError('variable expansion produced an empty prompt item')
    return result


def dependency_overrides(dependencies, count):
    overrides = {}
    for specification in dependencies:
        target, separator, sources = specification.partition(':')
        if not separator:
            raise ValueError('--depends-on requires N:M,K or N: for an independent task')
        index = int(target)
        parents = [int(value) for value in sources.split(',')] if sources else []
        if index not in range(1, count + 1) or any(value not in range(1, count + 1) for value in parents):
            raise ValueError(f'dependency positions must be between 1 and {count}')
        if index in overrides or len(set(parents)) != len(parents):
            raise ValueError(f'duplicate dependency specification: {specification}')
        overrides[index] = parents
    return overrides


def read_task(source, supplied):
    task = load_yaml(source)
    if not isinstance(task, dict) or set(task) - {'procedure', 'variables'} != TASK_FIELDS:
        raise ValueError(f'{source}: require 9 task fields and optional procedure/variables; '
                         'id, depends_on and max_retries are supplied during assembly')
    values = bind_variables(task.pop('variables', {}), supplied)
    if task['task_type'] != 'normal':
        raise ValueError(f'{source}: assembly currently accepts normal tasks')
    for key in ['title', 'executor', 'verifier']:
        if not isinstance(task[key], str) or not task[key].strip():
            raise ValueError(f'{source}: {key} must be a nonempty string')
    for key in ['goal', 'approach', 'acceptance', 'out_of_scope'] + (['procedure'] if 'procedure' in task else []):
        value = task[key]
        if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError(f'{source}: {key} must be a nonempty list of nonempty strings')
    if task['on_exhaust'] not in ('exit', 'continue'):
        raise ValueError(f'{source}: on_exhaust must be exit or continue')
    return task, values


def assign_node_ids(nodes):
    by_id = {node['id']: node for node in nodes}
    depths, visiting = {}, set()

    def depth(tid):
        if tid in visiting:
            raise ValueError(f'dependency cycle at input position {int(tid) + 1}')
        if tid in depths:
            return depths[tid]
        visiting.add(tid)
        depths[tid] = 1 + max((depth(parent) for parent in by_id[tid]['depends_on']), default=-1)
        visiting.remove(tid)
        return depths[tid]

    for tid in by_id:
        depth(tid)
    # Preserve branch order across layers even when task inputs list the other branch first.
    ranks = {}
    for layer in sorted(set(depths.values())):
        peers = [tid for tid in by_id if depths[tid] == layer]
        peers.sort(key=lambda tid: (tuple(sorted(ranks.get(parent) for parent in by_id[tid]['depends_on'])),
                                    int(tid)))
        for branch, tid in enumerate(peers):
            ranks[tid] = (layer, branch) if len(peers) > 1 else (layer,)
    identifiers = {tid: '.'.join(map(str, rank)) for tid, rank in ranks.items()}
    for node in nodes:
        node['id'] = identifiers[node['id']]
        node['depends_on'] = [identifiers[parent] for parent in node['depends_on']]


def resolve_report_references(nodes, bindings):
    # Resolve report path IDs before handing the standard YAML to harness.
    by_id = {node['id']: node for node in nodes}
    ancestors = {}

    def upstream(tid):
        if tid not in ancestors:
            ancestors[tid] = set(by_id[tid]['depends_on'])
            for parent in by_id[tid]['depends_on']:
                ancestors[tid].update(upstream(parent))
        return ancestors[tid]

    for node, values in zip(nodes, bindings):
        expand_node_prompts(node, values, by_id, upstream)


def expand_node_prompts(node, values, by_id, upstream):
    def resolve_id(match):
        title = match.group(1)
        if title is None:
            return node['id']
        candidates = {tid for tid in upstream(node['id']) if by_id[tid]['title'] == title}
        # A later run of the same producer supersedes its earlier ancestor.
        nearest = candidates - {tid for candidate in candidates for tid in upstream(candidate)}
        if len(nearest) != 1:
            raise ValueError(f"node {node['id']}: report producer {title!r} must resolve to one upstream node")
        return next(iter(nearest))

    for field in ['goal', 'approach', 'procedure', 'acceptance', 'out_of_scope']:
        if field in node:
            node[field] = [re.sub(r'\{\{id(?::([^{}]+))?\}\}', resolve_id, item) for item in node[field]]
            if any('{{id' in item for item in node[field]):
                raise ValueError(f"node {node['id']}: malformed report ID placeholder")
            node[field] = [expand_variables(item, values) for item in node[field]]


def assemble(files, dependencies, retries, variables=None):
    count = len(files)
    if not count:
        raise ValueError('at least one task is required')
    if len(retries) != count or any(type(value) is not int or value < 0 for value in retries):
        raise ValueError('max_retries must be a nonnegative integer for every task')
    supplied = [{} for _ in files] if variables is None else variables
    if len(supplied) != count:
        raise ValueError('variables must be supplied for each task position')
    overrides = dependency_overrides(dependencies, count)
    nodes, bindings = [], []
    for index, source in enumerate(files, 1):
        task, values = read_task(source, supplied[index - 1])
        bindings.append(values)
        parents = overrides.get(index, [index - 1] if index > 1 else [])
        nodes.append({'id': str(index - 1), **task, 'max_retries': retries[index - 1],
                      'depends_on': [str(value - 1) for value in parents]})
    assign_node_ids(nodes)
    resolve_report_references(nodes, bindings)
    return {'workflow': 'ops-direct-invoke', 'max_parallel': 2, 'nodes': nodes}


def template_positions(nodes):
    positions = {}
    for index, node in enumerate(nodes, 1):
        if not isinstance(node, dict) or set(node) - {'variables'} != {'id', 'yaml', 'depends_on', 'max_retries'}:
            raise ValueError('template nodes require id, yaml, depends_on and max_retries; optional variables')
        identifier = node['id']
        if not isinstance(identifier, str) or not re.fullmatch(r'\d+(?:\.\d+)?', identifier):
            raise ValueError('template id must be a numeric string')
        if identifier in positions:
            raise ValueError(f'duplicate template id: {identifier}')
        positions[identifier] = index
        if not isinstance(node['yaml'], str) or not node['yaml'].strip():
            raise ValueError('task yaml must be a nonempty path')
    return positions


def assemble_template(path):
    """Expand a reference graph using paths relative to the template file."""
    template = load_yaml(path)
    if not isinstance(template, dict) or set(template) != {'workflow', 'max_parallel', 'nodes'}:
        raise ValueError('template requires workflow, max_parallel and nodes')
    if not isinstance(template['workflow'], str) or not template['workflow'].strip():
        raise ValueError('workflow must be a nonempty string')
    if type(template['max_parallel']) is not int or template['max_parallel'] < 1:
        raise ValueError('max_parallel must be a positive integer')
    nodes = template['nodes']
    if not isinstance(nodes, list) or not nodes:
        raise ValueError('template nodes must be a nonempty list')
    positions = template_positions(nodes)
    dependencies = []
    for index, node in enumerate(nodes, 1):
        parents = node['depends_on']
        if (not isinstance(parents, list)
                or any(not isinstance(parent, str) or parent not in positions for parent in parents)):
            raise ValueError('depends_on must reference template node IDs')
        dependencies.append(f"{index}:" + ','.join(str(positions.get(parent)) for parent in parents))
    definition = assemble([path.parent / node['yaml'] for node in nodes], dependencies,
                          [node['max_retries'] for node in nodes], [node.get('variables', {}) for node in nodes])
    if [node['id'] for node in definition['nodes']] != list(positions):
        raise ValueError('template IDs must match dependency layers and branch order')
    definition.update(workflow=template['workflow'], max_parallel=template['max_parallel'])
    return definition


def write_workflow(definition, output):
    """Freeze a complete harness input without overwriting an existing run."""
    rendered = yaml.safe_dump(definition, allow_unicode=True, sort_keys=False, width=110)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        stream.write(rendered)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tasks', nargs='*', type=Path, help='task YAML paths; positions start at 1')
    parser.add_argument('--template', type=Path, help='reference workflow template path')
    parser.add_argument('--max-retries', type=int, help='required with task paths; retry budget for each task')
    parser.add_argument('--output', required=True, type=Path, help='new workflow.yaml path; never overwritten')
    parser.add_argument('--depends-on', action='append', default=[], metavar='N:M,K',
                        help='override dependencies of input N with M,K; N: means none; repeat for multiple tasks')
    args = parser.parse_args()
    try:
        if args.template is not None:
            if args.tasks or args.depends_on or args.max_retries is not None:
                raise ValueError('--template cannot be combined with task paths, --depends-on or --max-retries')
            definition = assemble_template(args.template.resolve(strict=True))
        else:
            if args.max_retries is None:
                raise ValueError('--max-retries is required with task paths')
            definition = assemble(args.tasks, args.depends_on, [args.max_retries] * len(args.tasks))
        output = args.output.absolute()
        write_workflow(definition, output)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    LOGGER.info("%s (%s tasks)", output, len(definition["nodes"]))


if __name__ == '__main__':
    main()
