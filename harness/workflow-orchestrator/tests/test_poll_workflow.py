# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""轮询脚本 poll_workflow 测试。

覆盖 stdout 关键事件、进展块（进度条与任务窗口）、待审批条目，以及偏移持久化与自愈。
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402
from test_orchestrator import _node, _workflow_yaml  # noqa: E402
from test_approval import make_workdir, run_script  # noqa: E402

POLL = SCRIPTS / "poll_workflow.py"

LOG_LINES = [
    json.dumps({"event": "init", "workflow": "t", "tasks": 1,
                "timestamp": "2026-09-23 10:00:01"}),
    json.dumps({"event": "update", "task_id": "a", "from": "pending",
                "to": "running", "timestamp": "2026-09-23 10:00:05"}),
    json.dumps({"event": "verdict", "task_id": "a", "verdict": "pass",
                "timestamp": "2026-09-23 10:02:00"}),
    json.dumps({"event": "update", "task_id": "a", "from": "verifying",
                "to": "pass", "timestamp": "2026-09-23 10:02:12"}),
]


def write_log(work_dir, lines):
    log = Path(work_dir) / ".workflow" / "log.jsonl"
    log.write_text("".join(line + "\n" for line in lines))
    return log


def append_log(work_dir, line):
    with open(Path(work_dir) / ".workflow" / "log.jsonl", "a") as f:
        f.write(line + "\n")


