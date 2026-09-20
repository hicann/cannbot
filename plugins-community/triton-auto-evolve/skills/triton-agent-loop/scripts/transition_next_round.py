#!/usr/bin/env python3
# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------
"""Transition to Next Round Script

Atomically executes Step 4 (prepare next round) and Phase 0 (directory creation)
of the Agent Loop, ensuring reliable round-to-round transitions.

All rounds are created as normal directories named opt-round-{N+1}. Direction
switch metadata is recorded in round_index.json and opt-note.md, but no special
"-switch" directory is created.

Usage:
    python3 transition_next_round.py \
        --op-dir triton_ascend_output/{op_name} \
        --current-round {N} \
        --next-round-strategy {exploration|structural_change|focused_tuning|stabilization|plateau_review} \
        --next-analysis-policy {pattern_entry|bottleneck_analysis|ir_supported} \
        --next-hypothesis "..." \
        --next-direction "..." \
        --next-evidence-sources '[...]' \
        [--baseline-dir opt-round-K] \
        [--baseline-dirs '["opt-round-K", "opt-round-L"]'] \
        [--switch-marker '{"reason": "...", "previous_direction": "...", "new_direction": "..."}']

Output (JSON):
    {
        "status": "success" | "fail",
        "next_round": <int>,
        "next_round_dir": "opt-round-<N>",
        "baseline_speedup": <float>,
        "issues": [...],
        "warnings": [...]
    }
"""

from __future__ import annotations

import argparse
import json
import shutil
import string
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config_loader import read_config, get_algorithm_params, get_enabled_algorithms
from direction_selector import DirectionYieldContext, build_direction_history
from strategies import discover_strategies, load_strategy_for_algorithm
from strategies.base import SwitchMarker
from workspace_utils import find_op_name


def _format_state_template(template: str, op_name: str) -> str | None:
    """Safely format a state file template.

    Only the ``{op_name}`` placeholder is allowed. Returns ``None`` for
    malformed templates instead of raising.
    """
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError:
        return None
    fields = {field_name for _, field_name, _, _ in parsed if field_name is not None}
    if fields - {"op_name"}:
        return None
    try:
        return template.format(op_name=op_name)
    except (KeyError, IndexError):
        return None


def _copy_algorithm_state_files(
    source_dir: Path,
    target_dir: Path,
    op_name: str,
    strategy: Any,
) -> list[str]:
    """Copy algorithm-specific state files from source round to next round.

    State file templates are declared by the Strategy class via
    ``state_file_templates``. Each template may contain the ``{op_name}``
    placeholder.

    Returns a list of copied relative paths.
    """
    copied: list[str] = []
    templates = getattr(strategy, "state_file_templates", [])
    for template in templates:
        rel_path = _format_state_template(template, op_name)
        if rel_path is None:
            continue
        src = source_dir / rel_path
        if not src.is_file():
            continue
        dst = target_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel_path)
    return copied


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def _find_state_dir(op_dir: Path) -> Path | None:
    """查找 .triton-agent/ 目录（从 op_dir 向上搜索）。"""
    for p in [op_dir] + list(op_dir.parents):
        candidate = p / ".triton-agent"
        if candidate.is_dir():
            return candidate
    return None


def _state_path_for_op_dir(op_dir: Path, state_dir_loc: Path | None, op_name: str | None = None) -> Path | None:
    """Return the state file path for the given operator workspace.

    New-format workspaces use ``state-{op_dir.name}.json`` so that different
    algorithms/runs are isolated.  If that file does not exist but a legacy
    ``state-{op_name}.json`` exists, fall back to the legacy path for backward
    compatibility.
    """
    if state_dir_loc is None:
        return None
    new_path = state_dir_loc / f"state-{op_dir.name}.json"
    if new_path.is_file():
        return new_path
    if op_name:
        legacy_path = state_dir_loc / f"state-{op_name}.json"
        if legacy_path.is_file():
            return legacy_path
    return new_path


def _load_round_index(op_dir: Path) -> list[dict[str, Any]]:
    round_index_path = op_dir / "round_index.json"
    if not round_index_path.is_file():
        return []
    try:
        data = load_json(round_index_path)
        if isinstance(data, list):
            return data
    except ValueError:
        pass
    return []


def _entry_for_round_index(round_index: list[dict[str, Any]], round_index_num: int) -> dict[str, Any] | None:
    for entry in round_index:
        if entry.get("round_index") == round_index_num:
            return entry
    return None


def _phase3_ok(current_dir: Path) -> bool:
    """Return True when Phase 3 disk verification passed all cases."""
    phase3_verify_paths = sorted(current_dir.glob("output/iter_*/verify/verify_result.json"))
    if not phase3_verify_paths:
        return False
    try:
        vdata = load_json(phase3_verify_paths[-1])
    except ValueError:
        return False
    total = vdata.get("total_cases", 0)
    passed = vdata.get("passed_cases", 0)
    if not (isinstance(total, (int, float)) and isinstance(passed, (int, float))):
        return False
    return int(total) > 0 and int(passed) == int(total)


