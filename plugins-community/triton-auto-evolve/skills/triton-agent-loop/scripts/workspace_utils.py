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
"""Shared workspace introspection utilities."""

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sorted_round_dirs(op_dir: Path) -> list[Path]:
    """Return opt-round-* directories sorted by numeric round index."""
    def _round_index(p: Path) -> int:
        head = p.name.replace("opt-round-", "").split("-")[0]
        return int(head) if head.isdigit() else 0

    return sorted(op_dir.glob("opt-round-*"), key=_round_index)


def read_round_summaries(op_dir: Path) -> list[dict[str, Any]]:
    """Read summary.json from each opt-round-* directory.

    Returns the parsed summary of each readable file, augmented with its
    ``round_dir`` name and a normalized numeric ``best_speedup``. Missing or
    unreadable summaries are skipped.
    """
    summaries: list[dict[str, Any]] = []
    for rd in sorted_round_dirs(op_dir):
        summary_path = rd / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        speedup = data.get("best_speedup", 0)
        if not isinstance(speedup, (int, float)):
            speedup = 0

        data["round_dir"] = rd.name
        data["best_speedup"] = speedup
        summaries.append(data)
    return summaries


def find_op_name(op_dir: Path | str) -> str | None:
    """Return the authoritative operator name for a workspace.

    The workspace directory now includes the algorithm and run tag
    (e.g. ``layer_norm-mcts-default``), so ``op_dir.name`` is no longer
    the operator name. We look at stable metadata first, then generated
    code artifacts.
    """
    if isinstance(op_dir, str):
        op_dir = Path(op_dir)

    # 1. State file (most authoritative).
    state_dir = op_dir.parent.parent / ".triton-agent"
    state_path = state_dir / f"state-{op_dir.name}.json"
    if state_path.is_file():
        op_name = load_json(state_path).get("op_name")
        if isinstance(op_name, str) and op_name:
            return op_name

    # 2. Any task manifest in the operator directory.
    for manifest_path in sorted(op_dir.glob(".task_manifest_*.json")):
        op_name = load_json(manifest_path).get("op_name")
        if isinstance(op_name, str) and op_name:
            return op_name

    # 3. Immutable global baseline file.
    global_baseline = op_dir / "global_baseline"
    if global_baseline.is_dir():
        for path in sorted(global_baseline.glob("*_generated.py")):
            stem = path.stem
            if stem.endswith("_generated"):
                return stem[:-10]

    # 4. Round summaries (op_name field).
    for summary_path in sorted(op_dir.glob("opt-round-*/summary.json")):
        op_name = load_json(summary_path).get("op_name")
        if isinstance(op_name, str) and op_name:
            return op_name

    # 5. Generated code files in round directories.
    for rd in sorted(op_dir.glob("opt-round-*")):
        for path in sorted(rd.glob("*_generated.py")):
            stem = path.stem
            if stem.endswith("_generated"):
                return stem[:-10]

    return None
