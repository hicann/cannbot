# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""人工审批门禁（require_approval）测试。

覆盖契约校验、init 落标记、状态迁移、approve_task 写入、get_task 收割与派发分支。
"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402
import get_task  # noqa: E402  白盒：validate_workflow / harvest_approvals
from test_orchestrator import ORCHESTRATOR, _node, _workflow_yaml, read_status, read_log  # noqa: E402

INIT_STATUS = SCRIPTS / "init_status.py"
UPDATE_STATUS = SCRIPTS / "update_status.py"
APPROVE_TASK = SCRIPTS / "approve_task.py"
GET_TASK = SCRIPTS / "get_task.py"


def run_script(script, *args):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True)


def make_workdir(tc, nodes, tasks, max_parallel=2):
    """构造手工 work_dir（workflow.yaml + .workflow/status.json + user_prompt.md）。"""
    temp_dir = tempfile.TemporaryDirectory(prefix="wo-appr-")
    tc.addCleanup(temp_dir.cleanup)
    work_dir = temp_dir.name
    wf = Path(work_dir) / "workflow.yaml"
    wf.write_text(_workflow_yaml(nodes, max_parallel))
    wr = Path(work_dir) / ".workflow"
    wr.mkdir()
    (wr / "user_prompt.md").write_text("test\n")
    (wr / "status.json").write_text(json.dumps({
        "workflow": str(wf), "work_dir": work_dir,
        "user_prompt": str(wr / "user_prompt.md"),
        "seq": 0, "rollbacks_used": 0, "tasks": tasks}))
    return work_dir


def write_approval(work_dir, task_id, data=None, raw=None):
    """直接写审批文件（raw 优先，用于构造损坏文件）；返回文件路径。"""
    ap_dir = Path(work_dir) / ".workflow" / "approvals"
    ap_dir.mkdir(parents=True, exist_ok=True)
    path = ap_dir / (task_id + ".json")
    path.write_text(raw if raw is not None else json.dumps(data))
    return path


class ContractTest(unittest.TestCase):
    def test_require_approval_accepted_bool(self):
        err = get_task.validate_workflow({
            "workflow": "t", "max_parallel": 1,
            "nodes": [_node("a", require_approval=True)]})
        self.assertIsNone(err)

    def test_require_approval_rejects_non_bool(self):
        err = get_task.validate_workflow({
            "workflow": "t", "max_parallel": 1,
            "nodes": [_node("a", require_approval="yes")]})
        self.assertIn("require_approval 必须是 bool", err)

    def test_subgraph_rejects_require_approval(self):
        err = get_task.validate_workflow({
            "workflow": "t", "max_parallel": 1,
            "nodes": [{"id": "sg", "task_type": "subgraph", "file": "sg.yaml",
                       "depends_on": [], "require_approval": True}]})
        self.assertIn("键不符", err)

    def test_require_approval_hint_list_accepted(self):
        err = get_task.validate_workflow({
            "workflow": "t", "max_parallel": 1,
            "nodes": [_node("a", require_approval=["检查 spec 完整性"])]})
        self.assertIsNone(err)

    def test_require_approval_rejects_bad_hint_list(self):
        for bad in ([], ["ok", ""], [1]):
            err = get_task.validate_workflow({
                "workflow": "t", "max_parallel": 1,
                "nodes": [_node("a", require_approval=bad)]})
            self.assertIn("require_approval 必须是 bool 或非空 list[非空 str]", err)

    def test_approval_hint_key_unknown(self):
        # approval_hint 独立键已并入 require_approval：残留即未知键
        err = get_task.validate_workflow({
            "workflow": "t", "max_parallel": 1,
            "nodes": [_node("a", require_approval=True, approval_hint=["h"])]})
        self.assertIn("键不符", err)


