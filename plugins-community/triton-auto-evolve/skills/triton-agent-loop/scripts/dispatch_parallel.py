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
"""dispatch_parallel.py — 并行启动多个 route 子 CLI，每个 route 独立执行
.claude/references/algorithms/gene-fusion/route.md 的完整 pipeline。

用法:
  python3 dispatch_parallel.py --manifests route-1/.task_manifest.json route-2/.task_manifest.json --timeout 3600
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="dispatch_parallel.py — 并行启动多个 route 子 CLI")
    parser.add_argument("--manifests", nargs="+", required=True, help="task manifest 文件路径列表")
    parser.add_argument("--timeout", type=int, default=3600, help="每个 route 的超时时间（秒），默认 3600")
    parser.add_argument("--output", type=str, default=None, help="结果输出 JSON 文件路径，默认写入第一个 manifest 的 work_dir 同级")
    return parser.parse_args()


def _prepare_route_workspace(manifest_path: Path) -> tuple[str, Path]:
    """Write the isolated manifest + AGENTS.md and return (route_id, work_dir)."""
    manifest = json.loads(manifest_path.read_text())
    route_id = manifest.get("route_id", manifest_path.parent.name)
    work_dir = Path(manifest.get("work_dir", manifest_path.parent))
    work_dir.mkdir(parents=True, exist_ok=True)

    # 将 manifest_path 写入 work_dir 内的 .task_manifest.json
    target_manifest = work_dir / ".task_manifest.json"
    target_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    # 写一个简单的 AGENTS.md 指向 route 规范
    agents_md = work_dir / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(f"""---
name: triton-route-worker-{route_id}
description: Route Worker for gene-fusion — 执行 .claude/references/algorithms/gene-fusion/route.md 完整 pipeline
mode: primary
temperature: 0.1
---

# Route Worker: {route_id}

你是 Gene-Fusion 的 Route Worker。你的完整规范在 `.claude/references/algorithms/gene-fusion/route.md`。

请读取 `{target_manifest}` 后按照规范执行。
""")
    return route_id, work_dir


def _run_route_subprocess(
    route_id: str,
    manifest_path: Path,
    work_dir: Path,
    timeout: int,
) -> dict:
    """Launch the route worker sub-CLI and wait for completion."""
    start_time = time.time()
    proc = subprocess.Popen(
        ["claude", "--print", "--output-format", "json", "--model", "claude-sonnet-4-6"],
        cwd=str(work_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "CLAUDE_CODE_WORK_DIR": str(work_dir)},
    )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        elapsed = time.time() - start_time

        result = {
            "route_id": route_id,
            "manifest_path": str(manifest_path),
            "work_dir": str(work_dir),
            "status": "success" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "stderr": stderr.decode("utf-8", errors="replace")[:1000] if stderr else "",
        }

        # 尝试读取 round_result.json
        round_result_path = work_dir / "round_result.json"
        if round_result_path.exists():
            result["round_result"] = json.loads(round_result_path.read_text())

        return result

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        elapsed = time.time() - start_time
        return {
            "route_id": route_id,
            "manifest_path": str(manifest_path),
            "work_dir": str(work_dir),
            "status": "timeout",
            "elapsed_seconds": round(elapsed, 1),
            "error": f"Route exceeded timeout of {timeout}s",
            "pid": proc.pid,
        }


def run_single_route(manifest_path: str, timeout: int) -> dict:
    """启动单个 route 子 CLI 并等待其完成。"""
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.exists():
        return {"route_id": None, "manifest_path": str(manifest_path), "status": "error", "error": "manifest not found"}

    route_id, work_dir = _prepare_route_workspace(manifest_path)
    try:
        return _run_route_subprocess(route_id, manifest_path, work_dir, timeout)
    except Exception as exc:
        return {
            "route_id": route_id,
            "manifest_path": str(manifest_path),
            "work_dir": str(work_dir),
            "status": "error",
            "error": str(exc),
        }


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    manifests = [Path(m).resolve() for m in args.manifests]
    if not manifests:
        logger.error("Error: No manifests provided")
        sys.exit(1)

    logger.info(
        "[dispatch_parallel] Starting %d routes in parallel (timeout=%ds)",
        len(manifests), args.timeout,
    )

    results = {}
    with ThreadPoolExecutor(max_workers=len(manifests)) as executor:
        futures = {executor.submit(run_single_route, str(m), args.timeout): str(m) for m in manifests}
        for future in as_completed(futures):
            result = future.result()
            manifest = futures[future]
            route_id = result.get("route_id", "unknown")
            status = result.get("status", "error")
            results[route_id] = result
            logger.info("  [%s] %s", route_id, status)

    # 写入结果
    output_path = Path(args.output) if args.output else Path(manifests[0]).parent.parent / "parallel_result.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))

    success_count = sum(1 for r in results.values() if r["status"] == "success")
    logger.info("[dispatch_parallel] Done: %d/%d routes succeeded", success_count, len(manifests))
    logger.info("  Result written to: %s", output_path)


if __name__ == "__main__":
    main()
