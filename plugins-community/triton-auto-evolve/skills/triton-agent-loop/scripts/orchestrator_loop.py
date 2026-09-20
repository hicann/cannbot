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
"""orchestrator_loop.py — 主 Orchestrator 的 round 调度循环参考实现。

用法:
    python3 orchestrator_loop.py \
        --op-name layer_norm \
        --algorithm <discovered-algorithm> \
        --run-tag default \
        --mode A \
        --task-desc path/to/layer_norm.py \
        [--task-json path/to/layer_norm.json] \
        [--gpu-kernel-ref path/to/gpu_kernel_ref.py] \
        [--gpu-perf-csv path/to/gpu_perf.csv] \
        [--timeout 7200] \
        [--op-category matmul]

    可用算法由 skills/triton-agent-loop/scripts/strategies/ 下的 Strategy 子类动态发现。

说明:
    本脚本仅作为参考实现。主 Claude Code Agent 可以直接调用其中的函数，
    也可以复现其逻辑。它负责：
    1. 初始化 workspace 和 state-{op_name}-{algorithm}-{run_tag}.json
    2. 循环生成 task_manifest.json
    3. 调用 dispatch_round.py 启动子 CLI
    4. 解析 round_result.json
    5. 执行 C1/C2 停止/继续判定
    6. 停止时选择全局最优 round 并输出最终报告

工作区隔离:
    不同算法或同一算法的不同运行使用独立目录：
        triton_ascend_output/{op_name}-{algorithm}-{run_tag}/

设计变更（v2）:
    - C3/D4 判定从 Orchestrator 移除，下沉到各进化策略内部。
    - 不再创建 opt-round-N-switch 目录；方向切换只作为元数据记录。
    - 所有策略通过 RoundDecision 信封返回决策，Orchestrator 只补全缺失项。
    - algorithm 不再配置在 config.json 中；由用户在会话开始时选择，并写入 state。
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config_loader import (
    read_config,
    get_enabled_algorithms,
    get_algorithm_params,
)
from direction_selector import build_direction_history
from strategies import discover_strategies, load_strategy_for_algorithm
from strategies.base import BaselineProposal, RoundDecision

logger = logging.getLogger(__name__)


SCRIPT_DIR = Path(__file__).resolve().parent
CTRL_SKILLS_DIR = SCRIPT_DIR.parent
REPO_OPS_CANDIDATES = [
    SCRIPT_DIR.parents[5] / "ops",
    SCRIPT_DIR.parents[6] / "ops",
]


@dataclass
class MigrateLegacyRequest:
    """Inputs for migrating a legacy workspace to the new naming scheme."""

    cwd: Path
    op_name: str
    algorithm: str
    run_tag: str
    legacy_op_dir: Path
    legacy_state: dict[str, Any]


@dataclass
class WorkspaceSpec:
    """Inputs for initializing a Round 1 workspace."""

    cwd: Path
    op_name: str
    op_dir: Path
    mode: str
    task_desc: Path
    task_json: Path | None
    gpu_kernel_ref: Path | None
    gpu_perf_csv: Path | None
    config: dict[str, Any]
    algorithm: str
    run_tag: str = "default"


@dataclass
class ManifestSpec:
    """Inputs for building a round worker task_manifest.json."""

    op_dir: Path
    op_name: str
    round_index: int
    baseline_dir: Path | None
    algorithm: str
    round_strategy: str
    analysis_policy: str
    hypothesis: str
    direction: str
    evidence_sources: list[str]
    mode: str
    task_desc: Path
    task_json: Path | None
    gpu_kernel_ref: Path | None
    gpu_perf_csv: Path | None
    config: dict[str, Any]
    arch: str = "ascend910b1"
    lineage_summary: list[dict[str, Any]] | None = None
    experience_file: str | None = None
    global_baseline_dir: Path | None = None
    global_baseline_speedup: float = 1.0
    decision_metadata: dict[str, Any] | None = None


@dataclass
class StopDecisionRequest:
    """Inputs for the stop-decision subprocess wrapper."""

    op_dir: Path
    current_round: int
    best_speedup: float
    target_speedup: float
    max_rounds: int
    algorithm_recommends_stop: bool = False


@dataclass
class PrepareNextRoundRequest:
    """Inputs for preparing the next round via transition_next_round.py."""

    op_dir: Path
    current_round: int
    decision: RoundDecision
    config: dict[str, Any]
    round_index: list[dict[str, Any]]
    algorithm: str
    op_category: str | None = None
    global_baseline_dir: str | None = "global_baseline"
    global_baseline_speedup: float = 1.0


@dataclass
class OrchestratorConfig:
    """CLI-driven inputs for a full orchestrator run."""

    cwd: Path
    op_name: str
    mode: str
    task_desc: Path
    task_json: Path | None
    gpu_kernel_ref: Path | None
    gpu_perf_csv: Path | None
    timeout: int = 7200
    op_category: str | None = None
    arch: str = "ascend910b1"
    algorithm: str | None = None
    run_tag: str = "default"
    migrate_legacy: str | None = None
    detect_legacy: bool = False


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_ops_root() -> Path | None:
    """Find shared ops/ directory."""
    for candidate in REPO_OPS_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def _algorithm_reference(algorithm: str) -> str:
    """Return the reference document path for an algorithm."""
    return f".claude/references/algorithms/{algorithm}/round.md"


def select_algorithm(
    config: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> str | None:
    """Determine the active optimization algorithm for this task.

    Priority:
      1. ``state["algorithm"]`` if present and still enabled.
      2. If exactly one algorithm is enabled in ``config["algorithms"]``, use it.
      3. Otherwise return ``None`` so the caller can ask the user.

    The main Claude Code agent should use ``AskUserQuestion`` when this function
    returns ``None``.  When running this script directly, pass ``--algorithm``.
    """
    discovered = set(discover_strategies().keys())
    enabled = [a for a in get_enabled_algorithms(config) if a in discovered]
    if not enabled:
        raise ValueError("No algorithms are enabled in config.json")

    if state and isinstance(state.get("algorithm"), str):
        algo = state["algorithm"]
        if algo in enabled:
            return algo

    if len(enabled) == 1:
        return enabled[0]

    return None


def _discovered_algorithm_names() -> set[str]:
    """Return the set of algorithm names discovered from strategy modules."""
    return set(discover_strategies().keys())


def _find_legacy_workspace(
    cwd: Path, op_name: str
) -> tuple[Path, dict[str, Any]] | None:
    """Detect a legacy workspace: triton_ascend_output/{op_name}/ + state-{op_name}.json."""
    legacy_op_dir = cwd / "triton_ascend_output" / op_name
    legacy_state_path = cwd / ".triton-agent" / f"state-{op_name}.json"
    if not legacy_op_dir.is_dir() or not legacy_state_path.is_file():
        return None
    try:
        return legacy_op_dir, load_json(legacy_state_path)
    except ValueError:
        return None


def _first_round_algorithm(round_index_path: Path, discovered: set[str]) -> str | None:
    """Read the algorithm from the first entry of a legacy round_index.json."""
    if not round_index_path.is_file():
        return None
    try:
        data = load_json(round_index_path)
    except ValueError:
        return None
    if not (isinstance(data, list) and data):
        return None
    algo = data[0].get("algorithm")
    if isinstance(algo, str) and algo in discovered:
        return algo
    return None


def _summary_algorithm(legacy_op_dir: Path, discovered: set[str]) -> str | None:
    """Read the algorithm from the first legacy summary.json that declares one."""
    for summary_path in sorted(legacy_op_dir.glob("opt-round-*/summary.json")):
        try:
            algo = load_json(summary_path).get("algorithm")
        except ValueError:
            continue
        if isinstance(algo, str) and algo in discovered:
            return algo
    return None


def _infer_algorithm_from_legacy(
    legacy_state: dict[str, Any],
    legacy_op_dir: Path,
    discovered: set[str],
) -> str | None:
    """Infer the algorithm used by a legacy workspace from multiple sources."""
    state_algo = legacy_state.get("algorithm")
    if isinstance(state_algo, str) and state_algo in discovered:
        return state_algo

    algo = _first_round_algorithm(legacy_op_dir / "round_index.json", discovered)
    if algo is not None:
        return algo

    return _summary_algorithm(legacy_op_dir, discovered)


def _discover_algorithm_from_new_state(cwd: Path, op_name: str) -> str | None:
    """Scan new-format state files and read the saved algorithm.

    Returns the algorithm if exactly one matching state file exists; otherwise
    returns None so the caller can ask the user or fall back to other sources.
    """
    state_dir = cwd / ".triton-agent"
    if not state_dir.is_dir():
        return None
    matches = list(state_dir.glob(f"state-{op_name}-*.json"))
    if len(matches) != 1:
        return None
    try:
        return load_json(matches[0]).get("algorithm")
    except ValueError:
        return None


def _list_new_state_algorithms(
    cwd: Path,
    op_name: str,
    run_tag: str | None = None,
) -> dict[str, Path]:
    """Return a mapping of algorithm -> state file path for new-format states.

    If *run_tag* is provided, only state files whose names end with
    ``-{run_tag}.json`` are considered. This isolates workspaces that differ
    only by run tag so that ``--algorithm naive --run-tag run2`` does not
    conflict with an existing ``state-{op_name}-mcts-default.json``.
    """
    state_dir = cwd / ".triton-agent"
    if not state_dir.is_dir():
        return {}
    result: dict[str, Path] = {}
    for path in state_dir.glob(f"state-{op_name}-*.json"):
        if run_tag is not None and not path.name.endswith(f"-{run_tag}.json"):
            continue
        try:
            algo = load_json(path).get("algorithm")
            if isinstance(algo, str) and algo:
                result[algo] = path
        except ValueError:
            continue
    return result


def _build_legacy_report(
    op_name: str,
    legacy_op_dir: Path,
    legacy_state: dict[str, Any],
    inferred: str | None,
) -> dict[str, Any]:
    """Build a structured report about a detected legacy workspace."""
    return {
        "type": "legacy_workspace_detected",
        "op_name": op_name,
        "legacy_dir": str(legacy_op_dir),
        "legacy_state": str(
            legacy_op_dir.parent.parent / ".triton-agent" / f"state-{op_name}.json"
        ),
        "current_round": legacy_state.get("current_round", "unknown"),
        "last_work_dir": legacy_state.get("work_dir", "unknown"),
        "state_algorithm": legacy_state.get("algorithm", "unknown"),
        "inferred_algorithm": inferred,
        "migration_plan": (
            f"Rename {legacy_op_dir.name} to {op_name}-<algorithm>-<run_tag>/, "
            f"create .triton-agent/state-{op_name}-<algorithm>-<run_tag>.json, "
            "preserve all round data."
        ),
        "options": [
            {
                "id": "continue_inferred",
                "label": f"Continue with inferred algorithm '{inferred or 'unknown'}'",
            },
            {"id": "specify_algorithm", "label": "Specify a different algorithm"},
            {"id": "abandon", "label": "Abandon legacy workspace and start fresh"},
        ],
    }


def _migrate_legacy_workspace(req: MigrateLegacyRequest) -> Path:
    """Migrate a legacy workspace to the new naming scheme.

    Returns the new operator directory path.
    """
    new_op_dir = req.cwd / "triton_ascend_output" / f"{req.op_name}-{req.algorithm}-{req.run_tag}"
    new_state_path = req.cwd / ".triton-agent" / f"state-{new_op_dir.name}.json"
    if new_op_dir.exists():
        raise FileExistsError(f"Migration target already exists: {new_op_dir}")

    req.legacy_op_dir.rename(new_op_dir)

    current_round = req.legacy_state.get("current_round", 1)
    work_dir = new_op_dir / f"opt-round-{current_round}"
    req.legacy_state.update(
        {
            "algorithm": req.algorithm,
            "run_tag": req.run_tag,
            "algorithm_reference": _algorithm_reference(req.algorithm),
            "work_dir": str(work_dir),
        }
    )
    save_json(new_state_path, req.legacy_state)

    # Ensure a round_index.json exists so the migration is treated as a recovery
    # rather than a fresh initialization.
    round_index_path = new_op_dir / "round_index.json"
    if not round_index_path.is_file():
        save_json(round_index_path, [])

    legacy_state_path = req.cwd / ".triton-agent" / f"state-{req.op_name}.json"
    if legacy_state_path.is_file():
        legacy_state_path.write_text(
            json.dumps(
                {
                    "migrated": True,
                    "migrated_to": str(new_state_path),
                    "migrated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    return new_op_dir


def _init_global_baseline(op_dir: Path, op_name: str, task_desc: Path) -> None:
    """Copy the user task file as the immutable global baseline."""
    global_baseline_dir = op_dir / "global_baseline"
    global_baseline_dir.mkdir(parents=True, exist_ok=True)
    if task_desc.is_file():
        shutil.copy2(task_desc, global_baseline_dir / f"{op_name}_generated.py")
    baseline_info = {
        "source_path": str(task_desc),
        "baseline_speedup": 1.0,
        "established_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json(global_baseline_dir / "baseline_info.json", baseline_info)


def _write_experience_file(op_dir: Path, op_name: str, algorithm: str, run_tag: str) -> None:
    """Write the operator-level experience file (private to this run)."""
    experience_path = op_dir / "operator_experience.md"
    experience_path.write_text(
        f"# Operator Experience: {op_name} ({algorithm}/{run_tag})\n\n"
        "## Failures / Avoid\n"
        "<!-- Sub-agent appends here after each round -->\n\n"
        "## Successful Patterns\n"
        "<!-- Sub-agent appends here after each round -->\n\n"
        "## Notes\n",
        encoding="utf-8",
    )


@dataclass
class InitialStateSpec:
    """Inputs for writing the initial .triton-agent/ state file."""

    cwd: Path
    op_dir: Path
    op_name: str
    algorithm: str
    run_tag: str
    algorithm_ref: str
    round_dir: Path


def _write_initial_state(spec: InitialStateSpec) -> None:
    """Write the initial .triton-agent/ state file."""
    state = {
        "op_name": spec.op_name,
        "algorithm": spec.algorithm,
        "run_tag": spec.run_tag,
        "status": "active",
        "current_round": 1,
        "algorithm_reference": spec.algorithm_ref,
        "rounds": {"1": {"status": "active", "round_dir": "opt-round-1"}},
        "phase": "round_active",
        "work_dir": str(spec.round_dir),
        "last_phase": 0,
        "performance_history": [],
        "direction_history": [],
    }
    state_dir = spec.cwd / ".triton-agent"
    state_dir.mkdir(parents=True, exist_ok=True)
    save_json(state_dir / f"state-{spec.op_dir.name}.json", state)


def _write_initial_summary(round_dir: Path, op_name: str, algorithm: str, config: dict[str, Any]) -> None:
    """Write the Round 1 summary.json."""
    summary = {
        "round_index": 1,
        "algorithm": algorithm,
        "baseline_dir": "global_baseline",
        "global_baseline_dir": "global_baseline",
        "global_baseline_speedup": 1.0,
        "round_strategy": "exploration",
        "analysis_policy": "pattern_entry",
        "hypothesis": f"Initial LLM-driven exploration for {op_name} optimization",
        "direction": "pattern: custom",
        "evidence_sources": ["model_knowledge"],
        "status": "active",
        "best_speedup": 0.0,
        "success": False,
        "target_speedup": config.get("target_speedup", 5),
    }
    save_json(round_dir / "summary.json", summary)


def _write_initial_round_index(op_dir: Path, op_name: str, algorithm: str, config: dict[str, Any]) -> None:
    """Write the Round 1 round_index.json."""
    round_index = [{
        "round_index": 1,
        "round_dir": "opt-round-1",
        "algorithm": algorithm,
        "direction": "pattern: custom",
        "hypothesis": f"Initial LLM-driven exploration for {op_name} optimization",
        "evidence_sources": ["model_knowledge"],
        "analysis_policy": "pattern_entry",
        "effective_metric_source": "kernel",
        "status": "active",
        "best_speedup": 0.0,
        "round_strategy": "exploration",
        "direction_yield": None,
        "yield_reason": None,
        "absolute_gain_vs_baseline": None,
        "absolute_gain_vs_global_baseline": None,
        "baseline_dir": "global_baseline",
        "global_baseline_dir": "global_baseline",
        "global_baseline_speedup": 1.0,
        "consecutive_low_gain_count": 0,
        "round_type": "active",
        "target_speedup": config.get("target_speedup", 5),
    }]
    save_json(op_dir / "round_index.json", round_index)


def init_workspace(spec: WorkspaceSpec) -> Path:
    """Initialize workspace for Round 1."""
    algorithm_ref = _algorithm_reference(spec.algorithm)

    round_dir = spec.op_dir / "opt-round-1"
    round_dir.mkdir(parents=True, exist_ok=True)

    _init_global_baseline(spec.op_dir, spec.op_name, spec.task_desc)
    _write_experience_file(spec.op_dir, spec.op_name, spec.algorithm, spec.run_tag)
    _write_initial_state(
        InitialStateSpec(
            cwd=spec.cwd,
            op_dir=spec.op_dir,
            op_name=spec.op_name,
            algorithm=spec.algorithm,
            run_tag=spec.run_tag,
            algorithm_ref=algorithm_ref,
            round_dir=round_dir,
        )
    )
    _write_initial_summary(round_dir, spec.op_name, spec.algorithm, spec.config)
    _write_initial_round_index(spec.op_dir, spec.op_name, spec.algorithm, spec.config)

    return round_dir


def build_manifest(spec: ManifestSpec) -> Path:
    """Write task_manifest.json for the round worker."""
    work_dir = spec.op_dir / f"opt-round-{spec.round_index}"
    work_dir.mkdir(parents=True, exist_ok=True)

    algorithm_reference = _algorithm_reference(spec.algorithm)
    algorithm_params = get_algorithm_params(spec.config, spec.algorithm)

    # Optionally surface the parent round's detailed journal to the sub-agent.
    parent_round_journal: str | None = None
    if spec.baseline_dir is not None:
        journal_path = Path(spec.baseline_dir) / "round_journal.md"
        if journal_path.is_file():
            parent_round_journal = str(journal_path)

    manifest: dict[str, Any] = {
        "op_name": spec.op_name,
        "round_index": spec.round_index,
        "work_dir": str(work_dir),
        "baseline_dir": str(spec.baseline_dir) if spec.baseline_dir else None,
        "algorithm": spec.algorithm,
        "algorithm_reference": algorithm_reference,
        "algorithm_params": algorithm_params,
        "round_strategy": spec.round_strategy,
        "analysis_policy": spec.analysis_policy,
        "hypothesis": spec.hypothesis,
        "direction": spec.direction,
        "evidence_sources": spec.evidence_sources,
        "mode": spec.mode,
        "arch": spec.arch,
        "input_files": {
            "task_desc": str(spec.task_desc),
            "task_json": str(spec.task_json) if spec.task_json else None,
            "gpu_kernel_ref": str(spec.gpu_kernel_ref) if spec.gpu_kernel_ref else None,
            "gpu_perf_csv": str(spec.gpu_perf_csv) if spec.gpu_perf_csv else None,
        },
        "config": spec.config,
        "is_recovery": False,
        "worker_reference": algorithm_reference,
        "lineage_summary": spec.lineage_summary or [],
        "experience_file": spec.experience_file,
        "global_baseline_dir": str(spec.global_baseline_dir) if spec.global_baseline_dir else None,
        "global_baseline_speedup": spec.global_baseline_speedup,
        "parent_round_journal": parent_round_journal,
    }

    # Forward algorithm-specific metadata from the strategy decision envelope.
    # For MCTS this includes mcts_parent_id, mcts_selection_path, etc.
    if spec.decision_metadata:
        for key in ("mcts_parent_id", "mcts_selection_path", "mcts_pending_expansion"):
            if key in spec.decision_metadata:
                manifest[key] = spec.decision_metadata[key]

    manifest_path = spec.op_dir / f".task_manifest_{spec.round_index}.json"
    save_json(manifest_path, manifest)
    return manifest_path


def dispatch_round(manifest_path: Path, timeout: int = 7200) -> dict[str, Any]:
    """Call dispatch_round.py to spawn sub CLI."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "dispatch_round.py"),
        "--manifest", str(manifest_path),
        "--timeout", str(timeout),
    ]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return json.loads(output)
    except subprocess.CalledProcessError as exc:
        try:
            return json.loads(exc.output)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "stderr": exc.output,
                "returncode": exc.returncode,
            }
    except json.JSONDecodeError as exc:
        return {"status": "error", "stderr": f"invalid JSON from dispatch_round.py: {exc}"}


