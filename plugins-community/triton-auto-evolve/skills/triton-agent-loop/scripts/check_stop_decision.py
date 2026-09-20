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
"""Stop Decision Validation Script

Agent MUST run this script BEFORE outputting any "stop" or "final report" decision.
The script objectively verifies whether stop conditions (C1/C2) are met and
whether the active strategy recommends stopping, preventing subjective early
termination of the optimization loop.

Usage:
    python3 check_stop_decision.py \
        --op-dir triton_ascend_output/{op_name}-{algorithm}-{run_tag} \
        --current-round {N} \
        [--best-speedup X] \
        [--target-speedup Y] \
        [--max-rounds M] \
        [--algorithm-recommends-stop]

Output (JSON):
    {
        "can_stop": false,
        "reason": "no stop condition met",
        "conditions_met": [],
        "checks": { ... }
    }

Rules:
    - Agent MUST NOT stop when can_stop is false
    - Agent MUST NOT output a final summary report when can_stop is false
    - Agent MUST NOT ask the user for confirmation to continue when can_stop is false
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workspace_utils import read_round_summaries


def _read_rounds_from_summaries(op_dir: Path) -> list[dict[str, Any]]:
    """Read summary.json from each opt-round-* directory.

    Sorts directories by numeric round index and parses directories
    like opt-round-9-switch correctly (kept for backwards compatibility).
    """
    rounds = []
    for data in read_round_summaries(op_dir):
        if data.get("success", False):
            status = "success"
        elif data.get("failure_phase"):
            status = "active"
        else:
            status = "unknown"

        rounds.append({
            "round_index": data.get("round_index", 0),
            "round_dir": data["round_dir"],
            "best_speedup": data["best_speedup"],
            "round_strategy": data.get("round_strategy", ""),
            "direction": data.get("direction", ""),
            "analysis_policy": data.get("analysis_policy", "pattern_entry"),
            "status": status,
            "improvement_made": data.get("optimized", False),
            "phase4_entered": data.get("phase4_entered", False),
        })
    return rounds


def _effective_best_speedup(
    op_dir: Path,
    best_speedup: float,
    warnings: list[str],
) -> tuple[float, list[dict[str, Any]]]:
    """Read actual round data and reconcile it with the CLI best_speedup."""
    all_rounds = _read_rounds_from_summaries(op_dir)
    non_idle_entries = [
        r for r in all_rounds
        if r.get("best_speedup", 0) > 0 or r.get("phase4_entered", False)
    ]
    actual_best_speedup = max(
        (r.get("best_speedup", 0) for r in non_idle_entries), default=0
    )
    if (
        best_speedup > 0
        and actual_best_speedup > 0
        and abs(best_speedup - actual_best_speedup) > 0.001
    ):
        warnings.append(
            f"CLI best_speedup({best_speedup:.4f}) differs from actual max "
            f"from summary.json({actual_best_speedup:.4f}). Using actual value."
        )
    return max(best_speedup, actual_best_speedup), non_idle_entries


def _evaluate_c1(effective_best_speedup: float, target_speedup: float) -> tuple[bool, str]:
    """Evaluate C1: target speedup reached."""
    if not (
        isinstance(effective_best_speedup, (int, float))
        and isinstance(target_speedup, (int, float))
    ):
        return False, (
            f"non-numeric values: best_speedup={effective_best_speedup}, "
            f"target_speedup={target_speedup}"
        )
    if not (math.isfinite(effective_best_speedup) and target_speedup > 0):
        return False, (
            f"invalid values: best_speedup={effective_best_speedup}, "
            f"target_speedup={target_speedup}"
        )
    met = effective_best_speedup >= target_speedup
    detail = (
        f"best_speedup({effective_best_speedup:.4f}) "
        f"{'>=' if met else '<'} target_speedup({target_speedup})"
    )
    return met, detail


def _evaluate_c2(non_idle_count: int, max_rounds: int) -> tuple[bool, str]:
    """Evaluate C2: max rounds reached."""
    met = non_idle_count >= max_rounds
    detail = (
        f"non-idle rounds({non_idle_count}) "
        f"{'>=' if met else '<'} max_rounds({max_rounds})"
    )
    return met, detail


def _write_stop_lock(
    op_dir: Path,
    current_round: int,
    reason: str,
    conditions_met: list[str],
    warnings: list[str],
) -> None:
    """Persist the transition lock that releases the Phase 7 gate."""
    lock = {
        "action": "stop",
        "transition_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "from_round": current_round,
        "state_after": {
            "current_round": current_round,
            "last_phase": 7,
            "status": "completed" if current_round > 0 else "active",
        },
        "conditions_met": conditions_met,
    }
    lock_path = op_dir / ".transition_lock.json"
    try:
        lock_path.write_text(
            json.dumps(lock, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
    except OSError as exc:
        warnings.append(f"failed to write stop lock: {exc}")


@dataclass
class StopDecisionRequest:
    """Inputs for the objective C1/C2 stop-condition evaluation."""

    op_dir: Path | str
    current_round: int = 0
    best_speedup: float = 0.0
    target_speedup: float = 1.0
    max_rounds: int = 5
    algorithm_recommends_stop: bool = False


def check_stop_decision(req: StopDecisionRequest) -> dict[str, Any]:
    """Objectively evaluate C1/C2 stop conditions and strategy stop recommendation.

    Reads round data DIRECTLY from opt-round-*/summary.json files.
    Does NOT trust round_index.json (which the model can manipulate).

    Returns a structured decision that the Agent MUST obey.
    """
    op_dir = req.op_dir
    if isinstance(op_dir, str):
        op_dir = Path(op_dir)
    result: dict[str, Any] = {
        "can_stop": False,
        "reason": "",
        "conditions_met": [],
        "checks": {},
    }
    warnings: list[str] = result.setdefault("warnings", [])

    effective_best_speedup, non_idle_entries = _effective_best_speedup(
        op_dir, req.best_speedup, warnings
    )
    c1_met, c1_detail = _evaluate_c1(effective_best_speedup, req.target_speedup)
    c2_met, c2_detail = _evaluate_c2(len(non_idle_entries), req.max_rounds)

    strategy_stop_met = req.algorithm_recommends_stop
    strategy_detail = f"algorithm_recommends_stop={req.algorithm_recommends_stop}"

    conditions_met: list[str] = []
    if c1_met:
        conditions_met.append("C1")
    if c2_met:
        conditions_met.append("C2")
    if strategy_stop_met:
        conditions_met.append("strategy_stop")

    result["conditions_met"] = conditions_met
    result["checks"] = {
        "C1": {"met": c1_met, "detail": c1_detail},
        "C2": {"met": c2_met, "detail": c2_detail},
        "strategy_stop": {"met": strategy_stop_met, "detail": strategy_detail},
    }

    if c1_met:
        result["can_stop"] = True
        result["reason"] = "C1: target_reached"
    elif c2_met:
        result["can_stop"] = True
        result["reason"] = "C2: max_rounds_reached"
    elif strategy_stop_met:
        result["can_stop"] = True
        result["reason"] = "strategy_recommends_stop"
    else:
        result["reason"] = "no stop condition met (C1/C2 not met)"

    if result["can_stop"]:
        _write_stop_lock(op_dir, req.current_round, result["reason"], conditions_met, warnings)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate stop decision for Agent Loop (must run before any stop output)"
    )
    parser.add_argument("--op-dir", required=True, help="Operator directory path")
    parser.add_argument("--current-round", type=int, default=0, help="Current round number")
    parser.add_argument("--best-speedup", type=float, default=0.0, help="Best speedup achieved")
    parser.add_argument("--target-speedup", type=float, default=1.0, help="Target speedup")
    parser.add_argument("--max-rounds", type=int, default=5, help="Maximum rounds (config.json max_rounds)")
    parser.add_argument("--algorithm-recommends-stop", action="store_true",
                        help="The active strategy recommends stopping")
    args = parser.parse_args()

    op_dir = Path(args.op_dir).expanduser().resolve()
    if not op_dir.is_dir():
        sys.stdout.write(json.dumps({
            "can_stop": False,
            "reason": f"operator directory not found: {op_dir}",
            "conditions_met": [],
            "checks": {},
        }) + "\n")
        return 1

    result = check_stop_decision(
        StopDecisionRequest(
            op_dir=op_dir,
            current_round=args.current_round,
            best_speedup=args.best_speedup,
            target_speedup=args.target_speedup,
            max_rounds=args.max_rounds,
            algorithm_recommends_stop=args.algorithm_recommends_stop,
        )
    )
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if result["can_stop"] else 1


if __name__ == "__main__":
    sys.exit(main())
