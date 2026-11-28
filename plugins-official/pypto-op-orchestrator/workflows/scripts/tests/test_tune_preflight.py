# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: CANN-2.0
"""An independent tuning job starts from a Stage 6 checkpoint."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


CHECK = Path(__file__).resolve().parents[1] / "check_artifacts.py"


class TunePreflightTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work_dir = Path(temporary.name)
        self.op_dir = self.work_dir / "custom" / "demo"
        self.op_dir.mkdir(parents=True)
        prepared = {"op": "demo", "op_dir": "custom/demo", "mode": "interactive", "tuning_mode": "panko"}
        self.prepared = self.work_dir / "prepared_case.json"
        self.prepared.write_text(json.dumps(prepared))
        self.set_stage7("in_progress")

    def set_stage7(self, status):
        state = {"stage_status": {"6": "completed", "7": status}, "stage7_tuning_mode": "panko"}
        (self.op_dir / ".orchestrator_state.json").write_text(json.dumps(state))

    def preflight(self):
        return subprocess.run(
            [sys.executable, str(CHECK), "--prepared", str(self.prepared), "--tune-preflight"],
            cwd=self.work_dir.parent, capture_output=True, text=True, check=False,
        )

    def test_fresh_checkpoint_can_start(self):
        result = self.preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TUNE_PREFLIGHT_OK", result.stdout)

    def test_interrupted_stage6_can_resume_without_another_rollback(self):
        workflow = yaml.safe_load((CHECK.parents[1] / "pypto-op-tune.yaml").read_text())
        preflight = next(node for node in workflow["nodes"] if node["id"] == "tune-preflight")
        _, _, recovery = "\n".join(preflight["approach"]).partition("in_progress")
        before_completion, completion, _ = recovery.partition("complete_stage")
        self.assertTrue(completion, "An in_progress Stage 6 needs a complete_stage action")
        self.assertIn("test_<op>.py", before_completion)
        self.assertNotIn("rollback_to_stage", before_completion)

        checkpoint = self.op_dir / ".orchestrator_state.json"
        state = {"current_stage": 6, "stage_status": {"6": "in_progress", "7": "pending"}}
        checkpoint.write_text(json.dumps(state))
        result = self.preflight()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Stage 6", result.stderr)
        self.assertEqual(json.loads(checkpoint.read_text()), state)

        checkpoint.write_text(json.dumps({"current_stage": 7, "stage_status": {"6": "completed", "7": "in_progress"}}))
        self.assertEqual(self.preflight().returncode, 0)

    def test_completed_run_of_the_same_mode_cannot_satisfy_a_new_job(self):
        self.set_stage7("completed")
        result = self.preflight()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Stage 6", result.stderr)

    def test_an_external_operator_must_be_copied_to_this_job(self):
        other = self.work_dir / "imported"
        self.op_dir.rename(other)
        prepared = json.loads(self.prepared.read_text())
        prepared["op_dir"] = str(other)
        self.prepared.write_text(json.dumps(prepared))
        result = self.preflight()
        self.assertEqual(result.returncode, 1)
        self.assertIn("custom/", result.stderr)

    def test_inherited_evidence_is_rejected_without_removing_it(self):
        for relative in ("optimization/search_state.json", "optimization/controller-terminal.json",
                         "optimization/baseline.json",
                         "demo_tune_result.json", "demo_tuning_report.md"):
            with self.subTest(relative=relative):
                path = self.op_dir / relative
                path.parent.mkdir(exist_ok=True)
                path.write_text("old result")
                result = self.preflight()
                self.assertEqual(result.returncode, 1)
                self.assertIn(relative, result.stderr)
                self.assertEqual(path.read_text(), "old result")
                path.unlink()
