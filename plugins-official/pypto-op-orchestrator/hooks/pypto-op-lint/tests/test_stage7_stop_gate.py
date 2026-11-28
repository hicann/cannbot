# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------
"""OL63 checks controller evidence before completing PANKO Stage 7."""

import hashlib
import json
from pathlib import Path

import pytest

from .helpers import build_stateless_op_dir, load_lint_module, run_rule


def _write_search_state(op_dir: Path, stop_reason):
    opt = op_dir / "optimization"
    opt.mkdir(parents=True, exist_ok=True)
    impl_path = op_dir / "demo_impl.py"
    impl_path.write_text("def demo(x): return x\n", encoding="utf-8")
    digest = hashlib.sha256(impl_path.read_bytes()).hexdigest()
    progress = {"_start_ts": 42, "best_latency_us": 583.3, "evals_used": 2}
    if stop_reason is not None:
        progress["stop_reason"] = stop_reason
    (opt / "search_state.json").write_text(
        json.dumps({
            "op": "demo",
            "config": {"eval_budget": 2},
            "progress": progress,
            "best_node": "root",
            "nodes": {"closed": [{"id": "root", "code_hash": digest, "eval": {"s": 1, "p": 583.3}}]},
        }),
        encoding="utf-8",
    )
    return {
        "directive": "STOP",
        "reason": stop_reason,
        "run_start": 42,
        "delivered_code_hash": digest,
    }


def _write_orchestrator_state(op_dir: Path, tuning_mode=None):
    state = {
        "operator_name": op_dir.name,
        "schema_version": "2.0",
        "max_stage": 7,
        "current_stage": 7,
        "stage_status": {str(i): "completed" for i in range(1, 7)},
        "stage_retry_count": {str(i): 0 for i in range(1, 8)},
    }
    state["stage_status"]["7"] = "in_progress"
    if tuning_mode is not None:
        state["stage7_tuning_mode"] = tuning_mode
    (op_dir / ".orchestrator_state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


# ── the stepwise path must stay completable ────────────────────────────────────


def test_ol63_skips_stepwise_stage7(tmp_path: Path):
    """The default path records tuning_mode=stepwise and writes no search_state.

    This is the regression: the gate used to FAIL here, so a perfectly finished
    stepwise Stage 7 could never call complete_stage(7).
    """
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "stepwise")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "SKIP"


def test_ol63_skips_when_mode_unset(tmp_path: Path):
    """An operator from before this field existed is on the stepwise path."""
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, None)
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "SKIP"


def test_ol63_skips_without_orchestrator_state(tmp_path: Path):
    """No state file at all: nothing has declared a PANKO run, so do not assume one."""
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "SKIP"


def test_ol63_fails_when_panko_ran_undeclared(tmp_path: Path):
    """search_state.json exists but the mode was never recorded.

    Only the harness writes that file, so PANKO ran. Skipping here would make
    "forget to record the mode" a way to switch the gate off.
    """
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "stepwise")
    _write_search_state(op_dir, "global_stagnation")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "FAIL"


# ── the PANKO path is gated as before ──────────────────────────────────────────


def test_ol63_fails_when_search_state_absent(tmp_path: Path):
    """PANKO was declared but never ran -> no stop was decided -> block."""
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "FAIL"


def test_ol63_fails_when_stop_reason_missing(tmp_path: Path):
    """search_state exists but the harness never stopped (no stop_reason) -> block."""
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    _write_search_state(op_dir, None)
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "FAIL"


def test_ol63_fails_when_stop_reason_blank(tmp_path: Path):
    """A blank stop_reason counts as not stopped -> block."""
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    _write_search_state(op_dir, "  ")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "FAIL"


def test_ol63_passes_when_harness_stop_recorded(tmp_path: Path):
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    terminal = _write_search_state(op_dir, "global_stagnation")
    (op_dir / "optimization/controller-terminal.json").write_text(json.dumps(terminal), encoding="utf-8")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "PASS"


def test_ol63_checks_registered_aicore_time_before_completion(tmp_path: Path):
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    terminal = _write_search_state(op_dir, "global_stagnation")
    folder = op_dir / "optimization"
    (folder / "controller-terminal.json").write_text(json.dumps(terminal), encoding="utf-8")
    state_path = folder / "search_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["config"]["delivery_latency_source"] = "aicore"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert run_rule(mod, op_dir, "OL63", stage=7).status == "FAIL"
    result = op_dir / "demo_tune_result.json"
    result.write_text(json.dumps({"optimized_us": 400}), encoding="utf-8")
    assert run_rule(mod, op_dir, "OL63", stage=7).status == "FAIL"
    result.write_text(json.dumps({"optimized_us": 583.3}), encoding="utf-8")
    assert run_rule(mod, op_dir, "OL63", stage=7).status == "PASS"


def test_ol63_blocks_stop_without_controller_record(tmp_path: Path):
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    _write_search_state(op_dir, "global_stagnation")
    finding = run_rule(mod, op_dir, "OL63", stage=7)
    assert finding.status == "FAIL"


@pytest.mark.parametrize("problem", ("forced_stop", "stale_run", "edited_impl", "invalid_latency", "fault"))
def test_ol63_blocks_invalid_delivery(tmp_path: Path, problem: str):
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    terminal = _write_search_state(op_dir, "eval_budget")
    state_path = op_dir / "optimization/search_state.json"
    search = json.loads(state_path.read_text(encoding="utf-8"))
    if problem == "forced_stop":
        search["progress"]["forced_stop"] = True
    elif problem == "stale_run":
        terminal["run_start"] = 25
    elif problem == "edited_impl":
        (op_dir / "demo_impl.py").write_text("def demo(x): return -x\n", encoding="utf-8")
    elif problem == "invalid_latency":
        search["nodes"]["closed"][0]["eval"]["p"] = True
    elif problem == "fault":
        search["progress"]["stop_reason"] = terminal["reason"] = "harness_fault"
    state_path.write_text(json.dumps(search), encoding="utf-8")
    (op_dir / "optimization/controller-terminal.json").write_text(json.dumps(terminal), encoding="utf-8")
    assert run_rule(mod, op_dir, "OL63", stage=7).status == "FAIL"


def test_ol63_skips_before_stage7(tmp_path: Path):
    """OL63 is stages=[7]: it must not fire on Stage 1-6 gates."""
    mod = load_lint_module()
    op_dir = build_stateless_op_dir(tmp_path, "demo")
    _write_orchestrator_state(op_dir, "panko")
    finding = run_rule(mod, op_dir, "OL63", stage=6)
    assert finding.status == "SKIP"