def update_round_index(
    op_dir: Path,
    round_result: dict[str, Any],
    active_algorithm: str | None = None,
) -> None:
    """Update round_index.json with completed round info.

    Uses ``active_algorithm`` as the fallback when the sub-agent result does not
    report an algorithm. This prevents a hard-coded "naive" default from causing
    algorithm drift when the active run uses mcts/gene-fusion.
    """
    round_index_path = op_dir / "round_index.json"
    round_index = load_json(round_index_path) if round_index_path.is_file() else []
    if not isinstance(round_index, list):
        round_index = []

    idx = round_result.get("round_index", 0)
    entry = next((r for r in round_index if r.get("round_index") == idx), None)
    if entry is None:
        entry = {
            "round_index": idx,
            "round_dir": f"opt-round-{idx}",
        }
        round_index.append(entry)

    entry.update({
        "algorithm": round_result.get("algorithm") or active_algorithm or "naive",
        "direction": round_result.get("direction", ""),
        "hypothesis": round_result.get("hypothesis", ""),
        "effective_metric_source": round_result.get("effective_metric_source", "kernel"),
        "status": round_result.get("status", "failed"),
        "best_speedup": round_result.get("best_speedup", 0.0),
        "round_strategy": round_result.get("round_strategy", "exploration"),
    })

    # Optional fields enriched by the sub-agent; preserve existing values if absent.
    optional_fields = [
        "evidence_sources",
        "analysis_policy",
        "direction_yield",
        "yield_reason",
        "absolute_gain_vs_baseline",
        "baseline_dir",
        "design_summary",
        "iter_count",
        "opt_iter_count",
        "key_fixes",
        "bottlenecks_observed",
        "parent_round_journal",
    ]
    for key in optional_fields:
        if key in round_result:
            entry[key] = round_result[key]

    save_json(round_index_path, round_index)