class InitStatusTest(unittest.TestCase):
    def test_gated_task_flag_persisted(self):
        temp_dir = tempfile.TemporaryDirectory(prefix="wo-appr-")
        self.addCleanup(temp_dir.cleanup)
        work_dir = temp_dir.name
        wf = Path(work_dir) / "workflow.yaml"
        wf.write_text(_workflow_yaml([_node("a", require_approval=True), _node("b")]))
        proc = run_script(INIT_STATUS, "--yaml", str(wf),
                          "--work-dir", work_dir, "--prompt", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = read_status(work_dir)
        self.assertTrue(status["tasks"]["a"]["require_approval"])
        self.assertNotIn("require_approval", status["tasks"]["b"])

    def test_gated_flag_persisted_from_hint_list(self):
        # 确认提示列表同样落门禁标记（提示本体留在 yaml，不进快照）
        temp_dir = tempfile.TemporaryDirectory(prefix="wo-appr-")
        self.addCleanup(temp_dir.cleanup)
        work_dir = temp_dir.name
        wf = Path(work_dir) / "workflow.yaml"
        wf.write_text(_workflow_yaml([_node("a", require_approval=["提示"])]))
        proc = run_script(INIT_STATUS, "--yaml", str(wf),
                          "--work-dir", work_dir, "--prompt", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = read_status(work_dir)
        self.assertTrue(status["tasks"]["a"]["require_approval"])


class SubgraphFlagTest(unittest.TestCase):
    def test_materialized_child_inherits_flag(self):
        # seed 是普通任务（status.json 的 tasks 不能为空），已 pass；sg 无依赖立即物化
        nodes = [_node("seed"),
                 {"id": "sg", "task_type": "subgraph", "file": "sg.yaml", "depends_on": []}]
        tasks = {"seed": {"status": "pass", "retries": 0, "pass_seq": 1}}
        work_dir = make_workdir(self, nodes, tasks)
        sub = {"nodes": [_node("x", require_approval=True), _node("y"),
                         _node("z", require_approval=["提示"])]}
        (Path(work_dir) / "sg.yaml").write_text(yaml.safe_dump(sub, sort_keys=False))
        proc = run_script(GET_TASK, work_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = read_status(work_dir)
        self.assertTrue(status["tasks"]["sg/x"]["require_approval"])
        self.assertNotIn("require_approval", status["tasks"]["sg/y"])
        self.assertTrue(status["tasks"]["sg/z"]["require_approval"])  # list 形态同样落标记


class UpdateStatusTest(unittest.TestCase):
    def test_gated_pass_goes_awaiting(self):
        wd = self._wd({"status": "verifying", "retries": 0, "require_approval": True})
        proc = run_script(UPDATE_STATUS, "t", wd, "pass")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("verifying → awaiting_approval", proc.stdout)
        status = read_status(wd)
        self.assertEqual(status["tasks"]["t"]["status"], "awaiting_approval")
        self.assertNotIn("pass_seq", status["tasks"]["t"])  # 批准后才记 pass_seq
        self.assertEqual(read_log(wd)[-1]["to"], "awaiting_approval")

    def test_ungated_pass_unchanged(self):
        wd = self._wd({"status": "verifying", "retries": 0})
        proc = run_script(UPDATE_STATUS, "t", wd, "pass")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = read_status(wd)
        self.assertEqual(status["tasks"]["t"]["status"], "pass")
        self.assertEqual(status["tasks"]["t"]["pass_seq"], 1)

    def test_awaiting_rejects_agent_reply(self):
        wd = self._wd({"status": "awaiting_approval", "retries": 0,
                       "require_approval": True})
        proc = run_script(UPDATE_STATUS, "t", wd, "pass")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("无迁移规则", proc.stderr)

    def _wd(self, entry):
        temp_dir = tempfile.TemporaryDirectory(prefix="wo-appr-")
        self.addCleanup(temp_dir.cleanup)
        work_dir = temp_dir.name
        wr = Path(work_dir) / ".workflow"
        wr.mkdir()
        (wr / "status.json").write_text(json.dumps({"seq": 0, "tasks": {"t": entry}}))
        return work_dir


class ApproveTaskTest(unittest.TestCase):
    def test_writes_approval_file(self):
        wd = self._wd()
        proc = run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "t",
                          "--decision", "approve")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads((Path(wd) / ".workflow" / "approvals" / "t.json").read_text())
        self.assertEqual(data, {"decision": "approve"})

    def test_redo_requires_comment(self):
        wd = self._wd()
        proc = run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "t",
                          "--decision", "redo")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--comment 不能为空", proc.stderr)

    def test_redo_with_comment(self):
        wd = self._wd()
        proc = run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "t",
                          "--decision", "redo", "--comment", "改用 sqlite")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads((Path(wd) / ".workflow" / "approvals" / "t.json").read_text())
        self.assertEqual(data, {"decision": "redo", "comment": "改用 sqlite"})

    def test_state_mismatch_rejected(self):
        wd = self._wd(status="running")
        proc = run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "t",
                          "--decision", "approve")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("不在待审批状态", proc.stderr)

    def test_unknown_task_rejected(self):
        wd = self._wd()
        proc = run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "nope",
                          "--decision", "approve")
        self.assertEqual(proc.returncode, 2)

    def test_overwrite_before_harvest(self):
        wd = self._wd()
        run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "t", "--decision", "redo",
                   "--comment", "first")
        run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "t", "--decision", "approve")
        data = json.loads((Path(wd) / ".workflow" / "approvals" / "t.json").read_text())
        self.assertEqual(data, {"decision": "approve"})

    def _wd(self, status="awaiting_approval"):
        return make_workdir(self, [_node("t", require_approval=True)],
                            {"t": {"status": status, "retries": 0,
                                   "require_approval": True}})