def _check_phase4(current_dir: Path, issues: list[str]) -> None:
    """Validate Phase 4 artifacts: real code change and attempts.md authenticity."""
    opt_iter_dirs = sorted(current_dir.glob("output/opt_iter_*"))
    phase4_ok = len(opt_iter_dirs) > 0

    has_real_change = False
    generated_code = current_dir / "output" / "generated_code.py"
    if phase4_ok and generated_code.is_file():
        for od in opt_iter_dirs:
            opt_code = od / "optimized_code.py"
            if opt_code.is_file() and opt_code.read_bytes() != generated_code.read_bytes():
                has_real_change = True
                break
        if not has_real_change:
            issues.append(
                "None of the opt_iter_*/optimized_code.py files differ from "
                "output/generated_code.py. All optimization iterations produced "
                "byte-identical code — no actual optimization was performed."
            )

    attempts_path = current_dir / "output" / "attempts.md"
    if phase4_ok and not attempts_path.is_file():
        issues.append("phase4_entered but output/attempts.md not found")
    elif attempts_path.is_file():
        lines = attempts_path.read_text().splitlines()
        tried_count = sum(
            1 for line in lines
            if line.strip().startswith("- [") and ("已尝试" in line or "已命中" in line)
        )
        if tried_count < 1 and phase4_ok:
            issues.append(
                "output/attempts.md has no '已尝试' or '已命中' records. "
                "At least 1 optimization point must be actually attempted."
            )


def _validate_current_round(current_dir: Path) -> tuple[list[str], dict[str, Any]]:
    """Validate current round and return (issues, current_summary)."""
    issues: list[str] = []
    current_summary: dict[str, Any] = {}

    if not current_dir.is_dir():
        issues.append(f"current round directory not found: {current_dir}")
        return issues, current_summary

    current_summary_path = current_dir / "summary.json"
    if current_summary_path.is_file():
        try:
            current_summary = load_json(current_summary_path)
        except ValueError:
            pass

    if not _phase3_ok(current_dir):
        issues.append(
            "Phase 3 verification not found on disk (output/iter_*/verify/verify_result.json)"
        )

    _check_phase4(current_dir, issues)

    return issues, current_summary


@dataclass
class DirectionMetadataRequest:
    """Inputs for computing a completed round's direction metadata."""

    current_summary: dict[str, Any]
    baseline_entry: dict[str, Any] | None
    strategy: Any
    plateau_detected: bool = False
    timeout: bool = False
    idle: bool = False
    context: dict[str, Any] | None = None
    global_baseline_speedup: float = 0.0


def _compute_direction_metadata(req: DirectionMetadataRequest) -> dict[str, Any]:
    """Compute direction_yield, yield_reason, and absolute_gain."""
    current_summary = req.current_summary
    best_speedup = current_summary.get("best_speedup", 0.0)
    if not isinstance(best_speedup, (int, float)):
        best_speedup = 0.0

    baseline_speedup = 0.0
    if req.baseline_entry:
        bs = req.baseline_entry.get("best_speedup", 0.0)
        if isinstance(bs, (int, float)):
            baseline_speedup = bs

    target_speedup = current_summary.get("target_speedup", 5.0)
    if not isinstance(target_speedup, (int, float)):
        target_speedup = 5.0

    perf_data = current_summary.get("perf_data") or {}
    total = perf_data.get("total_cases", 0)
    passed = perf_data.get("passed_cases", 0)
    verify_passed = (
        isinstance(total, (int, float))
        and isinstance(passed, (int, float))
        and int(total) > 0
        and int(passed) == int(total)
    )

    improvement_made = bool(current_summary.get("optimized", False))

    yield_label, yield_reason, absolute_gain = req.strategy.classify_direction_yield(
        DirectionYieldContext(
            best_speedup=best_speedup,
            baseline_speedup=baseline_speedup,
            target_speedup=target_speedup,
            verify_passed=verify_passed,
            improvement_made=improvement_made,
            plateau_detected=req.plateau_detected,
            timeout=req.timeout,
            idle=req.idle,
            context=req.context,
            global_baseline_speedup=req.global_baseline_speedup,
        )
    )

    absolute_gain_global = (
        best_speedup - req.global_baseline_speedup
        if req.global_baseline_speedup > 0
        else 0.0
    )

    return {
        "direction_yield": yield_label,
        "yield_reason": yield_reason,
        "absolute_gain_vs_baseline": round(absolute_gain, 6),
        "absolute_gain_vs_global_baseline": round(absolute_gain_global, 6),
    }


def _select_baseline_path(
    op_dir: Path,
    op_name: str,
    baseline_dir_name: str | None,
    baseline_dir_names: list[str],
) -> tuple[Path | None, dict[str, Any] | None, float]:
    """Select the baseline code path and matching round_index entry."""
    round_index = _load_round_index(op_dir)

    # Prefer explicit single baseline.
    if baseline_dir_name:
        candidate = op_dir / baseline_dir_name / f"{op_name}_generated.py"
        if candidate.is_file():
            entry = _entry_for_baseline(round_index, baseline_dir_name)
            speedup = float(entry.get("best_speedup", 0.0)) if entry else 0.0
            return candidate, entry, speedup
        return None, None, 0.0

    # If multiple baselines are given, pick the first valid one.
    for name in baseline_dir_names:
        if not name:
            continue
        candidate = op_dir / name / f"{op_name}_generated.py"
        if candidate.is_file():
            entry = _entry_for_baseline(round_index, name)
            speedup = float(entry.get("best_speedup", 0.0)) if entry else 0.0
            return candidate, entry, speedup

    return None, None, 0.0


def _entry_for_baseline(round_index: list[dict[str, Any]], round_dir: str) -> dict[str, Any] | None:
    for entry in round_index:
        if entry.get("round_dir") == round_dir:
            return entry
    return None


def _read_baseline_speedup(baseline_info_path: Path) -> float | None:
    """Read baseline_speedup from baseline_info.json; None if absent/invalid."""
    if not baseline_info_path.is_file():
        return None
    try:
        baseline_info = load_json(baseline_info_path)
        gbs = baseline_info.get("baseline_speedup", 0.0)
    except ValueError:
        return None
    if isinstance(gbs, (int, float)) and gbs > 0:
        return float(gbs)
    return None


