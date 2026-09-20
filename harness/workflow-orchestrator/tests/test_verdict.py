# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""verdict_pass.py / verdict_fail.py 黑盒 CLI 测试。

fixture：临时 work_dir + 手工 .workflow/status.json（任务置为指定状态）。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PASS_SCRIPT = SCRIPTS / "verdict_pass.py"
FAIL_SCRIPT = SCRIPTS / "verdict_fail.py"
sys.path.insert(0, str(SCRIPTS))
from verdict_common import verdict_file_path  # noqa: E402


class VerdictScriptTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="verdict-test-")
        self.addCleanup(temporary.cleanup)
        self.work_dir = Path(temporary.name)
        self.wf = self.work_dir / ".workflow"

    def test_pass_writes_verdict_file(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(PASS_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self._verdict_file().read_text())
        self.assertEqual(data, {"verdict": "pass"})

    def test_verdict_file_is_retained_after_write(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(PASS_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._verdict_file().is_file())

    def test_fail_writes_verdict_file_with_reason(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(FAIL_SCRIPT, "--reason", "报告未生成")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self._verdict_file().read_text())
        self.assertEqual(data, {"verdict": "fail", "reason": "报告未生成"})

    def test_fail_requires_reason(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(FAIL_SCRIPT)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self._verdict_file().exists())

    def test_fail_rejects_blank_reason(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(FAIL_SCRIPT, "--reason", "   ")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self._verdict_file().exists())

    def test_reason_truncated_to_500(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(FAIL_SCRIPT, "--reason", "x" * 600)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self._verdict_file().read_text())
        self.assertEqual(len(data["reason"]), 500)

    def test_rejects_wrong_phase(self):
        for st in ("pending", "running", "executed", "pass", "fail"):
            with self.subTest(status=st):
                self._write_status({"t1": {"status": st, "retries": 0}})
                r = self._run(PASS_SCRIPT)
                self.assertEqual(r.returncode, 2)
                self.assertIn(st, r.stderr)
                self.assertFalse(self._verdict_file().exists())

    def test_rejects_unknown_task(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        r = self._run(PASS_SCRIPT, task_id="ghost")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ghost", r.stderr)

    def test_missing_status_json(self):
        r = self._run(PASS_SCRIPT)
        self.assertEqual(r.returncode, 2)
        self.assertIn("status.json", r.stderr)

    def test_subgraph_task_id_escaped(self):
        self._write_status({"sub/child": {"status": "verifying", "retries": 0}})
        r = self._run(PASS_SCRIPT, task_id="sub/child")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._verdict_file("sub/child").is_file())

    def test_verdict_file_paths_are_unique_for_namespaced_and_literal_ids(self):
        """A top-level ``a__b`` task must not collide with subgraph ``a/b``."""
        self._write_status({
            "a__b": {"status": "verifying", "retries": 0},
            "a/b": {"status": "verifying", "retries": 0},
        })
        self.assertNotEqual(
            verdict_file_path(str(self.work_dir), "a__b"),
            verdict_file_path(str(self.work_dir), "a/b"),
        )

    def test_verdict_file_path_is_readable_and_escaped(self):
        self.assertTrue(verdict_file_path(str(self.work_dir), "verify-ops-test-kit")
                        .endswith("/verify-ops-test-kit.json"))
        self.assertTrue(verdict_file_path(str(self.work_dir), "sub/child")
                        .endswith("/sub%2Fchild.json"))
        self.assertTrue(verdict_file_path(str(self.work_dir), "a%b")
                        .endswith("/a%25b.json"))

    def test_last_write_wins(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        self.assertEqual(self._run(FAIL_SCRIPT, "--reason", "r").returncode, 0)
        self.assertEqual(self._run(PASS_SCRIPT).returncode, 0)
        data = json.loads(self._verdict_file().read_text())
        self.assertEqual(data, {"verdict": "pass"})

    def test_unwritable_verdict_file_dir_exits_2(self):
        self._write_status({"t1": {"status": "verifying", "retries": 0}})
        (self.wf / "verdicts").write_text("not a dir")  # 占位为文件 → makedirs 失败
        r = self._run(PASS_SCRIPT)
        self.assertEqual(r.returncode, 2)
        self.assertIn("裁决文件写入失败", r.stderr)

    def _write_status(self, tasks):
        self.wf.mkdir(parents=True, exist_ok=True)
        (self.wf / "status.json").write_text(json.dumps({"tasks": tasks}))

    def _run(self, script, *extra, task_id="t1"):
        return subprocess.run(
            [sys.executable, str(script), "--work-dir", str(self.work_dir),
             "--task-id", task_id, *extra],
            capture_output=True, text=True)

    def _verdict_file(self, task_id="t1"):
        return Path(verdict_file_path(str(self.work_dir), task_id))


if __name__ == "__main__":
    unittest.main()