class PollCase(unittest.TestCase):
    def poll(self, work_dir):
        r = run_script(POLL, "--work-dir", work_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.rstrip("\n")

    def write_status(self, work_dir, tasks):
        p = Path(work_dir) / ".workflow" / "status.json"
        status = json.loads(p.read_text())
        status["tasks"] = tasks
        p.write_text(json.dumps(status))

    def state_path(self, work_dir):
        return Path(work_dir) / ".workflow" / "skill_poll.state"


class EventsTest(PollCase):
    def setUp(self):
        self.work_dir = make_workdir(self, [_node("a")],
                                     {"a": {"status": "pending", "retries": 0}})
        self.progress_idle = "进展 ░░░░░░░░░░░░░░░░░░░░ 0%（0/1）\n○ a"

    def test_missing_log_only_progress(self):
        self.assertEqual(self.poll(self.work_dir), self.progress_idle)

    def test_first_call_renders_key_events(self):
        write_log(self.work_dir, LOG_LINES)
        out = self.poll(self.work_dir)
        self.assertIn("[10:00:05] a: pending → running", out)
        self.assertIn("[10:02:12] a: verifying → pass", out)
        self.assertNotIn("init", out)     # 非关键事件被过滤
        self.assertNotIn("verdict", out)

    def test_no_growth_still_shows_progress(self):
        write_log(self.work_dir, LOG_LINES)
        self.poll(self.work_dir)
        # 心跳：无新事件时事件段为空，但进展块每轮都输出
        self.assertEqual(self.poll(self.work_dir), self.progress_idle)

    def test_incremental_after_append(self):
        write_log(self.work_dir, LOG_LINES)
        self.poll(self.work_dir)
        append_log(self.work_dir, json.dumps({
            "event": "approval_ignored", "task_id": "a",
            "reason": "decision 非法", "timestamp": "2026-09-23 10:30:00"}))
        self.assertEqual(self.poll(self.work_dir),
                         "[10:30:00] 审批被忽略：a（decision 非法）"
                         "\n\n" + self.progress_idle)

    def test_awaiting_approval_suffix(self):
        write_log(self.work_dir, LOG_LINES)
        self.poll(self.work_dir)
        append_log(self.work_dir, json.dumps({
            "event": "update", "task_id": "a", "from": "verifying",
            "to": "awaiting_approval", "timestamp": "2026-09-23 10:31:00"}))
        self.assertEqual(self.poll(self.work_dir),
                         "[10:31:00] a: verifying → awaiting_approval（进入待审批）"
                         "\n\n" + self.progress_idle)

    def test_rollback_and_approval_rendering(self):
        write_log(self.work_dir, LOG_LINES)
        self.poll(self.work_dir)
        append_log(self.work_dir, json.dumps({
            "event": "rollback", "from": "c", "to": "a",
            "timestamp": "2026-09-23 10:32:00"}))
        append_log(self.work_dir, json.dumps({
            "event": "approval", "task_id": "b", "decision": "redo",
            "comment": "重做意见", "timestamp": "2026-09-23 10:32:30"}))
        self.assertEqual(self.poll(self.work_dir),
                         "[10:32:00] 回滚 c → a\n[10:32:30] b: 审批 redo：重做意见"
                         "\n\n" + self.progress_idle)

    def test_unparseable_line_shown_raw(self):
        write_log(self.work_dir, LOG_LINES)
        self.poll(self.work_dir)
        append_log(self.work_dir, "not-json{{")
        self.assertEqual(self.poll(self.work_dir),
                         "not-json{{\n\n" + self.progress_idle)

    def test_state_persisted(self):
        write_log(self.work_dir, LOG_LINES)
        self.poll(self.work_dir)
        state = json.loads(self.state_path(self.work_dir).read_text())
        self.assertEqual(state, {"events_offset": len(LOG_LINES)})  # 状态只留偏移

    def test_corrupt_state_self_heals_with_full_replay(self):
        write_log(self.work_dir, LOG_LINES)
        self.state_path(self.work_dir).write_text("garbage")
        out = self.poll(self.work_dir)
        self.assertIn("[10:00:05] a: pending → running", out)
        state = json.loads(self.state_path(self.work_dir).read_text())
        self.assertEqual(state["events_offset"], len(LOG_LINES))

    def test_offset_beyond_eof_stays_silent(self):
        write_log(self.work_dir, LOG_LINES)
        self.state_path(self.work_dir).write_text(
            json.dumps({"events_offset": 99}))
        self.assertNotIn("[10:00:05]", self.poll(self.work_dir))


class ProgressTest(PollCase):
    def test_missing_status_silent(self):
        work_dir = make_workdir(self, [_node("a")],
                                {"a": {"status": "pending", "retries": 0}})
        (Path(work_dir) / ".workflow" / "status.json").unlink()
        self.assertEqual(self.poll(work_dir), "")

    def test_bar_and_task_window(self):
        nodes = [_node("a"), _node("b", depends_on=["a"]),
                 _node("c", depends_on=["b"])]
        work_dir = make_workdir(self, nodes, self._tasks(
            ("a", "pass"), ("b", "running"), ("c", "pending")))
        self.assertEqual(self.poll(work_dir), (
            "进展 ███████░░░░░░░░░░░░░ 33%（1/3）\n"
            "✓ a\n"
            "▶ b（running）\n"
            "○ c"))

    def test_change_reprints(self):
        work_dir = make_workdir(
            self, [_node("a"), _node("b", depends_on=["a"])],
            self._tasks(("a", "pass"), ("b", "running")))
        first = self.poll(work_dir)
        self.assertEqual(self.poll(work_dir), first)  # 心跳：内容不变也每轮输出
        self.write_status(work_dir, self._tasks(("a", "pass"), ("b", "verifying")))
        self.assertEqual(self.poll(work_dir), (
            "进展 ██████████░░░░░░░░░░ 50%（1/2）\n"
            "✓ a\n"
            "▶ b（verifying）"))

    def test_window_anchors_on_active(self):
        # 8 个任务，t4 在跑：窗口显示 t2..t6（上方保留 2 条已完成），两侧 … 截断
        nodes = [_node("t%d" % i) for i in range(8)]
        work_dir = make_workdir(self, nodes, self._tasks(
            *[("t%d" % i, "pass" if i < 4 else "running" if i == 4 else "pending")
              for i in range(8)]))
        self.assertEqual(self.poll(work_dir), (
            "进展 ██████████░░░░░░░░░░ 50%（4/8）\n"
            "…\n"
            "✓ t2\n"
            "✓ t3\n"
            "▶ t4（running）\n"
            "○ t5\n"
            "○ t6\n"
            "…"))

    def test_all_pass_shows_tail_window(self):
        nodes = [_node("t%d" % i) for i in range(8)]
        work_dir = make_workdir(self, nodes, self._tasks(
            *[("t%d" % i, "pass") for i in range(8)]))
        self.assertEqual(self.poll(work_dir), (
            "进展 ████████████████████ 100%（8/8）\n"
            "…\n"
            "✓ t3\n"
            "✓ t4\n"
            "✓ t5\n"
            "✓ t6\n"
            "✓ t7"))

    def test_fail_marker_and_alert(self):
        work_dir = make_workdir(self, [_node("a"), _node("b")],
                                self._tasks(("a", "fail"), ("b", "pending")))
        self.assertEqual(self.poll(work_dir), (
            "进展 ░░░░░░░░░░░░░░░░░░░░ 0%（0/2）｜fail 1\n"
            "✗ a（fail）\n"
            "○ b"))

    def test_awaiting_approval_marker_and_alert(self):
        work_dir = make_workdir(
            self, [_node("a"), _node("b", require_approval=True), _node("c")],
            self._tasks(("a", "pass"), ("b", "awaiting_approval"),
                        ("c", "pending")))
        self.assertEqual(self.poll(work_dir), (
            "进展 ███████░░░░░░░░░░░░░ 33%（1/3）｜待审批 1\n"
            "✓ a\n"
            "◉ b（待审批）\n"
            "○ c\n"
            "\n"
            "◉ 待审批 b「Task b」\n"
            "  验收：\n"
            "  - true"))

    def test_completed_grouped_on_top_by_recency(self):
        # 并行任务"后登记先完成"（y1/y2 登记在 mid 之后但已 pass）：
        # 窗口按状态分组——最近完成在上（pass_seq 新靠下）、进行中居中、待执行在下
        nodes = [_node(t) for t in ("x1", "x2", "mid", "y1", "y2", "z")]
        tasks = {
            "x1": {"status": "pass", "retries": 0, "pass_seq": 1},
            "x2": {"status": "pass", "retries": 0, "pass_seq": 2},
            "mid": {"status": "verifying", "retries": 0},
            "y1": {"status": "pass", "retries": 0, "pass_seq": 3},
            "y2": {"status": "pass", "retries": 0, "pass_seq": 4},
            "z": {"status": "pending", "retries": 0},
        }
        work_dir = make_workdir(self, nodes, tasks)
        self.assertEqual(self.poll(work_dir), (
            "进展 █████████████░░░░░░░ 67%（4/6）\n"
            "…\n"
            "✓ x2\n"  # 待执行不足时窗口由已完成回填
            "✓ y1\n"
            "✓ y2\n"
            "▶ mid（verifying）\n"
            "○ z"))

    def test_middle_overflow_truncated(self):
        # 进行中超过窗口容量：挤占他段并截断
        nodes = [_node("r%d" % i) for i in range(6)]
        work_dir = make_workdir(self, nodes, self._tasks(
            *[("r%d" % i, "running") for i in range(6)]))
        self.assertEqual(self.poll(work_dir), (
            "进展 ░░░░░░░░░░░░░░░░░░░░ 0%（0/6）\n"
            "▶ r0（running）\n"
            "▶ r1（running）\n"
            "▶ r2（running）\n"
            "▶ r3（running）\n"
            "▶ r4（running）\n"
            "…"))

    def test_idle_needs_no_yaml(self):
        # 无待审批任务时不加载 yaml：删掉 workflow.yaml 仍正常渲染
        work_dir = make_workdir(self, [_node("a")],
                                {"a": {"status": "pending", "retries": 0}})
        (Path(work_dir) / "workflow.yaml").unlink()
        self.assertEqual(self.poll(work_dir),
                         "进展 ░░░░░░░░░░░░░░░░░░░░ 0%（0/1）\n○ a")

    def test_corrupt_status_fails(self):
        work_dir = make_workdir(self, [_node("a")],
                                {"a": {"status": "pending", "retries": 0}})
        (Path(work_dir) / ".workflow" / "status.json").write_text("{oops")
        r = run_script(POLL, "--work-dir", work_dir)
        self.assertEqual(r.returncode, 2)

    def _tasks(self, *pairs):
        """(tid, status) 序列 → tasks dict（保序）。"""
        return {tid: {"status": st, "retries": 0} for tid, st in pairs}


class PendingApprovalsTest(PollCase):
    def test_awaiting_task_listed(self):
        work_dir = make_workdir(
            self, [_node("a", title="实现功能", acceptance=["测试通过"])],
            {"a": {"status": "awaiting_approval", "retries": 0,
                   "require_approval": True}})
        out = self.poll(work_dir)
        self.assertIn("◉ 待审批 a「实现功能」\n  验收：\n  - 测试通过", out)
        self.assertNotIn("确认提示", out)  # require_approval 为 true（裸门禁）时无此段

    def test_approval_hint_rendered(self):
        # require_approval 为确认提示列表：门禁 + 提示同键配置
        work_dir = make_workdir(
            self, [_node("a", title="实现功能", acceptance=["测试通过"],
                         require_approval=["确认 spec 覆盖全部需求",
                                           "接口命名符合规范"])],
            {"a": {"status": "awaiting_approval", "retries": 0,
                   "require_approval": True}})
        out = self.poll(work_dir)
        self.assertIn("◉ 待审批 a「实现功能」\n  验收：\n  - 测试通过\n"
                      "  确认提示：\n  - 确认 spec 覆盖全部需求\n"
                      "  - 接口命名符合规范", out)

    def test_answered_task_excluded(self):
        work_dir = make_workdir(
            self, [_node("a")],
            {"a": {"status": "awaiting_approval", "retries": 0,
                   "require_approval": True}})
        ap_dir = Path(work_dir) / ".workflow" / "approvals"
        ap_dir.mkdir(parents=True)
        (ap_dir / "a.json").write_text(json.dumps({"decision": "approve"}))
        self.assertNotIn("◉ 待审批", self.poll(work_dir))

    def test_non_awaiting_excluded(self):
        work_dir = make_workdir(
            self, [_node("a"), _node("b", require_approval=True)],
            {"a": {"status": "running", "retries": 0},
             "b": {"status": "awaiting_approval", "retries": 0,
                   "require_approval": True}})
        out = self.poll(work_dir)
        self.assertIn("◉ 待审批 b「Task b」", out)
        self.assertNotIn("◉ 待审批 a", out)

    def test_subtask_resolved_from_subgraph(self):
        sg = {"id": "sg", "task_type": "subgraph", "file": "sg.yaml",
              "depends_on": []}
        work_dir = make_workdir(self, [sg],
                                {"sg/child": {"status": "awaiting_approval",
                                              "retries": 0,
                                              "require_approval": True}})
        (Path(work_dir) / "sg.yaml").write_text(yaml.safe_dump(
            {"nodes": [_node("child", title="子任务", acceptance=["ac"])]},
            sort_keys=False))
        self.assertIn("◉ 待审批 sg/child「子任务」\n  验收：\n  - ac",
                      self.poll(work_dir))

    def test_subtask_with_encoded_approval_file_excluded(self):
        sg = {"id": "sg", "task_type": "subgraph", "file": "sg.yaml",
              "depends_on": []}
        work_dir = make_workdir(self, [sg],
                                {"sg/child": {"status": "awaiting_approval",
                                              "retries": 0,
                                              "require_approval": True}})
        (Path(work_dir) / "sg.yaml").write_text(yaml.safe_dump(
            {"nodes": [_node("child")]}, sort_keys=False))
        ap_dir = Path(work_dir) / ".workflow" / "approvals"
        ap_dir.mkdir(parents=True)
        # 百分号编码契约：独立于实现侧 quote() 硬编码，防双向同错
        (ap_dir / "sg%2Fchild.json").write_text(json.dumps({"decision": "approve"}))
        self.assertNotIn("◉ 待审批", self.poll(work_dir))

    def test_unknown_awaiting_task_fails(self):
        work_dir = make_workdir(self, [_node("a")],
                                {"ghost": {"status": "awaiting_approval",
                                           "retries": 0}})
        r = run_script(POLL, "--work-dir", work_dir)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
