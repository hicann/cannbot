# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: CANN-2.0
"""The two workflow entry points bind exactly one Stage 7 graph per job."""

import json
import subprocess
import sys
import tempfile
import unittest
from itertools import product
from pathlib import Path

import yaml


WORKFLOWS = Path(__file__).resolve().parents[2]
SELECTOR = WORKFLOWS / "scripts" / "select_tuning_workflow.py"


class TuningWorkflowTest(unittest.TestCase):
    @staticmethod
    def install_panko(job):
        skill = job / ".agents/skills/pypto-op-perf-panko-manual"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text("PANKO fixture")
        evaluator = skill / "scripts/evaluate_candidate.py"
        evaluator.touch()
        return evaluator

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.prepared = self.work / "prepared_case.json"
        self.route = self.work / ".workflow" / "pypto-stage7.yaml"

    def select(self, record, *flags):
        self.prepared.write_text(json.dumps(record))
        return subprocess.run([sys.executable, str(SELECTOR), "--prepared", str(self.prepared), *flags],
                              cwd=self.work, text=True, capture_output=True, check=False)

    def test_original_job_defaults_to_stepwise(self):
        self.assertNotEqual(self.select({}, "--check").returncode, 0)
        self.assertEqual(self.select({}).returncode, 0)
        self.assertEqual(self.route.resolve(), WORKFLOWS / "pypto-op-tune-stepwise.yaml")

    def test_resume_keeps_selection_and_rejects_switch(self):
        self.install_panko(self.work)
        self.assertEqual(self.select({"tuning_mode": "panko"}).returncode, 0)
        before = self.route.lstat()
        for flags in ([], ["--check"]):
            r = self.select({"tuning_mode": "panko"}, *flags)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.route.lstat().st_ino, before.st_ino)
        self.assertNotEqual(self.select({"tuning_mode": "stepwise"}).returncode, 0)
        self.assertEqual(self.route.resolve(), WORKFLOWS / "pypto-op-tune-panko.yaml")

    def test_unknown_mode_and_foreign_route_are_rejected(self):
        self.assertNotEqual(self.select({"tuning_mode": "other"}).returncode, 0)
        self.assertFalse(self.route.exists())
        self.assertNotEqual(self.select({"tuning_mode": None}).returncode, 0)
        self.route.parent.mkdir()
        self.route.write_text("different job")
        self.assertNotEqual(self.select({}).returncode, 0)
        self.assertEqual(self.route.read_text(), "different job")

    def test_only_panko_requires_the_candidate_evaluator(self):
        evaluator = self.install_panko(self.work)
        evaluator.unlink()
        result = self.select({"tuning_mode": "panko"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evaluate_candidate.py", result.stderr)
        self.assertFalse(self.route.is_symlink())
        self.assertEqual(self.select({"tuning_mode": "stepwise"}).returncode, 0)

    def test_both_entries_dispatch_only_the_selected_subgraph(self):
        harness = WORKFLOWS.parents[2] / "harness/workflow-orchestrator/scripts/orchestrator.py"
        entries = (("develop", "stage6-e2e"), ("tune", "tune-preflight"))
        strategies = (("stepwise", {"stepwise"}), ("panko", {"search", "deliver"}))
        for (entry, dependency), (mode, children) in product(entries, strategies):
            with self.subTest(entry=entry, mode=mode), tempfile.TemporaryDirectory() as tmp:
                job = Path(tmp)
                if mode == "panko":
                    self.install_panko(job)
                prepared = job / "prepared_case.json"
                prepared.write_text(json.dumps({"tuning_mode": mode}))
                subprocess.run([sys.executable, SELECTOR, "--prepared", prepared], check=True, capture_output=True)
                workflow = WORKFLOWS / f"pypto-op-{entry}.yaml"
                nodes = yaml.safe_load(workflow.read_text())["nodes"]
                self.assertEqual(nodes[-1]["depends_on"], [dependency])
                subprocess.run([sys.executable, harness, "--yaml", workflow, "--work-dir", job,
                                "--prompt", mode, "--dry-run"], check=True, capture_output=True, timeout=60)
                tasks = json.loads((job / ".workflow/status.json").read_text())["tasks"]
                self.assertTrue(all(v["status"] == "pass" for v in tasks.values()))
                actual = {k.split("/", 1)[1] for k in tasks if k.startswith("stage7-tune/")}
                self.assertEqual(actual, children)
