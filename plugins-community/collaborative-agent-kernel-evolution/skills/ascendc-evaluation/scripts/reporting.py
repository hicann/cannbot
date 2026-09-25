# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------

"""Checkpoint result collection and JSON output — multi-kernel."""

import json
import logging
import os
import platform
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional

from constants import DEFAULT_ULP_CONFIG

logger = logging.getLogger(__name__)


def make_suffix(commit_hash: Optional[str] = None) -> str:
    """Build a filename suffix from commit hash (first 8 chars) or UTC timestamp.

    Used by both checkpoint JSON naming and profiling directory naming
    to keep them in sync.
    """
    if commit_hash:
        return commit_hash[:8]
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _collect_environment() -> dict:
    """Collect device and software version information."""
    env = {}
    try:
        import torch
        env["torch_version"] = torch.__version__
    except ImportError as exc:
        logger.debug("torch not available for environment collection: %s", exc)
    try:
        import torch_npu
        env["torch_npu_version"] = torch_npu.__version__
        import torch
        env["device"] = torch.npu.get_device_name(0)
    except Exception as exc:
        logger.debug("torch_npu device info unavailable: %s", exc)
    cann = os.environ.get("ASCEND_TOOLKIT_HOME", "")
    if cann:
        env["cann_version"] = os.path.basename(cann)
    env["python_version"] = platform.python_version()
    return env


class CaseKey(NamedTuple):
    """Identifies one test case. The four fields always travel together."""

    case_id: int
    params: dict
    seed: int
    distr: str

    @classmethod
    def from_meta(cls, meta: dict) -> "CaseKey":
        return cls(meta["id"], meta["params"], meta["seed"], meta["distr"])

    def to_dict(self) -> dict:
        return {"id": self.case_id, "params": self.params,
                "seed": self.seed, "distr": self.distr}


class CheckpointCollector:
    """Collects precision + profiling results for v2 checkpoint JSON.

    Supports multiple kernels — each kernel stores its own cases and
    writes to a separate JSON file. Output filename includes commit hash
    for traceability.
    """

    def __init__(self):
        self._kernels: Dict[str, dict] = {}  # kernel_name -> section
        self._current: Optional[str] = None

    def configure(self, *, kernel: dict, tolerances: dict,
                  tensors: Optional[dict] = None,
                  params_def: Optional[dict] = None,
                  ulp: Optional[dict] = None):
        """Configure a kernel section. Can be called multiple times for different kernels."""
        name = kernel["name"]
        self._current = name
        self._kernels[name] = {
            "kernel": kernel,
            "tolerances": tolerances,
            "tensors": tensors or {},
            "params_def": params_def or {},
            "ulp": ulp or dict(DEFAULT_ULP_CONFIG),
            "cases": {},
            "note": None,
            "mode": None,
        }

    def set_note(self, note: str):
        """Set an optional note for the current kernel."""
        if self._current and self._current in self._kernels:
            self._kernels[self._current]["note"] = note

    def set_mode(self, mode: str):
        """Set the comparison mode (three-way, baseline, two-way) for the current kernel."""
        if self._current and self._current in self._kernels:
            self._kernels[self._current]["mode"] = mode

    def add_forward(self, component: str, result_dict: dict, case: CaseKey):
        """Add a forward component result to the current kernel's cases."""
        self._case_entry(case).setdefault("forward", {})[component] = result_dict

    def add_backward(self, component: str, result_dict: dict, case: CaseKey):
        """Add a backward component result to the current kernel's cases."""
        self._case_entry(case).setdefault("backward", {})[component] = result_dict

    def add_performance(self, perf_dict: dict, case: CaseKey):
        """Add performance results to the current kernel's cases.

        Args:
            perf_dict: Dict with ans/ref PerfResult dicts and speedup.
            case: Case identification fields.
        """
        self._case_entry(case)["performance"] = perf_dict

    def add_profiling(self, profiling_dict: dict, case: CaseKey, role: str = "ans"):
        """Add msprof profiling results to the current kernel's cases.

        Args:
            profiling_dict: Dict from ProfilingResult.to_dict() or summary.
            case: Case identification fields.
            role: "ans", "ref", or "speedup" — stored under profiling.{role}.
        """
        self._case_entry(case).setdefault("profiling", {})[role] = profiling_dict

    def write_json(self, output_dir: str, commit_hash: Optional[str] = None) -> List[str]:
        """Write per-kernel checkpoint JSON files. Returns list of output paths.

        Args:
            output_dir: Directory to write JSON files.
            commit_hash: Git short hash to include in filename and data.
                         If None, uses timestamp-only naming.
        """
        os.makedirs(output_dir, exist_ok=True)
        suffix = make_suffix(commit_hash)
        now = datetime.now(timezone.utc)
        env = _collect_environment()
        paths = []

        for name, section in self._kernels.items():
            if not section["cases"]:
                continue

            op_lower = name.lower()
            data: Dict[str, Any] = {
                "schema_version": 2,
                "run_id": f"run_{suffix}",
                "timestamp": now.isoformat(),
                "op_name": name,
                "environment": env,
                "kernel": section["kernel"],
                "ulp": section["ulp"],
                "params_def": section["params_def"],
                "tensors": section["tensors"],
                "tolerances": section["tolerances"],
                "cases": [
                    section["cases"][cid]
                    for cid in sorted(section["cases"].keys())
                ],
            }
            if commit_hash is not None:
                data["commit"] = commit_hash
            if section["note"] is not None:
                data["note"] = section["note"]
            if section["mode"] is not None:
                data["mode"] = section["mode"]

            filename = f"checkpoint_{op_lower}_{suffix}.json"
            path = os.path.join(output_dir, filename)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            paths.append(path)

        return paths

    def _case_entry(self, case: CaseKey) -> dict:
        """The cases dict for `case`, created on first use."""
        return self._kernels[self._current]["cases"].setdefault(case.case_id, case.to_dict())