def check_stop_decision(req: StopDecisionRequest) -> dict[str, Any]:
    """Run check_stop_decision.py."""
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "check_stop_decision.py"),
        "--op-dir", str(req.op_dir),
        "--current-round", str(req.current_round),
        "--best-speedup", str(req.best_speedup),
        "--target-speedup", str(req.target_speedup),
        "--max-rounds", str(req.max_rounds),
    ]
    if req.algorithm_recommends_stop:
        cmd.append("--algorithm-recommends-stop")
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return json.loads(output)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return {"can_stop": False, "reason": str(exc)}


def count_non_idle_rounds(round_index: list[dict[str, Any]]) -> int:
    return sum(1 for r in round_index if r.get("status") != "skipped_idle")


def build_lineage_summary(
    round_index: list[dict[str, Any]],
    target_round_dir: str,
) -> list[dict[str, Any]]:
    """Build a root-to-leaf lineage summary for the target round."""
    by_dir = {entry.get("round_dir"): entry for entry in round_index if entry.get("round_dir")}
    lineage: list[dict[str, Any]] = []
    visited: set[str] = set()
    current_dir = target_round_dir

    while current_dir and current_dir not in visited:
        visited.add(current_dir)
        entry = by_dir.get(current_dir)
        if entry is None:
            break
        lineage_entry: dict[str, Any] = {
            "round_index": entry.get("round_index"),
            "round_dir": current_dir,
            "direction": entry.get("direction"),
            "best_speedup": entry.get("best_speedup"),
            "direction_yield": entry.get("direction_yield"),
            "hypothesis": entry.get("hypothesis"),
            "parent_round_dir": entry.get("baseline_dir"),
        }
        # Enrich the summary with design/iteration metadata when available.
        for key in (
            "design_summary",
            "iter_count",
            "opt_iter_count",
            "key_fixes",
            "bottlenecks_observed",
            "outcome",
        ):
            if key in entry:
                lineage_entry[key] = entry[key]
        lineage.append(lineage_entry)
        current_dir = entry.get("baseline_dir") or ""

    lineage.reverse()
    return lineage


