# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""Nested subgraph behavior through dispatch, polling and dry-run CLIs."""

import json
import shutil
import unittest
from pathlib import Path

import yaml

from test_approval import APPROVE_TASK, GET_TASK, SCRIPTS, make_workdir, run_script
from test_orchestrator import _node, read_status, run_orchestrator, WorkflowOptions


def subgraph(tid, file, deps=()):
    return {"id": tid, "task_type": "subgraph", "file": file, "depends_on": list(deps)}


class NestedSubgraphsTest(unittest.TestCase):
    def workspace(self, outer=None, inner=None, max_parallel=2):
        wd = make_workdir(
            self,
            [subgraph("outer", "outer.yaml"), _node("after", depends_on=["outer"])],
            {"after": {"status": "pending", "retries": 0}},
            max_parallel,
        )
        self.write_nodes(
            wd,
            "outer.yaml",
            outer if outer is not None else [subgraph("inner", "inner.yaml")],
        )
        if inner is not None:
            self.write_nodes(wd, "inner.yaml", inner)
        return wd

    def write_nodes(self, wd, name, nodes):
        path = Path(wd) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"nodes": nodes}, sort_keys=False))

    def dispatch(self, wd):
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def mark(self, wd, tid, state, **extra):
        status = read_status(wd)
        status["tasks"][tid].update(status=state, **extra)
        (Path(wd) / ".workflow/status.json").write_text(json.dumps(status))

    def test_nested_parallel_tasks_and_restart_aggregate(self):
        wd = self.workspace(inner=[_node("b"), _node("c")])
        self.assertEqual(
            [t["task_id"] for t in self.dispatch(wd)],
            ["outer/inner/b", "outer/inner/c"],
        )
        self.assertEqual(
            set(read_status(wd)["tasks"]), {"after", "outer/inner/b", "outer/inner/c"}
        )
        self.mark(wd, "outer/inner/b", "running")
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/inner/c"])
        self.mark(wd, "outer/inner/b", "pass")
        self.mark(wd, "outer/inner/c", "pass")
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["after"])
        self.mark(wd, "after", "pass")
        self.assertEqual(self.dispatch(wd), {"result": "[ALL TASK FINISHED]"})

    def test_late_generated_file_does_not_finish_parent_early(self):
        wd = self.workspace(
            outer=[
                _node("generate"),
                subgraph("inner", "generated/inner.yaml", ["generate"]),
            ]
        )
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/generate"])
        self.assertNotIn("outer/inner", read_status(wd)["tasks"])
        self.mark(wd, "outer/generate", "pass")
        self.write_nodes(wd, "generated/inner.yaml", [_node("b")])
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/inner/b"])

    def test_completed_nested_graph_survives_yaml_cleanup(self):
        wd = self.workspace(inner=[_node("b")])
        self.dispatch(wd)
        self.mark(wd, "outer/inner/b", "pass")
        (Path(wd) / "outer.yaml").unlink()
        (Path(wd) / "inner.yaml").unlink()
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["after"])

    def test_legacy_completed_single_level_graph_survives_yaml_cleanup(self):
        wd = make_workdir(
            self,
            [subgraph("sg", "removed.yaml"), _node("after", depends_on=["sg"])],
            {
                "sg/leaf": {"status": "pass", "retries": 0},
                "after": {"status": "pending", "retries": 0},
            },
        )
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["after"])

    def test_completed_nested_sibling_aggregates_with_skip_after_cleanup(self):
        wd = self.workspace(
            outer=[
                subgraph("inner", "inner.yaml"),
                _node("bad", on_exhaust="continue"),
            ],
            inner=[_node("x")],
        )
        self.dispatch(wd)
        self.mark(wd, "outer/inner/x", "pass")
        self.mark(wd, "outer/bad", "fail", retries=1)
        (Path(wd) / "inner.yaml").unlink()
        result = self.dispatch(wd)
        self.assertEqual(result["result"], "[ALL TASK FINISHED]")
        self.assertEqual(set(result["skipped"]), {"outer", "outer/bad", "after"})

    def test_subgraph_dependencies_work_in_reverse_yaml_order(self):
        wd = self.workspace(
            outer=[
                _node("last", depends_on=["inner"]),
                subgraph("inner", "inner.yaml"),
            ],
            inner=[_node("b")],
        )
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/inner/b"])
        self.mark(wd, "outer/inner/b", "pass")
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/last"])

    def test_sibling_subgraph_dependencies_in_reverse_yaml_order(self):
        wd = self.workspace(
            outer=[
                subgraph("right", "right.yaml", ["left"]),
                subgraph("left", "inner.yaml"),
            ],
            inner=[_node("x")],
        )
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/left/x"])
        self.mark(wd, "outer/left/x", "pass")
        self.write_nodes(wd, "right.yaml", [_node("x")])
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["outer/right/x"])

    def test_missing_ready_nested_file_is_an_error(self):
        wd = self.workspace()
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("outer/inner", proc.stderr)
        self.assertIn("file 不存在", proc.stderr)

    def test_nested_dependencies_and_rollback_stay_local(self):
        for bad_node in (
            _node("b", depends_on=["after"]),
            _node("b", on_exhaust="rollback", rollback_to="after"),
        ):
            with self.subTest(node=bad_node):
                wd = self.workspace(inner=[bad_node])
                proc = run_script(GET_TASK, wd)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("outer/inner", proc.stderr)
                self.assertIn("引用不存在", proc.stderr)

    def test_skipped_unmaterialized_nested_subgraph_propagates(self):
        wd = self.workspace(
            outer=[
                _node("generate", on_exhaust="continue"),
                subgraph("inner", "missing.yaml", ["generate"]),
            ]
        )
        self.dispatch(wd)
        self.mark(wd, "outer/generate", "fail", retries=1)
        result = self.dispatch(wd)
        self.assertEqual(result["result"], "[ALL TASK FINISHED]")
        self.assertEqual(
            set(result["skipped"]), {"outer/generate", "outer/inner", "outer", "after"}
        )

    def test_nested_skip_waits_for_independent_sibling(self):
        wd = self.workspace(inner=[_node("bad", on_exhaust="continue"), _node("good")])
        self.dispatch(wd)
        self.mark(wd, "outer/inner/bad", "fail", retries=1)
        self.assertEqual(
            [t["task_id"] for t in self.dispatch(wd)], ["outer/inner/good"]
        )
        self.mark(wd, "outer/inner/good", "pass")
        result = self.dispatch(wd)
        self.assertEqual(
            set(result["skipped"]), {"outer/inner/bad", "outer/inner", "outer", "after"}
        )

    def test_sibling_subgraphs_can_reuse_file_and_local_ids(self):
        wd = self.workspace(
            outer=[subgraph("left", "inner.yaml"), subgraph("right", "inner.yaml")],
            inner=[_node("x")],
        )
        self.assertEqual(
            [t["task_id"] for t in self.dispatch(wd)], ["outer/left/x", "outer/right/x"]
        )

    def test_recursive_file_reference_reports_error(self):
        wd = self.workspace(outer=[subgraph("inner", "alias.yaml")])
        (Path(wd) / "alias.yaml").symlink_to(Path(wd) / "outer.yaml")
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("循环引用", proc.stderr)
        self.assertIn("outer/inner", proc.stderr)

    def test_nested_approval_polling_and_completion(self):
        wd = self.workspace(
            inner=[_node("b", title="深层审批", require_approval=["确认结果"])]
        )
        self.dispatch(wd)
        self.assertTrue(read_status(wd)["tasks"]["outer/inner/b"]["require_approval"])
        self.mark(wd, "outer/inner/b", "awaiting_approval")
        proc = run_script(SCRIPTS / "poll_workflow.py", "--work-dir", wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("outer/inner/b「深层审批」", proc.stdout)
        self.assertIn("确认结果", proc.stdout)
        self.assertEqual(self.dispatch(wd), [])
        proc = run_script(
            APPROVE_TASK,
            "--work-dir",
            wd,
            "--task-id",
            "outer/inner/b",
            "--decision",
            "approve",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([t["task_id"] for t in self.dispatch(wd)], ["after"])

    def test_nested_approval_redo_and_terminal_failure(self):
        wd = self.workspace(
            inner=[
                _node("b", require_approval=True, max_retries=3, on_exhaust="continue")
            ]
        )
        self.dispatch(wd)
        self.mark(wd, "outer/inner/b", "awaiting_approval")
        proc = run_script(
            APPROVE_TASK,
            "--work-dir",
            wd,
            "--task-id",
            "outer/inner/b",
            "--decision",
            "redo",
            "--comment",
            "补充验证",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        batch = self.dispatch(wd)
        self.assertEqual(batch[0]["task_id"], "outer/inner/b")
        self.assertIn("补充验证", batch[0]["prompt"])
        self.mark(wd, "outer/inner/b", "awaiting_approval")
        proc = run_script(
            APPROVE_TASK,
            "--work-dir",
            wd,
            "--task-id",
            "outer/inner/b",
            "--decision",
            "fail",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = self.dispatch(wd)
        self.assertEqual(result["result"], "[ALL TASK FINISHED]")
        self.assertIn("outer/inner/b", result["skipped"])
        self.assertEqual(read_status(wd)["tasks"]["outer/inner/b"]["retries"], 4)

    def run_workflow(self, **kwargs):
        code, out, wd = run_orchestrator(**kwargs)
        self.addCleanup(shutil.rmtree, wd)
        self.assertEqual(code, 0, out)
        return wd

    def test_three_levels_subgraph_only_workflow(self):
        wd = self.run_workflow(
            nodes=[subgraph("outer", "outer.yaml")],
            pre_files={
                "outer.yaml": yaml.safe_dump(
                    {"nodes": [subgraph("middle", "middle.yaml")]}
                ),
                "middle.yaml": yaml.safe_dump(
                    {"nodes": [subgraph("inner", "inner.yaml")]}
                ),
                "inner.yaml": yaml.safe_dump({"nodes": [_node("leaf")]}),
            },
        )
        tasks = read_status(wd)["tasks"]
        self.assertEqual(set(tasks), {"outer/middle/inner/leaf"})
        self.assertEqual(tasks["outer/middle/inner/leaf"]["status"], "pass")

    def test_nested_retry_and_rollback(self):
        for rollback in (False, True):
            with self.subTest(rollback=rollback):
                b = (
                    _node("b", depends_on=["a"], on_exhaust="rollback", rollback_to="a")
                    if rollback
                    else _node("b", depends_on=["a"], max_retries=1)
                )
                wd = self.run_workflow(
                    nodes=[subgraph("outer", "outer.yaml")],
                    options=WorkflowOptions(max_parallel=2),
                    pre_files={
                        "outer.yaml": yaml.safe_dump(
                            {"nodes": [subgraph("inner", "inner.yaml")]}
                        ),
                        "inner.yaml": yaml.safe_dump({"nodes": [_node("a"), b]}),
                    },
                    dry_replies={
                        "outer/inner/b": [
                            "executed",
                            "$VERDICT:fail",
                            "executed",
                            "$VERDICT:pass",
                        ]
                    },
                )
                status = read_status(wd)
                self.assertTrue(
                    all(t["status"] == "pass" for t in status["tasks"].values())
                )
                self.assertEqual(status["rollbacks_used"], int(rollback))
                if rollback:
                    self.assertEqual(status["checkpoint_targets"], ["outer/inner/a"])
                    self.assertTrue(
                        (Path(wd) / ".workflow/checkpoints/outer/inner/a").is_dir()
                    )


if __name__ == "__main__":
    unittest.main()
