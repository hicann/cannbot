# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: CANN-2.0
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from itertools import chain
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_artifacts


class PankoDeliveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.op_dir = Path(temporary.name)
        self.impl = self.op_dir / "demo_impl.py"
        self.impl.write_text("def demo(x): return x\n")
        for name in ("demo_golden.py", "test_demo.py", "SPEC.md"):
            (self.op_dir / name).write_text("test fixture\n")
        state = {
            "stage_status": {str(i): "completed" for i in range(1, 8)},
            "stage7_tuning_mode": "panko",
        }
        (self.op_dir / ".orchestrator_state.json").write_text(json.dumps(state))
        digest = hashlib.sha256(self.impl.read_bytes()).hexdigest()
        self.folder = self.op_dir / "optimization"
        self.folder.mkdir()
        self.search = {
            "op": "demo", "best_node": "root",
            "nodes": {"closed": [{"id": "root", "code_hash": digest, "eval": {"s": 1, "p": 5.0}}]},
            "config": {"eval_budget": 1, "delivery_latency_source": "aicore"},
            "progress": {"_start_ts": 42, "stop_reason": "eval_budget", "evals_used": 1},
        }
        self.terminal = {"directive": "STOP", "run_start": 42, "reason": "eval_budget",
                         "delivered_code_hash": digest}
        self.result_file = self.op_dir / "demo_tune_result.json"
        self.result_file.write_text(json.dumps({"optimized_us": 5.0, "perf_target_us": None, "target_met": True}))
        self.report_file = self.op_dir / "demo_tuning_report.md"
        self.report_file.write_text("baseline and measured winner\n")

    def check_delivery(self):
        for name, payload in (("search_state", self.search), ("controller-terminal", self.terminal)):
            (self.folder / (name + ".json")).write_text(json.dumps(payload))
        return check_artifacts.check("demo", self.op_dir, require_bridge=False, tuning_mode="panko")

    def test_current_natural_stop_matches_delivered_source(self):
        self.assertEqual(self.check_delivery(), [])
        self.impl.write_text("def demo(x): return x + 2\n")
        self.assertTrue(self.check_delivery())

    def test_search_can_pass_before_stage_completion_only_for_its_own_result(self):
        self.check_delivery()
        self.result_file.unlink()
        state = {"stage_status": {"6": "completed", "7": "in_progress"}, "stage7_tuning_mode": "panko"}
        (self.op_dir / ".orchestrator_state.json").write_text(json.dumps(state))
        self.assertEqual(check_artifacts.check_panko_search("demo", self.op_dir, "panko"), [])
        self.assertTrue(check_artifacts.check_panko_search("demo", self.op_dir, "stepwise"))
        self.impl.write_text("different candidate")
        self.assertTrue(check_artifacts.check_panko_search("demo", self.op_dir, "panko"))

    def test_aicore_result_uses_the_winners_measurement(self):
        self.search["nodes"]["closed"][0]["eval"]["p"] = 210.0
        result = {"perf_target_us": 200, "target_met": True, "optimized_us": 180, "metric": "wall_clock"}
        self.result_file.write_text(json.dumps(result))
        self.assertIn("210", " ".join(self.check_delivery()))
        result.update(optimized_us=210, target_met=False)
        self.result_file.write_text(json.dumps(result))
        self.assertEqual(self.check_delivery(), [])
        self.result_file.unlink()
        self.assertTrue(self.check_delivery())

    def test_separate_timer_is_selected_at_init(self):
        self.search["config"]["delivery_latency_source"] = "case_timer"
        self.result_file.write_text(json.dumps({"optimized_us": 13.75}))
        self.assertEqual(self.check_delivery(), [])
        self.result_file.write_text(json.dumps({"optimized_us": True}))
        self.assertTrue(self.check_delivery())
        self.result_file.write_text(json.dumps({"optimized_us": 13.75}))
        self.search["config"]["delivery_latency_source"] = "aicor"
        self.assertTrue(self.check_delivery())

    def test_unregistered_timer_can_be_checked_against_the_original_request(self):
        self.search["config"].pop("delivery_latency_source")
        self.result_file.write_text(json.dumps({"optimized_us": 13.75, "perf_target_us": None, "target_met": True}))
        self.assertIn("--panko-latency-source", " ".join(self.check_delivery()))
        prepared = self.op_dir / "prepared_case.json"
        prepared.write_text(json.dumps({"op": "demo", "op_dir": ".", "tuning_mode": "panko"}))
        command = [sys.executable, check_artifacts.__file__, "--prepared", str(prepared)]
        search_state = (self.folder / "search_state.json").read_bytes()
        search = subprocess.run([*command, "--panko-search"], capture_output=True, text=True, check=False)
        self.assertNotEqual(search.returncode, 0)
        search = subprocess.run([*command, "--panko-search", "--panko-latency-source", "case_timer"],
                                capture_output=True, text=True, check=False)
        self.assertIn("PANKO_SEARCH_OK", search.stdout)
        for source, expected in (("case_timer", 0), ("aicore", 1)):
            result = subprocess.run([*command, "--panko-latency-source", source],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual((self.folder / "search_state.json").read_bytes(), search_state)
        self.search["config"]["delivery_latency_source"] = "aicore"
        self.check_delivery()
        result = subprocess.run([*command, "--panko-latency-source", "case_timer"],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicts", result.stderr)

    def test_search_requires_a_receipt_and_intact_snapshots_for_a_paid_manual_edit(self):
        self.search["config"].update(eval_budget=2, checkpoint_handoffs=True)
        self.search["progress"]["evals_used"] = 2
        before = self.impl.read_bytes()
        base = hashlib.sha256(before).hexdigest()
        after = b"def demo(x): return x + 2\n"
        candidate = hashlib.sha256(after).hexdigest()
        self.search["eval_cache"] = {base: {"s": 1}, candidate: {"s": 1}}
        self.assertTrue(self.check_delivery())
        nodes = self.folder / "nodes"
        nodes.mkdir()
        (nodes / (base + ".py")).write_bytes(before)
        (nodes / (candidate + ".py")).write_bytes(after)
        self.search["code_handoffs"] = [{
            "action_id": "u1", "base_hash": base, "intent": "edit one kernel expression", "coder": True,
            "candidate_hash": candidate, "evaluated_hash": candidate, "through_block": False,
            "summary": "change the expression",
        }]
        self.assertEqual(self.check_delivery(), [])
        (nodes / (candidate + ".py")).write_bytes(before)
        self.assertTrue(self.check_delivery())

    def test_stop_record_must_respect_the_evaluation_budget(self):
        for used, budget in ((2, 1), (1, 2), (1, None)):
            with self.subTest(used=used, budget=budget):
                self.search["config"]["eval_budget"] = budget
                self.search["progress"]["evals_used"] = used
                self.assertTrue(self.check_delivery())

    def test_search_requires_distinct_hashes_for_paid_direct_candidates(self):
        base = self.search["nodes"]["closed"][0]["code_hash"]
        digests = [hashlib.sha256(code).hexdigest() for code in (b"candidate A", b"candidate B")]
        self.search["config"].update(eval_budget=5, checkpoint_handoffs=True)
        self.search["progress"].update(evals_used=5, block_evals=2)
        self.search["eval_cache"] = {digest: {"s": 1} for digest in [base, *digests]}
        direct = [
            {"action_id": f"u{i}", "intent": "vary the tile", "base_hash": base, "coder": False,
             "candidate_hash": digest, "evaluated_hash": digest, "through_block": False}
            for i, digest in enumerate(digests)
        ]
        self.search["blocks"] = [{"device_trials": 2}]
        block_winner = dict(direct[0], through_block=True)
        self.search["code_handoffs"] = [*direct, block_winner]
        self.assertEqual(self.check_delivery(), [])
        self.assertEqual(check_artifacts.check_panko_search("demo", self.op_dir, "panko"), [])

        for already_charged in (digests[0], base):
            with self.subTest(already_charged=already_charged):
                self.search["code_handoffs"][1] = dict(
                    direct[1], candidate_hash=already_charged, evaluated_hash=already_charged,
                )
                self.assertIn("duplicate", " ".join(self.check_delivery()).lower())
                self.assertTrue(check_artifacts.check_panko_search("demo", self.op_dir, "panko"))

    def test_stale_and_forced_stops_are_rejected(self):
        self.terminal["run_start"] = 12
        self.assertTrue(self.check_delivery())
        self.terminal["run_start"] = 42
        self.search["progress"]["forced_stop"] = True
        self.assertTrue(self.check_delivery())

    def test_explicit_request_rejects_a_completed_stepwise_run(self):
        state = {"stage_status": {str(i): "completed" for i in range(1, 8)},
                 "stage7_tuning_mode": "stepwise"}
        (self.op_dir / ".orchestrator_state.json").write_text(json.dumps(state))
        problems = check_artifacts.check("demo", self.op_dir, require_bridge=False, tuning_mode="panko")
        self.assertTrue(any("策略不匹配" in message for message in problems))

    def verify_prepared(self, **fields):
        prepared = self.op_dir / "prepared_case.json"
        prepared.write_text(json.dumps({"op": "demo", "op_dir": ".", "mode": "interactive", **fields}))
        return subprocess.run([sys.executable, check_artifacts.__file__, "--prepared", str(prepared)],
                              capture_output=True, text=True, check=False)

    def test_prepared_mode_uses_the_same_default_as_subgraph_selection(self):
        self.assertEqual(self.check_delivery(), [])
        absent = self.verify_prepared()
        self.assertEqual(absent.returncode, 1, absent.stdout)
        self.assertIn("stepwise", absent.stderr)
        null = self.verify_prepared(tuning_mode=None)
        self.assertEqual(null.returncode, 2, null.stdout)
        self.assertIn("tuning_mode", null.stderr)
        # A direct check has no requested strategy to compare against.
        (self.op_dir / "demo_pypto_impl.py").write_text("def bridge(): pass\n")
        direct = subprocess.run(
            [sys.executable, check_artifacts.__file__, "--op", "demo", "--op-dir", str(self.op_dir)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.set_recorded_mode("stepwise")
        self.assertEqual(self.verify_prepared().returncode, 0)

    def set_recorded_mode(self, mode):
        path = self.op_dir / ".orchestrator_state.json"
        state = json.loads(path.read_text())
        state["stage7_tuning_mode"] = mode
        path.write_text(json.dumps(state))

    def test_prepared_final_result_is_checked_for_both_strategies(self):
        self.assertEqual(self.check_delivery(), [])
        no_target = {"optimized_us": 5, "perf_target_us": None, "target_met": True}
        entry_cases = (
            (5, {**no_target, "perf_target_us": 5}, "measurements", None),
            (1, {**no_target, "perf_target_us": 1}, "measurements", "target_met 与实测结果不一致"),
        )
        missed_target = {"optimized_us": 5, "perf_target_us": 1, "target_met": False}
        hardware_limit = {**missed_target, "hw_limit_reached": True}
        boundary_cases = (
            (1, missed_target, "measurements", "未确认硬件极限"),
            (1, hardware_limit, "measurements", "硬件极限论证"),
            (1, hardware_limit, "本轮未做硬件极限论证。", "硬件极限论证"),
            (1, hardware_limit, "## 硬件极限论证\n\n## 结论\nother notes", "硬件极限论证"),
            (1, hardware_limit, "## 硬件极限论证\nprofiling evidence", None),
            (6, {**no_target, "perf_target_us": 7}, "measurements", "perf_target_us 与 prepared_case.json"),
            (1, {**no_target, "optimized_us": 1, "perf_target_us": True}, "measurements",
             "perf_target_us 与 prepared_case.json"),
            (None, no_target, "measurements", None),
            (None, {**no_target, "target_met": 1}, "measurements", "target_met"),
            (None, no_target, "   ", "调优报告为空"),
            (None, {**no_target, "optimized_us": True}, "measurements", "optimized_us"),
            (None, {**no_target, "optimized_us": float("inf")}, "measurements", "optimized_us"),
        )
        cases = chain(
            (("stepwise", case) for case in entry_cases + boundary_cases),
            (("panko", case) for case in entry_cases),
        )
        for mode, (requested, result, report, error) in cases:
            self.set_recorded_mode(mode)
            with self.subTest(mode=mode, requested=requested, result=result, report=report):
                self.result_file.write_text(json.dumps(result))
                self.report_file.write_text(report)
                actual = self.verify_prepared(tuning_mode=mode, perf_target_us=requested)
                self.assertEqual(actual.returncode, 1 if error else 0, actual.stderr)
                if error:
                    self.assertIn(error, actual.stderr)