def resolve_baseline(
    op_dir: Path,
    decision: RoundDecision,
    round_index: list[dict[str, Any]],
    op_name: str,
) -> Path | None:
    """Resolve the baseline directory from a RoundDecision.

    Returns the path to the baseline generated code, or None if the next round
    should start without a baseline. If the strategy-selected parent round has
    no code (e.g., a virtual MCTS node), fall back to the global baseline.
    """
    baseline = decision.baseline
    if baseline.mode == "none":
        selected_dir = ""
    elif baseline.mode == "single":
        selected_dir = baseline.round_dirs[0] if baseline.round_dirs else ""
    else:
        selected_dir = ""
        for round_dir_name in baseline.round_dirs:
            if not round_dir_name:
                continue
            candidate = op_dir / round_dir_name / f"{op_name}_generated.py"
            if candidate.is_file():
                return candidate

    if selected_dir:
        candidate = op_dir / selected_dir / f"{op_name}_generated.py"
        if candidate.is_file():
            return candidate

    # Fallback to the immutable global baseline (user-provided reference code).
    global_baseline_candidate = op_dir / "global_baseline" / f"{op_name}_generated.py"
    if global_baseline_candidate.is_file():
        return global_baseline_candidate
    return None


def prepare_next_round(req: PrepareNextRoundRequest) -> dict[str, Any]:
    """Prepare the next round directory using transition_next_round.py."""
    decision = req.decision
    switch_marker = decision.switch_marker
    algorithm_metadata = dict(decision.metadata or {})
    algorithm_params = get_algorithm_params(req.config, req.algorithm)

    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "transition_next_round.py"),
        "--op-dir", str(req.op_dir),
        "--current-round", str(req.current_round),
        "--next-round-strategy", decision.round_strategy or "exploration",
        "--next-analysis-policy", decision.analysis_policy or "pattern_entry",
        "--next-hypothesis", decision.hypothesis or "",
        "--next-direction", decision.direction or "",
        "--next-evidence-sources", json.dumps(decision.evidence_sources, ensure_ascii=False),
        "--strategy-name", req.algorithm,
        "--strategy-params", json.dumps(algorithm_params, ensure_ascii=False),
        "--algorithm", req.algorithm,
        "--algorithm-metadata", json.dumps(algorithm_metadata, ensure_ascii=False),
        "--current-success-criteria", "speedup_vs_baseline >= target",
        "--current-key-learnings", "",
        "--global-baseline-dir", req.global_baseline_dir or "global_baseline",
        "--global-baseline-speedup", str(req.global_baseline_speedup),
    ]

    baseline = decision.baseline
    if baseline.mode == "single" and baseline.round_dirs:
        cmd.extend(["--baseline-dir", baseline.round_dirs[0]])
    elif baseline.mode == "multiple":
        cmd.extend(["--baseline-dirs", json.dumps(baseline.round_dirs, ensure_ascii=False)])
        if baseline.combination_rule:
            cmd.extend(["--combination-rule", baseline.combination_rule])

    if switch_marker is not None:
        cmd.extend([
            "--switch-marker",
            json.dumps({
                "reason": switch_marker.reason,
                "previous_direction": switch_marker.previous_direction,
                "new_direction": switch_marker.new_direction,
            }, ensure_ascii=False),
        ])

    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    return json.loads(output)


def _replace_section(content: str, heading: str, section: str) -> str:
    """Replace an existing section for the same operator, or append if absent."""
    idx = content.find(f"\n{heading}")
    if idx == -1:
        idx = content.find(heading)
    if idx != -1:
        next_heading = content.find("\n## ", idx + 1)
        if next_heading == -1:
            return content[:idx] + section
        return content[:idx] + section + content[next_heading + 1:]
    return content.rstrip() + "\n\n" + section


def _update_global_template(
    cwd: Path,
    op_name: str,
    category: str | None,
    best_round_entry: dict[str, Any] | None,
    operator_experience_path: Path,
) -> Path | None:
    """Append or replace the operator-specific experience in the project template.

    The project template lives at ``.claude/template/{category}.md`` and is
    copied per project by ``init.sh``. Updates only affect the current project
    unless manually synced across projects.
    """
    category = category or "general"
    template_dir = cwd / ".claude" / "template"
    template_dir.mkdir(parents=True, exist_ok=True)
    template_path = template_dir / f"{category}.md"

    heading = f"## Experience: {op_name}"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    best_round = best_round_entry.get("round_index") if best_round_entry else None
    best_speedup = best_round_entry.get("best_speedup") if best_round_entry else None
    target_reached = best_round_entry.get("target_reached") if best_round_entry else None
    final_code = (
        best_round_entry.get("artifacts", {}).get("generated_code")
        if best_round_entry
        else None
    )

    lines = [
        heading,
        "",
        f"- **Updated**: {timestamp}",
        f"- **Best round**: {best_round}",
        f"- **Best speedup**: {best_speedup}",
        f"- **Target reached**: {target_reached}",
    ]
    if final_code:
        lines.append(f"- **Final code**: `{final_code}`")

    if operator_experience_path.is_file():
        exp_text = operator_experience_path.read_text(encoding="utf-8").strip()
        if exp_text:
            lines.extend(["", "### Operator experience", "", exp_text])

    section = "\n".join(lines) + "\n\n"

    if template_path.is_file():
        content = template_path.read_text(encoding="utf-8")
    else:
        content = f"# {category.capitalize()} operator optimization experience\n\n"

    # Replace an existing section for the same operator, or append if not present.
    content = _replace_section(content, heading, section)

    template_path.write_text(content, encoding="utf-8")
    return template_path