def _resolve_global_baseline(
    op_dir: Path,
    global_baseline_dir: str | None,
    global_baseline_speedup: float,
) -> tuple[str | None, float]:
    """Resolve global baseline speedup from baseline_info.json when absent."""
    if global_baseline_dir:
        gbs = _read_baseline_speedup(op_dir / global_baseline_dir / "baseline_info.json")
        if gbs is not None:
            global_baseline_speedup = gbs
        return global_baseline_dir, global_baseline_speedup

    gbs = _read_baseline_speedup(op_dir / "global_baseline" / "baseline_info.json")
    if gbs is not None:
        global_baseline_speedup = gbs
        global_baseline_dir = "global_baseline"
    return global_baseline_dir, global_baseline_speedup


@dataclass
class _BaselineSelection:
    """Inputs for selecting and copying the next round's baseline."""

    op_dir: Path
    op_name: str | None
    baseline_dir: str | None
    baseline_dirs: list[str]
    next_round_dir: Path
    strategy: Any
    algorithm: str
    warnings: list[str]


def _select_and_copy_baseline(d: _BaselineSelection) -> tuple[dict[str, Any] | None, float]:
    """Select a baseline, copy its code, and return (baseline_entry, speedup)."""
    op_dir = d.op_dir
    op_name = d.op_name
    baseline_dir = d.baseline_dir
    baseline_dirs = d.baseline_dirs
    next_round_dir = d.next_round_dir
    strategy = d.strategy
    algorithm = d.algorithm
    warnings = d.warnings
    baseline_path: Path | None = None
    baseline_entry: dict[str, Any] | None = None
    baseline_speedup = 0.0

    if baseline_dir or baseline_dirs:
        baseline_path, baseline_entry, baseline_speedup = _select_baseline_path(
            op_dir, op_name or "", baseline_dir, baseline_dirs
        )
        if baseline_path is None:
            warnings.append("specified baseline not found; next round starts without baseline code")
        else:
            warnings.append(
                f"baseline copied from {baseline_entry.get('round_dir') if baseline_entry else 'unknown'} "
                f"(speedup={baseline_speedup:.4f})"
            )
    else:
        warnings.append("no baseline specified, next round starts without baseline code")

    if baseline_path and baseline_path.is_file() and op_name:
        shutil.copy2(baseline_path, next_round_dir / f"{op_name}_generated.py")
        # Copy algorithm-specific state files if the baseline is a previous round.
        if baseline_entry and baseline_entry.get("round_dir"):
            source_round_dir_path = op_dir / baseline_entry["round_dir"]
            copied_state = _copy_algorithm_state_files(
                source_round_dir_path, next_round_dir, op_name, strategy
            )
            if copied_state:
                warnings.append(f"copied algorithm state files for {algorithm}: {copied_state}")
    elif op_name:
        # Ensure a generated code file exists even if starting from scratch.
        target_path = next_round_dir / f"{op_name}_generated.py"
        if not target_path.is_file():
            target_path.write_text("# placeholder\n", encoding="utf-8")

    return baseline_entry, baseline_speedup


@dataclass
class _NextSummary:
    """Inputs for building the next round's summary.json payload."""

    next_round_index: int
    algorithm: str
    baseline_entry: dict[str, Any] | None
    global_baseline_dir: str | None
    global_baseline_speedup: float
    next_round_strategy: str
    next_analysis_policy: str
    next_hypothesis: str
    next_direction: str
    next_evidence_sources: list[str]
    current_summary: dict[str, Any]
    algorithm_metadata: dict[str, Any] | None


def _build_next_summary(d: _NextSummary) -> dict[str, Any]:
    """Build the next round's summary.json payload."""
    next_round_index = d.next_round_index
    algorithm = d.algorithm
    baseline_entry = d.baseline_entry
    global_baseline_dir = d.global_baseline_dir
    global_baseline_speedup = d.global_baseline_speedup
    next_round_strategy = d.next_round_strategy
    next_analysis_policy = d.next_analysis_policy
    next_hypothesis = d.next_hypothesis
    next_direction = d.next_direction
    next_evidence_sources = d.next_evidence_sources
    current_summary = d.current_summary
    algorithm_metadata = d.algorithm_metadata
    next_summary = {
        "round_index": next_round_index,
        "algorithm": algorithm,
        "baseline_dir": baseline_entry.get("round_dir") if baseline_entry else None,
        "global_baseline_dir": global_baseline_dir,
        "global_baseline_speedup": global_baseline_speedup,
        "round_strategy": next_round_strategy,
        "analysis_policy": next_analysis_policy,
        "hypothesis": next_hypothesis,
        "direction": next_direction,
        "evidence_sources": next_evidence_sources,
        "status": "active",
        "best_speedup": 0.0,
        "success": False,
        "gen_iterations": 0,
        "opt_iterations": 0,
        "optimized": False,
        "target_reached": False,
        "target_speedup": current_summary.get("target_speedup", 5.0),
        "direction_yield": None,
        "yield_reason": None,
        "absolute_gain_vs_baseline": None,
        "absolute_gain_vs_global_baseline": None,
    }
    if algorithm_metadata:
        for key in ("mcts_parent_id", "mcts_selection_path", "mcts_pending_expansion"):
            if key in algorithm_metadata:
                next_summary[key] = algorithm_metadata[key]
    return next_summary


