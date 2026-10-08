# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""Lazy expansion and direct-child state aggregation for nested task graphs."""

import os


def effective_status(tid, tasks, members, skipped=frozenset(), completed=frozenset()):
    """Subgraph nodes settle only when every direct child (including subgraphs) does."""
    if tid in skipped:
        return "skipped"
    if tid in completed:
        return "pass"
    if tid not in members:
        return tasks.get(tid, {}).get("status", "pending")
    kids = members[tid]
    if not kids:
        return "pending"
    return (
        "pass"
        if all(
            effective_status(k, tasks, members, skipped, completed) == "pass"
            for k in kids
        )
        else "running"
    )


class TaskGraph:
    """One dispatch's graph; loader(path) returns validated (local nodes, error).

    node_by_id contains qualified dependencies but keeps local rollback_to values.
    subs retains each loaded file's local definitions for checkpoint discovery.
    Only normal nodes are registered in the persistent task ledger.
    known_members stores discovered topology across dispatches; completed is a
    transient cache derived from that topology and the current normal-task states.
    """

    def __init__(self, work_dir, nodes, tasks, loader, known_members=None):
        self.work_dir, self.tasks, self.loader = work_dir, tasks, loader
        self.node_by_id, self.members, self.subs = {}, {}, {}
        self.file_chains, self.resolved = {}, set()
        # Persist topology, never subgraph execution states. It distinguishes a
        # finished subgraph from one with as-yet-unmaterialized inner graphs.
        self.known_members = dict(known_members or {})
        self.completed = set()
        self.legacy = known_members is None
        self.changed = False
        self.roots = self._add_nodes(nodes, "", ())

    def effective(self, tid, skipped=frozenset()):
        return effective_status(tid, self.tasks, self.members, skipped, self.completed)

    def materialize(self):
        for tid in self.roots:
            err = self._expand(tid)
            if err:
                return err
        return None

    def stream(self):
        """Normal task candidates in depth-first YAML order."""

        def walk(ids):
            for tid in ids:
                if tid in self.members:
                    yield from walk(self.members[tid])
                else:
                    node = self.node_by_id[tid]
                    yield node, tid, node["depends_on"]

        return list(walk(self.roots))

    def _add_nodes(self, nodes, parent, file_chain):
        ids = []
        for node in nodes:
            prefix = parent + "/" if parent else ""
            tid = prefix + node["id"]
            ids.append(tid)
            self.node_by_id[tid] = dict(
                node, depends_on=[prefix + d for d in node["depends_on"]]
            )
            if node["task_type"] == "subgraph":
                self.members[tid] = []
                if tid not in self.known_members:
                    # Old ledgers supported only one level. Retain their ability
                    # to resume completed subgraphs after generated YAML cleanup.
                    kids = [k for k in self.tasks if k.rpartition("/")[0] == tid]
                    self.known_members[tid] = kids if self.legacy else []
                self.file_chains[tid] = file_chain
                if tid in self.tasks:
                    del self.tasks[tid]
                    self.changed = True
            elif parent and tid not in self.tasks:
                entry = {"status": "pending", "retries": 0}
                if node.get("require_approval"):
                    entry["require_approval"] = True
                self.tasks[tid] = entry
                self.changed = True
        return ids

    def _expand(self, tid):
        if tid not in self.members or tid in self.resolved:
            return None
        self.resolved.add(tid)
        node = self.node_by_id[tid]
        # Resolve sibling subgraphs before testing their aggregate state. YAML
        # order is presentation order, not a required topological ordering.
        for dep in node["depends_on"]:
            err = self._expand(dep)
            if err:
                return err
        if not all(self.effective(d) == "pass" for d in node["depends_on"]):
            return None
        if effective_status(tid, self.tasks, self.known_members) == "pass":
            self.completed.add(tid)
            return None
        path = os.path.join(self.work_dir, node["file"])
        real_path = os.path.realpath(path)
        chain = self.file_chains[tid]
        if real_path in chain:
            return "subgraph %s 文件循环引用: %s" % (
                tid,
                " -> ".join(chain + (real_path,)),
            )
        if not os.path.isfile(path):
            return "subgraph %s 依赖已满足但 file 不存在: %s" % (tid, path)
        children, err = self.loader(path)
        if err:
            return "subgraph %s 校验失败(%s): %s" % (tid, path, err)
        self.subs[tid] = children
        self.members[tid] = self._add_nodes(children, tid, chain + (real_path,))
        self.known_members[tid] = self.members[tid]
        for child in self.members[tid]:
            err = self._expand(child)
            if err:
                return err
        return None