@dataclass
class StopReportSpec:
    """Inputs for building the final stop report."""

    cwd: Path
    op_dir: Path
    op_name: str
    op_category: str | None
    round_index: list[dict[str, Any]]
    target_speedup: float
    non_idle_count: int
    reason: str


def _build_stop_report(spec: StopReportSpec) -> dict[str, Any]:
    """Build the final stop report and copy the best generated code out."""
    best_entry = max(
        (r for r in spec.round_index if r.get("status") == "success"),
        key=lambda r: r.get("best_speedup", 0.0),
        default=None,
    )
    final_report: dict[str, Any] = {
        "status": "stopped",
        "reason": spec.reason,
        "best_round": best_entry.get("round_index") if best_entry else None,
        "best_speedup": best_entry.get("best_speedup", 0.0) if best_entry else 0.0,
        "target_speedup": spec.target_speedup,
        "total_rounds": spec.non_idle_count,
    }
    if best_entry:
        src = spec.op_dir / best_entry["round_dir"] / f"{spec.op_name}_generated.py"
        dst = spec.op_dir / f"{spec.op_name}_final.py"
        shutil.copy2(src, dst)
        final_report["final_code"] = str(dst)
    _update_global_template(
        spec.cwd, spec.op_name, spec.op_category, best_entry, spec.op_dir / "operator_experience.md"
    )
    return final_report


def _needs_effective_baseline(
    decision: RoundDecision,
    proposed_dir: str,
    concrete_file: Path | None,
) -> bool:
    """Return True when the proposal needs to be mapped to the global baseline."""
    return (
        decision.baseline.mode == "none"
        or not proposed_dir
        or concrete_file is None
        or not concrete_file.is_file()
    )


def _fill_missing_direction(
    strategy: Any,
    decision: RoundDecision,
    round_index: list[dict[str, Any]],
    op_category: str | None,
    current_policy: str,
) -> None:
    """Fill direction fields the strategy did not provide (LLM-driven)."""
    if decision.direction is not None:
        return
    if strategy.capabilities.can_select_round:
        # Round-selection strategies (e.g., MCTS) intentionally leave
        # direction to the sub-agent.
        return
    if strategy.capabilities.can_propose_direction:
        import direction_selector as ds
        sel = ds.select_next_direction(
            round_index,
            op_category=op_category,
            current_policy=current_policy,
        )
        decision.direction = sel.direction
        decision.hypothesis = sel.hypothesis or decision.hypothesis
        decision.round_strategy = sel.strategy or decision.round_strategy
        decision.analysis_policy = sel.analysis_policy or decision.analysis_policy
        decision.evidence_sources = sel.evidence_sources or decision.evidence_sources
        if not decision.metadata:
            decision.metadata = sel.metadata
        return
    decision.direction = "pattern: custom"


def _resolve_next_baseline(
    op_dir: Path,
    decision: RoundDecision,
    round_index: list[dict[str, Any]],
    op_name: str,
    strategy: Any,
) -> Path | None:
    """Pick and resolve the baseline for the next round."""
    if decision.baseline.mode == "none" and decision.direction:
        best_score = -1.0
        best_entry: dict[str, Any] | None = None
        for entry in round_index:
            if entry.get("status") != "success":
                continue
            score = strategy.score_baseline_for_direction(
                entry,
                target_direction=decision.direction,
                target_strategy=decision.round_strategy or "exploration",
                context={"op_dir": str(op_dir)},
            )
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry:
            decision.baseline = BaselineProposal(
                mode="single", round_dirs=[best_entry["round_dir"]]
            )

    baseline_file = resolve_baseline(op_dir, decision, round_index, op_name)
    if baseline_file is None:
        return None

    baseline_dir = baseline_file.parent
    proposed_dir = decision.baseline.round_dirs[0] if decision.baseline.round_dirs else ""
    concrete_file = (
        op_dir / proposed_dir / f"{op_name}_generated.py" if proposed_dir else None
    )
    if _needs_effective_baseline(decision, proposed_dir, concrete_file):
        effective_dir = baseline_dir.relative_to(op_dir).as_posix()
        decision.baseline = BaselineProposal(mode="single", round_dirs=[effective_dir])
    return baseline_dir


@dataclass
class _WorkspaceContext:
    """Resolved workspace state handed from the prelude to the round loop."""

    config: dict[str, Any]
    target_speedup: float
    max_rounds: int
    max_worker_timeout: int
    active_algorithm: str
    op_dir: Path
    state_path: Path
    strategy: Any
    op_name: str
    mode: str
    task_desc: Path
    task_json: Path | None
    gpu_kernel_ref: Path | None
    gpu_perf_csv: Path | None
    op_category: str | None
    arch: str
    cwd: Path
    run_tag: str


def _handle_detect_legacy(cfg: OrchestratorConfig, discovered: set[str]) -> dict[str, Any] | None:
    """Handle the --detect-legacy early exit; returns None if not requested."""
    if not cfg.detect_legacy:
        return None
    legacy = _find_legacy_workspace(cfg.cwd, cfg.op_name)
    if legacy is None:
        sys.stdout.write(json.dumps({"type": "none"}, indent=2, ensure_ascii=False) + "\n")
        return {"_exit_code": 0}
    legacy_op_dir, legacy_state = legacy
    inferred = _infer_algorithm_from_legacy(legacy_state, legacy_op_dir, discovered)
    report = _build_legacy_report(cfg.op_name, legacy_op_dir, legacy_state, inferred)
    sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return {"_exit_code": 0}


def _resolve_legacy_workspace(
    cfg: OrchestratorConfig,
    discovered: set[str],
    existing_state_algorithms: dict[str, Path],
    algorithm: str | None,
) -> tuple[str | None, tuple | None] | dict[str, Any]:
    """Infer the algorithm from a legacy workspace; returns (algorithm, legacy) or exit dict."""
    if existing_state_algorithms:
        return algorithm, None
    legacy = _find_legacy_workspace(cfg.cwd, cfg.op_name)
    if legacy is None:
        return algorithm, None
    legacy_op_dir, legacy_state = legacy
    inferred = _infer_algorithm_from_legacy(legacy_state, legacy_op_dir, discovered)
    if not cfg.migrate_legacy:
        report = _build_legacy_report(cfg.op_name, legacy_op_dir, legacy_state, inferred)
        sys.stderr.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return {"_exit_code": 3}
    algorithm = cfg.migrate_legacy
    if inferred and algorithm != inferred:
        logger.warning(
            "requested migration algorithm '%s' differs from "
            "inferred '%s'. Using requested algorithm.",
            algorithm, inferred,
        )
    return algorithm, legacy


