# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: CANN-2.0
"""Bind Stage 7 to the plugin subgraph selected when this job was prepared."""

import argparse
import json
import logging
import os
from pathlib import Path


WORKFLOWS = {
    "stepwise": "pypto-op-tune-stepwise.yaml",
    "panko": "pypto-op-tune-panko.yaml",
}


def get_tuning_mode(record: dict) -> str:
    if not isinstance(record, dict):
        raise ValueError("prepared_case.json 必须是 JSON 对象")
    mode = record.get("tuning_mode", "stepwise")
    if not isinstance(mode, str) or mode not in WORKFLOWS:
        raise ValueError(f"未知 tuning_mode: {mode!r}")
    return mode


def select_workflow(prepared: Path, check_only: bool = False) -> str:
    mode = get_tuning_mode(json.loads(prepared.read_text(encoding="utf-8")))
    work_dir = prepared.absolute().parent
    source = Path(__file__).resolve().parents[1] / WORKFLOWS[mode]
    if not source.is_file():
        raise ValueError(f"插件缺少调优子图 {source}")
    if mode == "panko":
        evaluator = work_dir / ".agents/skills/pypto-op-perf-panko-manual/scripts/evaluate_candidate.py"
        if not evaluator.is_file():
            raise ValueError(f"PANKO Skill 缺少 {evaluator}")
    route = work_dir / ".workflow" / "pypto-stage7.yaml"
    if not check_only:
        route.parent.mkdir(parents=True, exist_ok=True)
        try:
            route.symlink_to(os.path.relpath(source, route.parent))
        except FileExistsError:
            pass  # A retry reuses the link. Never replace another job's choice.
    if not route.is_symlink() or route.resolve() != source:
        raise ValueError(f"{route} 与本次 {mode} 策略不符，请核对任务工作区")
    return mode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="只核对已选子图")
    args = parser.parse_args()
    try:
        mode = select_workflow(args.prepared, args.check)
    except (ValueError, OSError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1
    os.write(1, f"STAGE7_WORKFLOW_OK {mode}\n".encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