class HarvestTest(unittest.TestCase):
    GATED_A = {"status": "awaiting_approval", "retries": 0, "require_approval": True}

    def test_awaiting_blocks_dispatch_without_approval(self):
        wd = make_workdir(self, [_node("a", require_approval=True)], {"a": dict(self.GATED_A)})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "[]")  # 等审批：非 STUCK 非 FINISHED

    def test_approve_unlocks_downstream(self):
        wd = make_workdir(
            self,
            [_node("a", require_approval=True), _node("b", depends_on=["a"])],
            {"a": dict(self.GATED_A), "b": {"status": "pending", "retries": 0}})
        path = write_approval(wd, "a", {"decision": "approve"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        batch = json.loads(proc.stdout)
        self.assertEqual([t["task_id"] for t in batch], ["b"])  # a 已 pass，解锁 b
        status = read_status(wd)
        self.assertEqual(status["tasks"]["a"]["status"], "pass")
        self.assertEqual(status["tasks"]["a"]["pass_seq"], 1)
        self.assertFalse(path.exists())  # 收割后删除
        self.assertEqual(read_log(wd)[-1]["event"], "approval")
        self.assertEqual(read_log(wd)[-1]["decision"], "approve")

    def test_redo_back_to_pending_with_feedback(self):
        wd = make_workdir(self, [_node("a", require_approval=True, max_retries=1)],
                          {"a": dict(self.GATED_A, retries=1)})
        write_approval(wd, "a", {"decision": "redo", "comment": "改用 sqlite"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        batch = json.loads(proc.stdout)
        self.assertEqual(batch[0]["task_id"], "a")
        self.assertIn("Human-Feedback", batch[0]["prompt"])
        self.assertIn("改用 sqlite", batch[0]["prompt"])
        status = read_status(wd)
        self.assertEqual(status["tasks"]["a"]["status"], "pending")
        self.assertEqual(status["tasks"]["a"]["retries"], 0)  # 重做不占机器预算

    def test_fail_continue_enters_skip_set(self):
        wd = make_workdir(
            self,
            [_node("a", require_approval=True, on_exhaust="continue"),
             _node("b", depends_on=["a"])],
            {"a": dict(self.GATED_A), "b": {"status": "pending", "retries": 0}})
        write_approval(wd, "a", {"decision": "fail", "comment": "方案不可行"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["result"], "[ALL TASK FINISHED]")
        self.assertEqual(result["skipped"], ["a", "b"])
        entry = read_status(wd)["tasks"]["a"]
        self.assertEqual(entry["status"], "fail")
        self.assertTrue(entry["exhausted"])  # 终裁 = 耗尽预算，不触发机器重试

    def test_fail_exit_stuck(self):
        wd = make_workdir(self, [_node("a", require_approval=True, on_exhaust="exit")],
                          {"a": dict(self.GATED_A)})
        write_approval(wd, "a", {"decision": "fail"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[STUCK]", proc.stdout)

    def test_stale_approval_file_ignored(self):
        wd = make_workdir(self, [_node("a", require_approval=True)],
                          {"a": {"status": "running", "retries": 0,
                                 "require_approval": True}},
                          max_parallel=1)
        path = write_approval(wd, "a", {"decision": "approve"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "[]")  # a 在飞
        self.assertFalse(path.exists())  # 残留文件已删
        self.assertEqual(read_status(wd)["tasks"]["a"]["status"], "running")
        self.assertEqual(read_log(wd)[-1]["event"], "approval_ignored")

    def test_corrupt_approval_file_renamed_bad(self):
        wd = make_workdir(self, [_node("a", require_approval=True)], {"a": dict(self.GATED_A)})
        write_approval(wd, "a", raw="not json{")
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("审批文件损坏", proc.stderr)
        self.assertTrue((Path(wd) / ".workflow" / "approvals" / "a.json.bad").is_file())
        self.assertEqual(proc.stdout.strip(), "[]")  # 仍在等审批

    def test_stuck_exit_takes_priority_over_awaiting(self):
        wd = make_workdir(
            self,
            [_node("a", require_approval=True),
             _node("y", max_retries=0, on_exhaust="exit")],
            {"a": dict(self.GATED_A), "y": {"status": "fail", "retries": 1}})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[STUCK]", proc.stdout)

    def test_non_string_comment_redo_ignored(self):
        # JSON 合法但 comment 类型非法：coerce 后 redo 缺 comment → 忽略（不崩溃、不卡死）
        wd = make_workdir(self, [_node("a", require_approval=True)], {"a": dict(self.GATED_A)})
        path = write_approval(wd, "a", {"decision": "redo", "comment": 42})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "[]")
        self.assertFalse(path.exists())
        self.assertEqual(read_status(wd)["tasks"]["a"]["status"], "awaiting_approval")
        self.assertEqual(read_log(wd)[-1]["event"], "approval_ignored")

    def test_unknown_task_approval_ignored(self):
        wd = make_workdir(self, [_node("a", require_approval=True)], {"a": dict(self.GATED_A)})
        path = write_approval(wd, "ghost", {"decision": "approve"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(path.exists())
        self.assertEqual(read_log(wd)[-1]["event"], "approval_ignored")

    def test_fail_rollback_routes_to_rollback(self):
        # 终裁 fail + on_exhaust=rollback：当轮进入回滚路径（无 checkpoint → STUCK 原因含 rollback）
        wd = make_workdir(
            self,
            [_node("a"),
             _node("b", depends_on=["a"], require_approval=True,
                   on_exhaust="rollback", rollback_to="a")],
            {"a": {"status": "pass", "retries": 0, "pass_seq": 1},
             "b": dict(self.GATED_A)})
        write_approval(wd, "b", {"decision": "fail", "comment": "方向错了"})
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[STUCK]", proc.stdout)
        self.assertIn("rollback", proc.stdout)
        entry = read_status(wd)["tasks"]["b"]
        self.assertEqual(entry["status"], "fail")
        self.assertTrue(entry["exhausted"])

    def test_subgraph_child_approval_roundtrip(self):
        # 子图子任务 sg/x 待审批：approve_task 写入百分号编码文件，get_task 收割后 x pass
        nodes = [_node("seed"),
                 {"id": "sg", "task_type": "subgraph", "file": "sg.yaml", "depends_on": []}]
        tasks = {"seed": {"status": "pass", "retries": 0, "pass_seq": 1},
                 "sg/x": {"status": "awaiting_approval", "retries": 0,
                          "require_approval": True}}
        wd = make_workdir(self, nodes, tasks)
        sub = {"nodes": [_node("x", require_approval=True)]}
        (Path(wd) / "sg.yaml").write_text(yaml.safe_dump(sub, sort_keys=False))
        proc = run_script(APPROVE_TASK, "--work-dir", wd, "--task-id", "sg/x",
                          "--decision", "approve")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((Path(wd) / ".workflow" / "approvals" / "sg%2Fx.json").is_file())
        proc = run_script(GET_TASK, wd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(read_status(wd)["tasks"]["sg/x"]["status"], "pass")


class HarvestRobustnessTest(unittest.TestCase):
    """收割落盘容错：审批文件在收割瞬间被人工删走（os.remove 抛 OSError）不崩溃。"""

    def test_approve_harvest_tolerates_delete_race(self):
        wd = make_workdir(self, [_node("a", require_approval=True)],
                          {"a": {"status": "awaiting_approval", "retries": 0,
                                 "require_approval": True}})
        changed, status = self._harvest_with_remove_gone(wd)
        self.assertTrue(changed)  # 收割照常完成，不因删文件失败回滚状态
        self.assertEqual(status["tasks"]["a"]["status"], "pass")
        self.assertEqual(read_log(wd)[-1]["event"], "approval")

    def test_stale_harvest_tolerates_delete_race(self):
        wd = make_workdir(self, [_node("a", require_approval=True)],
                          {"a": {"status": "running", "retries": 0,
                                 "require_approval": True}})
        changed, status = self._harvest_with_remove_gone(wd)
        self.assertFalse(changed)
        self.assertEqual(status["tasks"]["a"]["status"], "running")
        self.assertEqual(read_log(wd)[-1]["event"], "approval_ignored")

    def _harvest_with_remove_gone(self, wd):
        """写审批文件 a=approve，在 os.remove 被抢删（抛 FileNotFoundError）下收割。"""
        node = _node("a", require_approval=True)
        write_approval(wd, "a", {"decision": "approve"})
        status = read_status(wd)
        with patch("get_task.os.remove", side_effect=FileNotFoundError("被人抢先删除")):
            changed = get_task.harvest_approvals(status, {"a": node}, {})
        return changed, status


def _terminate(proc):
    """无论断言成败都确保子进程被终止、管道被关闭（addCleanup 用）。"""
    if proc.poll() is None:
        proc.kill()
        proc.wait()
    if proc.stdout:
        proc.stdout.close()


class ApprovalE2ETest(unittest.TestCase):
    """dry-run 端到端：gated 任务待审批时编排器保持存活，批准后工作流完成。"""

    def test_orchestrator_survives_awaiting_and_completes_after_approval(self):
        temp_dir = tempfile.TemporaryDirectory(prefix="wo-appr-e2e-")
        self.addCleanup(temp_dir.cleanup)
        work_dir = temp_dir.name
        nodes = [_node("a", require_approval=True), _node("b", depends_on=["a"])]
        wf = Path(work_dir) / "workflow.yaml"
        wf.write_text(_workflow_yaml(nodes, max_parallel=2))
        wr = Path(work_dir) / ".workflow"
        wr.mkdir()
        (wr / "dry_replies.json").write_text(json.dumps(
            {"a": ["executed", "$VERDICT:pass"], "b": ["executed", "$VERDICT:pass"]}))
        proc = subprocess.Popen(
            [sys.executable, str(ORCHESTRATOR), "--yaml", str(wf),
             "--work-dir", work_dir, "--dry-run", "--prompt", "test"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(_terminate, proc)
        # 轮询直到 a 进入待审批（状态落盘后即使编排器退出也可读到）
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if read_status(work_dir)["tasks"]["a"]["status"] == "awaiting_approval":
                    break
            except (OSError, json.JSONDecodeError, KeyError):
                pass  # status.json 尚未初始化或写半截
            time.sleep(0.2)
        else:
            # 先终止子进程再读输出：编排器活着但永远进不了待审批时，
            # 直接 read 会永远阻塞在打开的管道上（addCleanup 也不会执行）
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            self.fail("30s 内 a 未进入 awaiting_approval: %s" % proc.stdout.read())
        # 核心回归断言：待审批期间编排器必须持续存活（旧逻辑连续 3 空轮即 exit 2，
        # 每轮仅一次 get_task 子进程调用、无 sleep，约 0.5s 内自杀）
        deadline = time.time() + 3
        while time.time() < deadline:
            self.assertIsNone(proc.poll(), "a 待审批期间编排器退出（空轮误杀回归）")
            time.sleep(0.2)
        # 批准后编排器收割信箱、a 落 pass 并解锁 b，最终工作流完成
        ap = run_script(APPROVE_TASK, "--work-dir", work_dir, "--task-id", "a",
                        "--decision", "approve")
        self.assertEqual(ap.returncode, 0, ap.stderr)
        rc = proc.wait(timeout=60)
        out = proc.stdout.read()
        self.assertEqual(rc, 0, out)
        tasks = read_status(work_dir)["tasks"]
        self.assertEqual(tasks["a"]["status"], "pass")
        self.assertEqual(tasks["b"]["status"], "pass")
        events = [e.get("event") for e in read_log(work_dir)]
        self.assertIn("approval", events)


if __name__ == "__main__":
    unittest.main()