def _resolve_from_existing_state(
    cfg: OrchestratorConfig,
    discovered: set[str],
    existing_state_algorithms: dict[str, Path],
    algorithm: str | None,
) -> str | None:
    """Resolve the algorithm from existing state files, or validate the CLI choice."""
    if algorithm is None:
        if len(existing_state_algorithms) == 1:
            new_state_algorithm = next(iter(existing_state_algorithms.keys()))
            if new_state_algorithm not in discovered:
                raise ValueError(
                    f"Saved algorithm '{new_state_algorithm}' has no strategy. "
                    f"Available: {sorted(discovered)}"
                )
            return new_state_algorithm
        if len(existing_state_algorithms) > 1:
            algos = sorted(existing_state_algorithms.keys())
            raise ValueError(
                f"Multiple existing workspaces found for '{cfg.op_name}': {algos}. "
                f"Please specify --algorithm or --migrate-legacy."
            )
        return None
    for existing_algo, existing_path in existing_state_algorithms.items():
        if existing_algo != algorithm:
            raise ValueError(
                f"Existing workspace uses algorithm '{existing_algo}' "
                f"({existing_path.name}). Conflicts with --algorithm {algorithm}."
            )
    return algorithm


def _resolve_algorithm(
    cfg: OrchestratorConfig, config: dict[str, Any]
) -> tuple[str, tuple | None] | dict[str, Any]:
    """Resolve the active algorithm; returns (algorithm, legacy) or an early-exit dict."""
    cwd = cfg.cwd
    op_name = cfg.op_name
    algorithm = cfg.algorithm
    run_tag = cfg.run_tag
    discovered = _discovered_algorithm_names()

    early = _handle_detect_legacy(cfg, discovered)
    if early is not None:
        return early

    if algorithm is not None and algorithm not in discovered:
        raise ValueError(
            f"Algorithm '{algorithm}' not discovered. Available: {sorted(discovered)}"
        )

    existing_state_algorithms = _list_new_state_algorithms(cwd, op_name, run_tag)
    algorithm = _resolve_from_existing_state(cfg, discovered, existing_state_algorithms, algorithm)

    resolved = _resolve_legacy_workspace(cfg, discovered, existing_state_algorithms, algorithm)
    if isinstance(resolved, dict):
        return resolved
    algorithm, legacy = resolved

    if algorithm is None:
        algorithm = select_algorithm(config, None)
    if algorithm is None:
        raise ValueError(
            "No active algorithm selected. In the main Claude Code agent use "
            "AskUserQuestion; when running this script directly pass --algorithm."
        )
    return algorithm, legacy


def _migrate_if_needed(
    cfg: OrchestratorConfig,
    op_dir: Path,
    state_path: Path,
    active_algorithm: str,
    legacy: tuple | None,
) -> tuple[Path, Path]:
    """Migrate the legacy workspace if one exists and the new one does not."""
    if legacy is None or op_dir.exists():
        return op_dir, state_path
    legacy_op_dir, legacy_state = legacy
    op_dir = _migrate_legacy_workspace(
        MigrateLegacyRequest(
            cwd=cfg.cwd,
            op_name=cfg.op_name,
            algorithm=active_algorithm,
            run_tag=cfg.run_tag,
            legacy_op_dir=legacy_op_dir,
            legacy_state=legacy_state,
        )
    )
    state_path = cfg.cwd / ".triton-agent" / f"state-{op_dir.name}.json"
    return op_dir, state_path


def _init_workspace_and_strategy(
    cfg: OrchestratorConfig,
    config: dict[str, Any],
    active_algorithm: str,
    legacy: tuple | None,
) -> tuple[Path, Path, Any]:
    """Create/migrate the workspace and load the strategy."""
    cwd = cfg.cwd
    op_name = cfg.op_name
    run_tag = cfg.run_tag

    op_dir = cwd / "triton_ascend_output" / f"{op_name}-{active_algorithm}-{run_tag}"
    state_path = cwd / ".triton-agent" / f"state-{op_dir.name}.json"
    op_dir, state_path = _migrate_if_needed(cfg, op_dir, state_path, active_algorithm, legacy)

    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = load_json(state_path)
        except ValueError:
            state = {}

    if not state_path.is_file() or not (op_dir / "round_index.json").is_file():
        init_workspace(
            WorkspaceSpec(
                cwd=cwd,
                op_name=op_name,
                op_dir=op_dir,
                mode=cfg.mode,
                task_desc=cfg.task_desc,
                task_json=cfg.task_json,
                gpu_kernel_ref=cfg.gpu_kernel_ref,
                gpu_perf_csv=cfg.gpu_perf_csv,
                config=config,
                algorithm=active_algorithm,
                run_tag=run_tag,
            )
        )
        state = load_json(state_path)

    state["algorithm"] = active_algorithm
    save_json(state_path, state)

    strategy = _load_strategy(config, active_algorithm, op_dir)
    return op_dir, state_path, strategy


def _load_strategy(config: dict[str, Any], active_algorithm: str, op_dir: Path) -> Any:
    """Load the strategy and run its per-operator initialization."""
    strategy = load_strategy_for_algorithm(config, active_algorithm)
    round_index_for_init: list[dict[str, Any]] = []
    if (op_dir / "round_index.json").is_file():
        try:
            round_index_for_init = load_json(op_dir / "round_index.json")
        except ValueError:
            pass
    if hasattr(strategy, "init_for_operator"):
        strategy.init_for_operator(op_dir, config, round_index_for_init)
    return strategy


def _resolve_and_init_workspace(cfg: OrchestratorConfig) -> _WorkspaceContext | dict[str, Any]:
    """Resolve the algorithm, initialize the workspace, and load the strategy.

    Returns a ``_WorkspaceContext`` on success, or a ``{"_exit_code": N}`` dict
    for the detect-legacy / legacy-not-migrating early-exit paths.
    """
    config = read_config(cfg.cwd)

    resolved = _resolve_algorithm(cfg, config)
    if isinstance(resolved, dict):
        return resolved
    active_algorithm, legacy = resolved

    op_dir, state_path, strategy = _init_workspace_and_strategy(cfg, config, active_algorithm, legacy)

    return _WorkspaceContext(
        config=config,
        target_speedup=config.get("target_speedup", 5),
        max_rounds=config.get("max_rounds", 10),
        max_worker_timeout=config.get("max_worker_timeout", 28800),
        active_algorithm=active_algorithm,
        op_dir=op_dir,
        state_path=state_path,
        strategy=strategy,
        op_name=cfg.op_name,
        mode=cfg.mode,
        task_desc=cfg.task_desc,
        task_json=cfg.task_json,
        gpu_kernel_ref=cfg.gpu_kernel_ref,
        gpu_perf_csv=cfg.gpu_perf_csv,
        op_category=cfg.op_category,
        arch=cfg.arch,
        cwd=cfg.cwd,
        run_tag=cfg.run_tag,
    )


@dataclass
class _SuccessCtx:
    """State handed to the per-round success handler."""

    strategy: Any
    op_dir: Path
    op_name: str
    op_category: str | None
    current_round: int
    work_dir: Path
    state_path: Path
    active_algorithm: str
    target_speedup: float
    max_rounds: int
    cwd: Path
    summary: dict[str, Any]
    round_result: dict[str, Any]
    config: dict[str, Any]
    global_baseline_speedup: float