@dataclass
class _StateUpdate:
    """Inputs for advancing the .triton-agent/ state file."""

    op_dir: Path
    current_round: int
    next_round_index: int
    next_round_dir_name: str
    next_round_dir: Path
    algorithm: str
    existing_rounds: list[dict[str, Any]]
    warnings: list[str]


def _update_state_file(d: _StateUpdate) -> None:
    """Advance the .triton-agent/ state file to the next round."""
    op_dir = d.op_dir
    current_round = d.current_round
    next_round_index = d.next_round_index
    next_round_dir_name = d.next_round_dir_name
    next_round_dir = d.next_round_dir
    algorithm = d.algorithm
    existing_rounds = d.existing_rounds
    warnings = d.warnings
    state_dir_loc = _find_state_dir(op_dir)
    if state_dir_loc is None:
        warnings.append(".triton-agent/ not found, state file will not be updated")
    op_name = find_op_name(op_dir) or (op_dir.name if op_dir.name else None)
    state_path = _state_path_for_op_dir(op_dir, state_dir_loc, op_name)
    if not (state_path and state_path.is_file()):
        return

    try:
        state = load_json(state_path)
        if str(current_round) in state.get("rounds", {}):
            state["rounds"][str(current_round)]["status"] = "completed"
        rounds = state.setdefault("rounds", {})
        rounds[str(next_round_index)] = {
            "status": "active",
            "round_dir": next_round_dir_name,
        }
        state["current_round"] = next_round_index
        state["algorithm"] = algorithm
        state["algorithm_reference"] = f".claude/references/algorithms/{algorithm}/round.md"
        state["status"] = "active"
        state["phase"] = "round_active"
        state["work_dir"] = str(next_round_dir)
        state["last_phase"] = 0
        # Maintain direction_history for fast recovery.
        state["direction_history"] = build_direction_history(existing_rounds)
        state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except ValueError as exc:
        warnings.append(f"state file update failed: {exc}")


@dataclass
class _RoundIndexUpdate:
    """Inputs for finalizing the current entry and appending the next entry."""

    op_dir: Path
    existing_rounds: list[dict[str, Any]]
    current_round: int
    source_round_dir: str
    current_summary: dict[str, Any]
    direction_metadata: dict[str, Any]
    next_round_index: int
    next_round_dir_name: str
    next_round_strategy: str
    next_analysis_policy: str
    next_hypothesis: str
    next_direction: str
    next_evidence_sources: list[str]
    algorithm: str
    baseline_entry: dict[str, Any] | None
    switch_marker: SwitchMarker | None
    global_baseline_dir: str | None
    global_baseline_speedup: float


def _build_current_entry(d: _RoundIndexUpdate) -> dict[str, Any]:
    """Finalize and return the current round entry, creating it if absent."""
    current_entry = _entry_for_round_index(d.existing_rounds, d.current_round)
    if current_entry is None:
        current_entry = {
            "round_index": d.current_round,
            "round_dir": d.source_round_dir,
            "direction": d.current_summary.get("direction", ""),
            "hypothesis": d.current_summary.get("hypothesis", ""),
            "evidence_sources": d.current_summary.get("evidence_sources", []),
            "analysis_policy": d.current_summary.get("analysis_policy", "pattern_entry"),
            "effective_metric_source": d.current_summary.get("effective_metric_source", "kernel"),
            "status": "success" if d.current_summary.get("success", False) else "failed",
            "best_speedup": d.current_summary.get("best_speedup", 0.0),
            "round_strategy": d.current_summary.get("round_strategy", "exploration"),
            "consecutive_low_gain_count": d.current_summary.get("consecutive_low_gain_count", 0),
            "round_type": d.current_summary.get("round_type", "active"),
            "target_speedup": d.current_summary.get("target_speedup", 5.0),
            "global_baseline_dir": d.current_summary.get("global_baseline_dir") or d.global_baseline_dir,
            "global_baseline_speedup": d.current_summary.get("global_baseline_speedup") or d.global_baseline_speedup,
        }
        d.existing_rounds.append(current_entry)

    current_entry.update(d.direction_metadata)
    current_entry["status"] = "success" if d.current_summary.get("success", False) else "failed"

    if "baseline_dir" not in current_entry:
        current_entry["baseline_dir"] = d.current_summary.get("baseline_dir")
    if "global_baseline_dir" not in current_entry or not current_entry["global_baseline_dir"]:
        current_entry["global_baseline_dir"] = d.global_baseline_dir
    if "global_baseline_speedup" not in current_entry or not current_entry["global_baseline_speedup"]:
        current_entry["global_baseline_speedup"] = d.global_baseline_speedup
    current_entry.pop("parent_round_dir", None)
    current_entry.pop("best_baseline_for_this_direction", None)
    return current_entry


def _build_next_entry(d: _RoundIndexUpdate) -> dict[str, Any]:
    """Build the next round entry, embedding the switch marker if present."""
    next_entry: dict[str, Any] = {
        "round_index": d.next_round_index,
        "round_dir": d.next_round_dir_name,
        "algorithm": d.algorithm,
        "direction": d.next_direction,
        "hypothesis": d.next_hypothesis,
        "evidence_sources": d.next_evidence_sources,
        "analysis_policy": d.next_analysis_policy,
        "effective_metric_source": "kernel",
        "status": "active",
        "best_speedup": 0.0,
        "round_strategy": d.next_round_strategy,
        "consecutive_low_gain_count": 0,
        "round_type": "active",
        "target_speedup": d.current_summary.get("target_speedup", 5.0),
        "direction_yield": None,
        "yield_reason": None,
        "absolute_gain_vs_baseline": None,
        "absolute_gain_vs_global_baseline": None,
        "baseline_dir": d.baseline_entry.get("round_dir") if d.baseline_entry else None,
        "global_baseline_dir": d.global_baseline_dir,
        "global_baseline_speedup": d.global_baseline_speedup,
    }
    if d.switch_marker is not None:
        next_entry["switch_reason"] = d.switch_marker.reason
        next_entry["previous_direction"] = d.switch_marker.previous_direction
        next_entry["new_direction"] = d.switch_marker.new_direction
    return next_entry


