# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""Exercise exit-code handling using real subprocesses, without an installed CLI."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import Future

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import orchestrator as orch


class StubClaude(orch.ClaudeProvider):
    def __init__(self, output, code=0):
        self.output = output
        self.code = code

    def build_command(self, agent, prompt):
        return [sys.executable, "-c",
                "import sys; sys.stdout.buffer.write(%r); sys.exit(%d)"
                % (self.output, self.code)]


class AgentExitTest(unittest.TestCase):
    def run_and_harvest(self, work_dir, phase, output, code=0, verdict=None):
        wf = Path(work_dir) / ".workflow"
        wf.mkdir(exist_ok=True)
        status = {"seq": 0, "tasks": {"t": {
            "status": "running" if phase == "execute" else "verifying", "retries": 0}}}
        (wf / "status.json").write_text(json.dumps(status))
        if verdict is not None:
            path = Path(orch.verdict_file_path(work_dir, "t"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(verdict)
        entry = {"task_id": "t", "_phase": phase, "agent": "test", "prompt": "test"}
        future = Future()
        try:
            future.set_result(orch.run_agent(entry, StubClaude(output, code), work_dir, None))
        except Exception as exc:
            self.fail("Successful process output must not cause parsing errors: %r" % exc)
        orch.harvest_done(work_dir, {future: entry})
        return json.loads((wf / "status.json").read_text())["tasks"]["t"]

    def test_execute_uses_exit_code_and_preserves_raw_output(self):
        outputs = [b'[{"type":"result","result":"executed"}]',
                   b'{"result": null}', b'{"is_error":true,"result":"fail"}',
                   b'not json', b'', b'\xff', b'$CRASH']
        for output in outputs:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as wd:
                task = self.run_and_harvest(wd, "execute", output)
                self.assertEqual(task["status"], "executed")
                self.assertEqual(task["retries"], 0)
                sessions = list((Path(wd) / ".workflow/sessions").glob("*"))
                self.assertEqual(sessions[0].read_bytes(), output)

    def test_verify_ignores_text_without_valid_verdict(self):
        for verdict in (None, '{', '[]', '{"verdict":"bogus"}'):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as wd:
                task = self.run_and_harvest(wd, "verify", b'{"result":"pass"}', verdict=verdict)
                self.assertEqual(task["status"], "verifying")
                self.assertEqual(task["retries"], 0)

    def test_verify_uses_file_with_array_output(self):
        for verdict in ("pass", "fail"):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as wd:
                task = self.run_and_harvest(wd, "verify", b'[{"result":"pass"}]',
                                            verdict=json.dumps({"verdict": verdict}))
                self.assertEqual(task["status"], verdict)
                self.assertEqual(task["retries"], int(verdict == "fail"))

    def test_nonzero_exit_overrides_success_output_and_verdict(self):
        for phase in ("execute", "verify"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as wd:
                task = self.run_and_harvest(wd, phase, b'{"result":"pass"}', code=7,
                                            verdict='{"verdict":"pass"}')
                self.assertEqual(task["status"], "fail")
                self.assertEqual(task["retries"], 1)
                session = next((Path(wd) / ".workflow/sessions").glob("*"))
                self.assertIn(b'exit=7', session.read_bytes())


if __name__ == "__main__":
    unittest.main()