def _record_round_result(c: _SuccessCtx) -> None:
    """Record the completed round in any state-aware strategy (e.g. MCTS)."""
    if not hasattr(c.strategy, "record_round_result"):
        return
    try:
        round_index = load_json(c.op_dir / "round_index.json")
        current_entry = next(
            (r for r in round_index if r.get("round_index") == c.current_round), None
        )
        if current_entry:
            c.strategy.record_round_result(
                current_entry,
                c.work_dir,
                context={"op_dir": str(c.op_dir), "current_round": c.current_round},
            )
    except Exception as exc:
        logger.warning("[orchestrator] Strategy record_round_result warning: %s", exc)


def _make_stop_report(
    c: _SuccessCtx,
    round_index: list[dict[str, Any]],
    non_idle_count: int,
    reason: str,
) -> dict[str, Any]:
    """Build the final stop report."""
    return _build_stop_report(
        StopReportSpec(
            cwd=c.cwd,
            op_dir=c.op_dir,
            op_name=c.op_name,
            op_category=c.op_category,
            round_index=round_index,
            target_speedup=c.target_speedup,
            non_idle_count=non_idle_count,
            reason=reason,
        )
    )


def _check_stop(
    c: _SuccessCtx,
    round_index: list[dict[str, Any]],
    non_idle_count: int,
    decision: RoundDecision,
    best_speedup: float,
) -> dict[str, Any] | None:
    """Run the stop gate; returns a stop report or None to continue."""
    c1 = best_speedup >= c.target_speedup
    c2 = non_idle_count >= c.max_rounds
    if decision.algorithm_recommends_stop:
        stop_check = check_stop_decision(
            StopDecisionRequest(
                op_dir=c.op_dir,
                current_round=c.current_round,
                best_speedup=best_speedup,
                target_speedup=c.target_speedup,
                max_rounds=c.max_rounds,
                algorithm_recommends_stop=True,
            )
        )
        if stop_check.get("can_stop", False) or c1 or c2:
            return _make_stop_report(
                c, round_index, non_idle_count,
                decision.stop_reason or ("C1" if c1 else "C2"),
            )
    if c1 or c2:
        stop_check = check_stop_decision(
            StopDecisionRequest(
                op_dir=c.op_dir,
                current_round=c.current_round,
                best_speedup=best_speedup,
                target_speedup=c.target_speedup,
                max_rounds=c.max_rounds,
            )
        )
        if stop_check.get("can_stop", False):
            return _make_stop_report(c, round_index, non_idle_count, "C1" if c1 else "C2")
    return None


def _update_state_and_prepare(
    c: _SuccessCtx,
    round_index: list[dict[str, Any]],
    best_speedup: float,
    decision: RoundDecision,
) -> None:
    """Update the state file and prepare the next round directory."""
    state = load_json(c.state_path)
    state.setdefault("performance_history", []).append({
        "round": c.current_round,
        "speedup_vs_torch": best_speedup,
        "target_reached": best_speedup >= c.target_speedup,
    })
    state["direction_history"] = build_direction_history(round_index)
    state["algorithm"] = c.active_algorithm
    save_json(c.state_path, state)

    prepare_next_round(
        PrepareNextRoundRequest(
            op_dir=c.op_dir,
            current_round=c.current_round,
            decision=decision,
            config=c.config,
            round_index=round_index,
            algorithm=c.active_algorithm,
            op_category=c.op_category,
            global_baseline_dir="global_baseline",
            global_baseline_speedup=c.global_baseline_speedup,
        )
    )


def _process_success_round(c: _SuccessCtx) -> dict[str, Any] | None:
    """Handle a successful round: stop gate, state update, next-round prep.

    Returns a result dict for an early stop/failure, or ``None`` to continue.
    """
    update_round_index(c.op_dir, c.round_result, c.active_algorithm)
    _record_round_result(c)

    best_speedup = c.round_result.get("best_speedup", 0.0)
    round_index = load_json(c.op_dir / "round_index.json")
    non_idle_count = count_non_idle_rounds(round_index)

    current_policy = c.summary.get("analysis_policy", "pattern_entry")
    try:
        decision = c.strategy.select_next_round(
            round_index,
            op_category=c.op_category,
            current_policy=current_policy,
            context={"op_dir": str(c.op_dir), "current_round": c.current_round},
        )
    except Exception as exc:
        return {
            "status": "failed",
            "reason": f"strategy.select_next_round failed: {exc}",
            "round": c.current_round,
        }

    result = _check_stop(c, round_index, non_idle_count, decision, best_speedup)
    if result is not None:
        return result

    _fill_missing_direction(c.strategy, decision, round_index, c.op_category, current_policy)
    _resolve_next_baseline(c.op_dir, decision, round_index, c.op_name, c.strategy)
    _update_state_and_prepare(c, round_index, best_speedup, decision)
    return None


@dataclass
class _RoundLoad:
    """Per-round context loaded from the workspace."""

    baseline_dir: Path | None
    global_baseline_dir: Path
    global_baseline_speedup: float
    lineage_summary: list[dict[str, Any]]
    experience_file: Path
    decision_metadata: dict[str, Any]


def _read_global_baseline_speedup(op_dir: Path) -> float:
    """Read the global baseline speedup, defaulting to 1.0."""
    global_baseline_speedup = 1.0
    baseline_info_path = op_dir / "global_baseline" / "baseline_info.json"
    if baseline_info_path.is_file():
        try:
            baseline_info = load_json(baseline_info_path)
            gbs = baseline_info.get("baseline_speedup", 1.0)
            if isinstance(gbs, (int, float)) and gbs > 0:
                global_baseline_speedup = float(gbs)
        except (ValueError, TypeError):
            pass
    return global_baseline_speedup


def _load_round_context(
    op_dir: Path, current_round: int, active_algorithm: str, summary: dict[str, Any]
) -> _RoundLoad:
    """Load the per-round baseline, lineage, and decision metadata."""
    round_index_path = op_dir / "round_index.json"
    round_index: list[dict[str, Any]] = []
    baseline_dir_name = None
    if round_index_path.is_file():
        try:
            round_index = load_json(round_index_path)
            entry = next(
                (r for r in round_index if r.get("round_index") == current_round), None
            )
            if entry:
                baseline_dir_name = entry.get("baseline_dir")
        except (ValueError, TypeError):
            pass
    if not baseline_dir_name:
        baseline_dir_name = summary.get("baseline_dir")
    baseline_dir = op_dir / baseline_dir_name if baseline_dir_name else None

    global_baseline_dir = op_dir / "global_baseline"
    global_baseline_speedup = _read_global_baseline_speedup(op_dir)

    experience_file = op_dir / "operator_experience.md"
    lineage_summary = build_lineage_summary(round_index, f"opt-round-{current_round}")

    summary_algorithm = summary.get("algorithm")
    if summary_algorithm and summary_algorithm != active_algorithm:
        logger.warning(
            "summary.json algorithm (%s) differs from active algorithm (%s); "
            "using active algorithm.",
            summary_algorithm, active_algorithm,
        )
    decision_metadata: dict[str, Any] = {}
    for key in ("mcts_parent_id", "mcts_selection_path", "mcts_pending_expansion"):
        if key in summary:
            decision_metadata[key] = summary[key]

    return _RoundLoad(
        baseline_dir=baseline_dir,
        global_baseline_dir=global_baseline_dir,
        global_baseline_speedup=global_baseline_speedup,
        lineage_summary=lineage_summary,
        experience_file=experience_file,
        decision_metadata=decision_metadata,
    )