def _update_round_index(d: _RoundIndexUpdate) -> None:
    """Finalize the current round entry and append the next round entry."""
    _build_current_entry(d)
    d.existing_rounds.append(_build_next_entry(d))
    (d.op_dir / "round_index.json").write_text(
        json.dumps(d.existing_rounds, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@dataclass
class _OptNote:
    """Inputs for appending the completed round's audit entry to opt-note.md."""

    op_dir: Path
    current_round: int
    current_summary: dict[str, Any]
    current_success_criteria: str
    current_key_learnings: str
    direction_metadata: dict[str, Any]
    switch_marker: SwitchMarker | None


def _append_opt_note(d: _OptNote) -> None:
    """Append the completed round's audit entry to opt-note.md."""
    op_dir = d.op_dir
    current_round = d.current_round
    current_summary = d.current_summary
    current_success_criteria = d.current_success_criteria
    current_key_learnings = d.current_key_learnings
    direction_metadata = d.direction_metadata
    switch_marker = d.switch_marker
    opt_entry = (
        f"\n## Round {current_round}\n\n"
        f"- round_strategy: {current_summary.get('round_strategy', 'N/A')}\n"
        f"- hypothesis: {current_summary.get('hypothesis', 'N/A')}\n"
        f"- direction: {current_summary.get('direction', 'N/A')}\n"
        f"- success_criteria: {current_success_criteria}\n"
        f"- evidence_sources: {json.dumps(current_summary.get('evidence_sources', []), ensure_ascii=False)}\n"
        f"- result: {'success' if current_summary.get('success', False) else 'failed'}\n"
        f"- best_speedup: {current_summary.get('best_speedup', 0)}\n"
        f"- direction_yield: {direction_metadata.get('direction_yield')}\n"
        f"- yield_reason: {direction_metadata.get('yield_reason')}\n"
        f"- absolute_gain_vs_baseline: {direction_metadata.get('absolute_gain_vs_baseline')}\n"
        f"- absolute_gain_vs_global_baseline: {direction_metadata.get('absolute_gain_vs_global_baseline')}\n"
    )
    if switch_marker is not None:
        opt_entry += (
            f"- switch_reason: {switch_marker.reason}\n"
            f"- previous_direction: {switch_marker.previous_direction}\n"
            f"- new_direction: {switch_marker.new_direction}\n"
        )
    opt_entry += f"- key_learnings: {current_key_learnings}\n"

    with open(op_dir / "opt-note.md", "a", encoding="utf-8") as f:
        f.write(opt_entry)


def _write_transition_lock(
    op_dir: Path,
    current_round: int,
    next_round_index: int,
    next_round_dir_name: str,
    warnings: list[str],
) -> None:
    """Write the transition lock that releases the Phase 7 gate."""
    lock = {
        "action": "continue",
        "transition_at": datetime.now(timezone.utc).isoformat(),
        "from_round": current_round,
        "to_round": next_round_index,
        "to_round_dir": next_round_dir_name,
        "state_after": {
            "current_round": next_round_index,
            "last_phase": 0,
            "status": "active",
            "phase": "round_active",
        },
    }
    try:
        (op_dir / ".transition_lock.json").write_text(
            json.dumps(lock, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        warnings.append(f"failed to write transition lock: {exc}")


@dataclass
class _MetadataAndSummary:
    """Inputs for computing direction metadata and writing the next summary.json."""

    op_dir: Path
    source_round_dir: str
    current_summary: dict[str, Any]
    baseline_entry: dict[str, Any] | None
    strategy: Any
    switch_marker: SwitchMarker | None
    global_baseline_speedup: float
    next_round_index: int
    algorithm: str
    global_baseline_dir: str | None
    next_round_strategy: str
    next_analysis_policy: str
    next_hypothesis: str
    next_direction: str
    next_evidence_sources: list[str]
    algorithm_metadata: dict[str, Any] | None
    next_round_dir: Path


def _compute_metadata_and_write_summary(d: _MetadataAndSummary) -> dict[str, Any]:
    """Compute the completed round's metadata and write the next summary.json."""
    current_round_dir = d.op_dir / d.source_round_dir
    plateau_detected = (
        d.switch_marker is not None and d.switch_marker.reason == "plateau_stagnation"
    )
    direction_metadata = _compute_direction_metadata(
        DirectionMetadataRequest(
            current_summary=d.current_summary,
            baseline_entry=d.baseline_entry,
            strategy=d.strategy,
            plateau_detected=plateau_detected,
            timeout=d.current_summary.get("status") == "timeout",
            idle=(d.current_summary.get("round_type") == "idle"),
            context={"op_dir": str(d.op_dir), "round_dir": str(current_round_dir)},
            global_baseline_speedup=d.global_baseline_speedup,
        )
    )
    next_summary = _build_next_summary(
        _NextSummary(
            next_round_index=d.next_round_index,
            algorithm=d.algorithm,
            baseline_entry=d.baseline_entry,
            global_baseline_dir=d.global_baseline_dir,
            global_baseline_speedup=d.global_baseline_speedup,
            next_round_strategy=d.next_round_strategy,
            next_analysis_policy=d.next_analysis_policy,
            next_hypothesis=d.next_hypothesis,
            next_direction=d.next_direction,
            next_evidence_sources=d.next_evidence_sources,
            current_summary=d.current_summary,
            algorithm_metadata=d.algorithm_metadata,
        )
    )
    (d.next_round_dir / "summary.json").write_text(
        json.dumps(next_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return direction_metadata


@dataclass
class _TransitionComputed:
    """Computed state shared by the transition write-phase helpers."""

    op_dir: Path
    current_round: int
    next_round_index: int
    next_round_dir_name: str
    next_round_dir: Path
    source_round_dir: str
    existing_rounds: list[dict[str, Any]]
    current_summary: dict[str, Any]
    direction_metadata: dict[str, Any]
    baseline_entry: dict[str, Any] | None
    global_baseline_dir: str | None
    global_baseline_speedup: float
    warnings: list[str]


def _write_transition_artifacts(req: TransitionRequest, c: _TransitionComputed) -> None:
    """Persist state / round_index / opt-note / lock for the transition."""
    _update_state_file(
        _StateUpdate(
            op_dir=c.op_dir,
            current_round=c.current_round,
            next_round_index=c.next_round_index,
            next_round_dir_name=c.next_round_dir_name,
            next_round_dir=c.next_round_dir,
            algorithm=req.algorithm,
            existing_rounds=c.existing_rounds,
            warnings=c.warnings,
        )
    )
    _update_round_index(
        _RoundIndexUpdate(
            op_dir=c.op_dir,
            existing_rounds=c.existing_rounds,
            current_round=c.current_round,
            source_round_dir=c.source_round_dir,
            current_summary=c.current_summary,
            direction_metadata=c.direction_metadata,
            next_round_index=c.next_round_index,
            next_round_dir_name=c.next_round_dir_name,
            next_round_strategy=req.next_round_strategy,
            next_analysis_policy=req.next_analysis_policy,
            next_hypothesis=req.next_hypothesis,
            next_direction=req.next_direction,
            next_evidence_sources=req.next_evidence_sources,
            algorithm=req.algorithm,
            baseline_entry=c.baseline_entry,
            switch_marker=req.switch_marker,
            global_baseline_dir=c.global_baseline_dir,
            global_baseline_speedup=c.global_baseline_speedup,
        )
    )
    _append_opt_note(
        _OptNote(
            op_dir=c.op_dir,
            current_round=c.current_round,
            current_summary=c.current_summary,
            current_success_criteria=req.current_success_criteria,
            current_key_learnings=req.current_key_learnings,
            direction_metadata=c.direction_metadata,
            switch_marker=req.switch_marker,
        )
    )
    _write_transition_lock(
        c.op_dir, c.current_round, c.next_round_index, c.next_round_dir_name, c.warnings
    )


@dataclass
class TransitionRequest:
    """Inputs for atomically transitioning to the next round."""

    op_dir: Path | str
    current_round: int
    next_round_strategy: str
    next_analysis_policy: str
    next_hypothesis: str
    next_direction: str
    next_evidence_sources: list[str]
    current_success_criteria: str = ""
    current_key_learnings: str = ""
    baseline_dir: str | None = None
    baseline_dirs: list[str] | None = None
    combination_rule: str | None = None
    switch_marker: SwitchMarker | None = None
    strategy_name: str = "naive"
    strategy_params: dict[str, Any] | None = None
    global_baseline_dir: str | None = None
    global_baseline_speedup: float = 1.0
    algorithm: str = "naive"
    algorithm_metadata: dict[str, Any] | None = None


@dataclass
class _PreludeState:
    """Computed state from the transition prelude."""

    existing_rounds: list[dict[str, Any]]
    current_summary: dict[str, Any]
    next_round_index: int
    source_round_dir: str
    next_round_dir_name: str
    next_round_dir: Path
    strategy: Any
    op_name: str | None
    baseline_entry: dict[str, Any] | None
    baseline_speedup: float


def _prepare_transition(
    req: TransitionRequest, op_dir: Path, result: dict[str, Any]
) -> _PreludeState | None:
    """Validate the current round and prepare the next round directory."""
    issues, current_summary = _validate_current_round(op_dir / f"opt-round-{req.current_round}")
    if issues:
        result["issues"] = issues
        return None

    existing_rounds = _load_round_index(op_dir)
    max_existing = max((r.get("round_index", 0) for r in existing_rounds), default=0)
    next_round_index = max(req.current_round, max_existing) + 1
    source_round_dir = f"opt-round-{req.current_round}"
    next_round_dir_name = f"opt-round-{next_round_index}"
    result["next_round_dir"] = next_round_dir_name

    next_round_dir = op_dir / next_round_dir_name
    next_round_dir.mkdir(parents=True, exist_ok=True)

    config = read_config(op_dir.parent.parent)
    strategy = load_strategy_for_algorithm(config, req.algorithm, params=req.strategy_params)

    op_name = find_op_name(op_dir)
    baseline_entry, baseline_speedup = _select_and_copy_baseline(
        _BaselineSelection(
            op_dir=op_dir,
            op_name=op_name,
            baseline_dir=req.baseline_dir,
            baseline_dirs=req.baseline_dirs or [],
            next_round_dir=next_round_dir,
            strategy=strategy,
            algorithm=req.algorithm,
            warnings=result["warnings"],
        )
    )
    result["baseline_speedup"] = baseline_speedup

    return _PreludeState(
        existing_rounds=existing_rounds,
        current_summary=current_summary,
        next_round_index=next_round_index,
        source_round_dir=source_round_dir,
        next_round_dir_name=next_round_dir_name,
        next_round_dir=next_round_dir,
        strategy=strategy,
        op_name=op_name,
        baseline_entry=baseline_entry,
        baseline_speedup=baseline_speedup,
    )


def _write_metadata_and_summary(
    req: TransitionRequest,
    op_dir: Path,
    p: _PreludeState,
    global_baseline_dir: str | None,
    global_baseline_speedup: float,
) -> dict[str, Any]:
    """Compute direction metadata and write the next summary.json."""
    return _compute_metadata_and_write_summary(
        _MetadataAndSummary(
            op_dir=op_dir,
            source_round_dir=p.source_round_dir,
            current_summary=p.current_summary,
            baseline_entry=p.baseline_entry,
            strategy=p.strategy,
            switch_marker=req.switch_marker,
            global_baseline_speedup=global_baseline_speedup,
            next_round_index=p.next_round_index,
            algorithm=req.algorithm,
            global_baseline_dir=global_baseline_dir,
            next_round_strategy=req.next_round_strategy,
            next_analysis_policy=req.next_analysis_policy,
            next_hypothesis=req.next_hypothesis,
            next_direction=req.next_direction,
            next_evidence_sources=req.next_evidence_sources,
            algorithm_metadata=req.algorithm_metadata,
            next_round_dir=p.next_round_dir,
        )
    )


def _finalize_transition(
    req: TransitionRequest,
    op_dir: Path,
    p: _PreludeState,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Write the next-round artifacts and return the completed result."""
    global_baseline_dir = result["global_baseline_dir"]
    global_baseline_speedup = result["global_baseline_speedup"]
    direction_metadata = _write_metadata_and_summary(
        req, op_dir, p, global_baseline_dir, global_baseline_speedup
    )

    _write_transition_artifacts(
        req,
        _TransitionComputed(
            op_dir=op_dir,
            current_round=req.current_round,
            next_round_index=p.next_round_index,
            next_round_dir_name=p.next_round_dir_name,
            next_round_dir=p.next_round_dir,
            source_round_dir=p.source_round_dir,
            existing_rounds=p.existing_rounds,
            current_summary=p.current_summary,
            direction_metadata=direction_metadata,
            baseline_entry=p.baseline_entry,
            global_baseline_dir=global_baseline_dir,
            global_baseline_speedup=global_baseline_speedup,
            warnings=result["warnings"],
        )
    )

    result["status"] = "success"
    result["next_round"] = p.next_round_index
    result["issues"] = []
    return result


def transition_to_next_round(req: TransitionRequest) -> dict[str, Any]:
    """Atomically execute the round transition."""
    op_dir = Path(req.op_dir) if isinstance(req.op_dir, str) else req.op_dir
    result: dict[str, Any] = {
        "status": "fail",
        "next_round": req.current_round + 1,
        "next_round_dir": f"opt-round-{req.current_round + 1}",
        "baseline_speedup": 0.0,
        "global_baseline_speedup": req.global_baseline_speedup,
        "global_baseline_dir": req.global_baseline_dir,
        "issues": [],
        "warnings": [],
    }

    global_baseline_dir, global_baseline_speedup = _resolve_global_baseline(
        op_dir, req.global_baseline_dir, req.global_baseline_speedup
    )
    result["global_baseline_speedup"] = global_baseline_speedup
    result["global_baseline_dir"] = global_baseline_dir

    p = _prepare_transition(req, op_dir, result)
    if p is None:
        return result

    return _finalize_transition(req, op_dir, p, result)


def _saved_algorithm(state_dir: Path | None, op_dir: Path) -> str | None:
    """Read the algorithm stored in the workspace state file."""
    if state_dir is None:
        return None
    state_path = state_dir / f"state-{op_dir.name}.json"
    if not state_path.is_file():
        return None
    try:
        return load_json(state_path).get("algorithm")
    except ValueError:
        return None


def _resolve_algorithm(
    cli_algorithm: str | None,
    strategy_name: str,
    op_dir: Path,
) -> str:
    """Resolve the algorithm when --algorithm is not provided.

    Priority:
      1. Explicit CLI --algorithm.
      2. The single enabled algorithm in config.json.
      3. The algorithm saved in the current workspace state file, if enabled.
      4. The explicit --strategy-name (when not auto).
    """
    if cli_algorithm is not None:
        return cli_algorithm

    config = read_config(op_dir.parent.parent)
    discovered = set(discover_strategies().keys())
    enabled = [a for a in get_enabled_algorithms(config) if a in discovered]

    if len(enabled) == 1:
        return enabled[0]

    saved_algo = _saved_algorithm(_find_state_dir(op_dir), op_dir)
    if isinstance(saved_algo, str) and saved_algo in enabled:
        return saved_algo

    if strategy_name != "auto" and strategy_name in discovered:
        return strategy_name

    if not enabled:
        raise ValueError(
            "No algorithms are enabled in config.json; pass --algorithm explicitly."
        )
    raise ValueError(
        f"Multiple algorithms are enabled in config.json: {enabled}. "
        "Pass --algorithm explicitly."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transition to the next optimization round")
    parser.add_argument("--op-dir", required=True, help="Operator directory path")
    parser.add_argument("--current-round", type=int, required=True, help="Current round number")
    parser.add_argument(
        "--next-round-strategy",
        required=True,
        choices=[
            "exploration", "structural_change", "focused_tuning",
            "stabilization", "plateau_review",
        ],
        help="Next round strategy",
    )
    parser.add_argument("--next-analysis-policy", required=True,
                        choices=["pattern_entry", "bottleneck_analysis", "ir_supported"],
                        help="Next round analysis policy")
    parser.add_argument("--next-hypothesis", required=True, help="Next round hypothesis")
    parser.add_argument("--next-direction", required=True, help="Next round direction")
    parser.add_argument("--next-evidence-sources", required=True, help="JSON list of evidence sources")
    parser.add_argument("--current-success-criteria", default="", help="Current round success criteria")
    parser.add_argument("--current-key-learnings", default="", help="Current round key learnings")
    parser.add_argument("--baseline-dir", default=None,
                        help="Single baseline round directory to copy code from")
    parser.add_argument("--baseline-dirs", default=None,
                        help="JSON list of baseline round directories (multiple baseline mode)")
    parser.add_argument("--combination-rule", default=None,
                        help="How to combine multiple baselines (e.g. crossover)")
    parser.add_argument("--global-baseline-dir", default=None,
                        help="Global baseline directory for speedup reference")
    parser.add_argument("--global-baseline-speedup", type=float, default=1.0,
                        help="Global baseline speedup (default 1.0)")
    parser.add_argument("--switch-marker", default=None,
                        help='JSON object with reason/previous_direction/new_direction for audit')
    parser.add_argument("--strategy-name", default="auto",
                        help="Direction/baseline selection strategy name. "
                             "Use 'auto' to load the strategy configured in config.json "
                             "(defaults to naive if no config is found).")
    parser.add_argument("--strategy-params", default="{}",
                        help="JSON object of strategy-specific parameters. "
                             "Ignored when --strategy-name=auto.")
    parser.add_argument("--algorithm", default=None,
                        help="Optimization algorithm for the next round. "
                             "Required unless --strategy-name=auto and config.json enables "
                             "exactly one algorithm.")
    parser.add_argument("--algorithm-metadata", default="{}",
                        help="JSON object with algorithm-specific metadata to persist in next summary.json")
    return parser.parse_args()


def _safe_json_loads(raw: str) -> Any:
    """Parse JSON, returning None on malformed/absent input."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _emit_fail(current_round: int, message: str) -> int:
    """Print the standard fail JSON and return exit code 1."""
    sys.stdout.write(json.dumps({
        "status": "fail",
        "next_round": current_round + 1,
        "next_round_dir": f"opt-round-{current_round + 1}",
        "baseline_speedup": 0.0,
        "issues": [message],
        "warnings": [],
    }) + "\n")
    return 1


def _parse_switch_marker(raw: str | None) -> SwitchMarker | None:
    """Parse the --switch-marker JSON into a SwitchMarker, or None."""
    if not raw:
        return None
    data = _safe_json_loads(raw)
    if not isinstance(data, dict):
        return None
    return SwitchMarker(
        reason=data.get("reason", ""),
        previous_direction=data.get("previous_direction"),
        new_direction=data.get("new_direction"),
    )


def _build_transition_request(
    args: argparse.Namespace,
    op_dir: Path,
    algorithm: str,
) -> TransitionRequest:
    """Parse the CLI args into a TransitionRequest."""
    strategy_params = _safe_json_loads(args.strategy_params)
    if not isinstance(strategy_params, dict):
        strategy_params = {}
    if args.strategy_name == "auto":
        strategy_name = algorithm
        if not strategy_params:
            strategy_params = get_algorithm_params(read_config(op_dir.parent.parent), algorithm)
    else:
        strategy_name = args.strategy_name

    evidence_sources = _safe_json_loads(args.next_evidence_sources)
    if not isinstance(evidence_sources, list):
        evidence_sources = [args.next_evidence_sources]

    baseline_dirs: list[str] = []
    if args.baseline_dirs:
        parsed = _safe_json_loads(args.baseline_dirs)
        if isinstance(parsed, list):
            baseline_dirs = [str(x) for x in parsed]

    switch_marker = _parse_switch_marker(args.switch_marker)

    algorithm_metadata = _safe_json_loads(args.algorithm_metadata)
    if not isinstance(algorithm_metadata, dict):
        algorithm_metadata = {}

    return TransitionRequest(
        op_dir=op_dir,
        current_round=args.current_round,
        next_round_strategy=args.next_round_strategy,
        next_analysis_policy=args.next_analysis_policy,
        next_hypothesis=args.next_hypothesis,
        next_direction=args.next_direction,
        next_evidence_sources=evidence_sources,
        current_success_criteria=args.current_success_criteria,
        current_key_learnings=args.current_key_learnings,
        baseline_dir=args.baseline_dir,
        baseline_dirs=baseline_dirs,
        combination_rule=args.combination_rule,
        switch_marker=switch_marker,
        strategy_name=strategy_name,
        strategy_params=strategy_params,
        global_baseline_dir=args.global_baseline_dir,
        global_baseline_speedup=args.global_baseline_speedup,
        algorithm=algorithm,
        algorithm_metadata=algorithm_metadata,
    )


def main() -> int:
    args = _parse_args()

    op_dir = Path(args.op_dir).expanduser().resolve()
    if not op_dir.is_dir():
        return _emit_fail(args.current_round, f"operator directory not found: {op_dir}")

    try:
        algorithm = _resolve_algorithm(args.algorithm, args.strategy_name, op_dir)
    except ValueError as exc:
        return _emit_fail(args.current_round, str(exc))

    result = transition_to_next_round(_build_transition_request(args, op_dir, algorithm))
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
