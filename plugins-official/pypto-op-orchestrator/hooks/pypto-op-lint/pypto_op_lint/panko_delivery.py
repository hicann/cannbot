# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: CANN-2.0
"""Validate the PANKO controller evidence for the delivered implementation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Literal


_SUCCESSFUL_STOPS = (
    "success",
    "converged",
    "wall_clock",
    "eval_budget",
    "frontier_exhausted",
    "global_stagnation",
)


def _positive_finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _is_natural_stop(progress: dict, terminal: dict) -> bool:
    reason = progress["stop_reason"]
    if progress.get("forced_stop") or reason not in _SUCCESSFUL_STOPS:
        return False
    if terminal["directive"] != "STOP" or terminal["reason"] != reason:
        return False
    start = progress["_start_ts"]
    return _positive_finite(start) and start == terminal["run_start"]


def _budget_error(budget: int | None, used: int, reason: str) -> str | None:
    if type(used) is not int or used < 1:
        return "PANKO evaluation count must include the measured baseline"
    if budget is not None and (type(budget) is not int or used > budget):
        return "PANKO evaluation count exceeds the configured budget or the budget is invalid"
    if reason == "eval_budget" and used != budget:
        return "PANKO budget STOP requires the configured budget to be exhausted"
    return None


def _valid_code_handoff(receipt: dict, folder: Path) -> bool:
    if not isinstance(receipt["coder"], bool) or not isinstance(receipt["through_block"], bool):
        return False
    if not all(isinstance(receipt[key], str) and receipt[key].strip() for key in ("action_id", "intent")):
        return False
    digests = (receipt["base_hash"], receipt["candidate_hash"], receipt["evaluated_hash"])
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in digests):
        return False
    if not receipt["through_block"] and receipt["candidate_hash"] != receipt["evaluated_hash"]:
        return False
    if receipt["coder"]:
        if not isinstance(receipt.get("summary"), str) or not receipt["summary"].strip():
            return False
        for digest in digests[:2]:
            snapshot = folder / "nodes" / (digest + ".py")
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
                return False
    return True


def _handoff_error(search: dict, folder: Path) -> str | None:
    receipts = search.get("code_handoffs", [])
    baseline_hash = next(node["code_hash"] for node in search["nodes"]["closed"] if node["id"] == "root")
    direct_hashes = {baseline_hash}  # INIT already accounts for this measurement.
    for receipt in receipts:
        if not _valid_code_handoff(receipt, folder) or receipt["evaluated_hash"] not in search["eval_cache"]:
            return "PANKO CODE receipt does not match its action, snapshots or evaluated source"
        if not receipt["through_block"]:
            digest = receipt["evaluated_hash"]
            if digest in direct_hashes:
                return f"PANKO duplicate receipt for a directly evaluated candidate: {digest}"
            direct_hashes.add(digest)
    progress = search["progress"]
    block_trials = 0
    for block in search.get("blocks", []):
        trials = block["device_trials"]
        if type(trials) is not int or trials < 0:
            return "PANKO BO trial count is invalid"
        block_trials += trials
    if block_trials != progress.get("block_evals", 0) or len(direct_hashes) + block_trials != progress["evals_used"]:
        return "PANKO has evaluations without a CODE receipt or measured BO trial"
    return None


def _latency_source(config: dict, requested: str | None, required: bool) -> str | None:
    if "delivery_latency_source" in config:
        source = config["delivery_latency_source"]
        if requested is not None and requested != source:
            raise ValueError("Requested PANKO latency source conflicts with the registered INIT configuration")
    elif requested is not None:
        source = requested
    elif required:
        raise ValueError("PANKO INIT did not register a timer. For an existing run, "
                         "pass --panko-latency-source from the original request")
    else:
        return None
    if source not in ("aicore", "case_timer"):
        raise ValueError(f"Unknown PANKO delivery_latency_source: {source!r}")
    return source


def read_tuning_result(path: Path) -> dict:
    """Read a published tuning result with a positive finite latency in microseconds."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Invalid tuning result {path.name}: {error}") from error
    latency = result.get("optimized_us") if isinstance(result, dict) else None
    if not _positive_finite(latency):
        raise ValueError(f"{path.name}: optimized_us must be a positive finite number")
    return result


def check_panko_delivery(op_dir: Path, op_name: str, *,
                         phase: Literal["stage_gate", "search", "delivery"] = "stage_gate",
                         requested_latency_source: str | None = None,
                         tuning_result: dict | None = None) -> tuple[str, str | None]:
    """Verify controller evidence. The search phase precedes publication of the tuning result."""
    folder = op_dir / "optimization"
    try:
        search = json.loads((folder / "search_state.json").read_text(encoding="utf-8"))
        terminal = json.loads((folder / "controller-terminal.json").read_text(encoding="utf-8"))
        progress = search["progress"]
        if search["op"] != op_name or not _is_natural_stop(progress, terminal):
            return "", "PANKO controller STOP does not match this run or is not a natural completion"
        reason = progress["stop_reason"]
        config = search["config"]
        budget_error = _budget_error(config["eval_budget"], progress["evals_used"], reason)
        if budget_error:
            return "", budget_error
        source = _latency_source(config, requested_latency_source, required=phase != "stage_gate")

        if phase == "search" or config.get("checkpoint_handoffs"):
            handoff_error = _handoff_error(search, folder)
            if handoff_error:
                return "", handoff_error

        best = next(node for node in search["nodes"]["closed"] if node["id"] == search["best_node"])
        delivered = hashlib.sha256((op_dir / f"{op_name}_impl.py").read_bytes()).hexdigest()
        hashes_match = best["code_hash"] == delivered == terminal["delivered_code_hash"]
        measured = best["eval"]
        if not hashes_match or measured["s"] != 1 or not _positive_finite(measured["p"]):
            return "", "PANKO delivered source does not match the measured best candidate"
        if phase != "search" and source is not None:
            result_path = op_dir / f"{op_name}_tune_result.json"
            if tuning_result is None:
                tuning_result = read_tuning_result(result_path)
            latency = tuning_result["optimized_us"]
            if source == "aicore" and latency != measured["p"]:
                return "", (f"{result_path.name}: optimized_us {latency} differs from the measured "
                            f"AICore winner {measured['p']} us")
    except (OSError, ValueError, TypeError, KeyError, StopIteration, OverflowError) as error:
        return "", f"PANKO search state or controller record is missing or invalid: {error}"
    return reason, None