def _dispatch_worker(
    ctx: _WorkspaceContext,
    manifest_path: Path,
    work_dir: Path,
    current_round: int,
    current_timeout: int,
) -> tuple[dict[str, Any], int]:
    """Dispatch the worker and handle timeout, returning (result, new_timeout)."""
    dispatch_result = dispatch_round(manifest_path, current_timeout)
    sub_pid = dispatch_result.get("pid")
    if sub_pid:
        logger.info("[orchestrator] Round %s sub-agent PID: %s", current_round, sub_pid)
        logger.info("[orchestrator] To kill manually: kill %s", sub_pid)

    if dispatch_result["status"] != "timeout":
        return dispatch_result, current_timeout

    new_timeout = min(current_timeout * 2, ctx.max_worker_timeout)
    logger.warning(
        "[orchestrator] Round %s timed out after %ss; increasing timeout to %ss for next round",
        current_round, current_timeout, new_timeout,
    )
    state = load_json(ctx.state_path)
    state.setdefault("performance_history", []).append({
        "round": current_round,
        "speedup_vs_torch": 0.0,
        "target_reached": False,
        "timeout": True,
    })
    save_json(ctx.state_path, state)
    if hasattr(ctx.strategy, "record_round_result"):
        try:
            ctx.strategy.record_round_result(
                {"round_index": current_round, "status": "timeout", "best_speedup": 0.0},
                work_dir,
                context={"op_dir": str(ctx.op_dir), "current_round": current_round},
            )
        except Exception as exc:
            logger.warning("[orchestrator] Strategy record_round_result warning: %s", exc)
    return dispatch_result, new_timeout


def _build_manifest_path(
    ctx: _WorkspaceContext,
    summary: dict[str, Any],
    current_round: int,
    rl: _RoundLoad,
) -> Path:
    """Build the round worker's task_manifest.json and return its path."""
    return build_manifest(
        ManifestSpec(
            op_dir=ctx.op_dir,
            op_name=ctx.op_name,
            round_index=current_round,
            baseline_dir=rl.baseline_dir,
            algorithm=ctx.active_algorithm,
            round_strategy=summary.get("round_strategy", "exploration"),
            analysis_policy=summary.get("analysis_policy", "pattern_entry"),
            hypothesis=summary.get("hypothesis", ""),
            direction=summary.get("direction", ""),
            evidence_sources=summary.get("evidence_sources", []),
            mode=ctx.mode,
            task_desc=ctx.task_desc,
            task_json=ctx.task_json,
            gpu_kernel_ref=ctx.gpu_kernel_ref,
            gpu_perf_csv=ctx.gpu_perf_csv,
            config=ctx.config,
            arch=ctx.arch,
            lineage_summary=rl.lineage_summary,
            experience_file=str(rl.experience_file) if rl.experience_file.is_file() else None,
            global_baseline_dir=rl.global_baseline_dir,
            global_baseline_speedup=rl.global_baseline_speedup,
            decision_metadata=rl.decision_metadata,
        )
    )


def run_orchestrator(cfg: OrchestratorConfig) -> dict[str, Any]:
    """Main orchestration loop."""
    ctx = _resolve_and_init_workspace(cfg)
    if isinstance(ctx, dict):
        return ctx
    current_timeout = cfg.timeout

    while True:
        state = load_json(ctx.state_path)
        current_round = state.get("current_round")
        work_dir = Path(state.get("work_dir"))
        summary = load_json(work_dir / "summary.json")

        rl = _load_round_context(ctx.op_dir, current_round, ctx.active_algorithm, summary)
        manifest_path = _build_manifest_path(ctx, summary, current_round, rl)

        dispatch_result, current_timeout = _dispatch_worker(
            ctx, manifest_path, work_dir, current_round, current_timeout
        )
        if dispatch_result["status"] == "timeout":
            continue
        if dispatch_result["status"] != "success":
            return {
                "status": "failed",
                "reason": f"dispatch_round failed: {dispatch_result.get('stderr', '')}",
                "round": current_round,
            }
        result = _process_success_round(
            _SuccessCtx(
                strategy=ctx.strategy,
                op_dir=ctx.op_dir,
                op_name=ctx.op_name,
                op_category=ctx.op_category,
                current_round=current_round,
                work_dir=work_dir,
                state_path=ctx.state_path,
                active_algorithm=ctx.active_algorithm,
                target_speedup=ctx.target_speedup,
                max_rounds=ctx.max_rounds,
                cwd=ctx.cwd,
                summary=summary,
                round_result=dispatch_result["round_result"],
                config=ctx.config,
                global_baseline_speedup=rl.global_baseline_speedup,
            )
        )
        if result is not None:
            return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Triton Auto Evolve Orchestrator Loop")
    parser.add_argument("--op-name", required=True, help="Operator name")
    parser.add_argument("--algorithm", default=None,
                        help="Optimization algorithm (required when multiple algorithms are enabled). "
                             "Must match a discovered strategy name.")
    parser.add_argument("--run-tag", default="default",
                        help="Run tag to isolate multiple runs of the same operator/algorithm (default: default)")
    parser.add_argument("--mode", default="A", choices=["A", "B"], help="Input mode")
    parser.add_argument("--task-desc", required=True, help="Path to task description .py file")
    parser.add_argument("--task-json", default=None, help="Path to task JSON file (multi-case mode)")
    parser.add_argument("--gpu-kernel-ref", default=None, help="Path to GPU kernel reference file")
    parser.add_argument("--gpu-perf-csv", default=None, help="Path to GPU performance CSV")
    parser.add_argument("--timeout", type=int, default=7200, help="Initial sub CLI timeout in seconds")
    parser.add_argument(
        "--op-category",
        default=None,
        help="Operator category (elementwise, matmul, normalization, ...)",
    )
    parser.add_argument("--arch", default="ascend910b1", help="Target Ascend architecture (e.g. ascend910b3)")
    parser.add_argument(
        "--migrate-legacy",
        default=None,
        metavar="ALGORITHM",
        help="Migrate a legacy workspace (triton_ascend_output/{op_name}/) to "
             "the new naming and continue with ALGORITHM",
    )
    parser.add_argument(
        "--detect-legacy",
        action="store_true",
        help="Detect legacy workspace, print JSON report, and exit without modifying anything",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()

    cwd = Path.cwd()
    result = run_orchestrator(
        OrchestratorConfig(
            cwd=cwd,
            op_name=args.op_name,
            mode=args.mode,
            task_desc=Path(args.task_desc).expanduser().resolve(),
            task_json=Path(args.task_json).expanduser().resolve() if args.task_json else None,
            gpu_kernel_ref=Path(args.gpu_kernel_ref).expanduser().resolve() if args.gpu_kernel_ref else None,
            gpu_perf_csv=Path(args.gpu_perf_csv).expanduser().resolve() if args.gpu_perf_csv else None,
            timeout=args.timeout,
            op_category=args.op_category,
            arch=args.arch,
            algorithm=args.algorithm,
            run_tag=args.run_tag,
            migrate_legacy=args.migrate_legacy,
            detect_legacy=args.detect_legacy,
        )
    )
    exit_code = result.pop("_exit_code", None)
    if exit_code is not None:
        return exit_code
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if result.get("status") == "stopped" else 1


if __name__ == "__main__":
    sys.exit(main())
