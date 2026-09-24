#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""Reconstruct the Ascend C compilation pipeline state from a build directory."""

import configparser
import glob
import logging
import os
import sys
from pathlib import Path

from common import (
    DTYPE_TO_MACRO,
    DTYPE_TO_ORIG,
    GE_DTYPE_ENUM,
    GE_FORMAT_ENUM,
    find_build_dir,
    find_work_dirs,
    load_json,
)

LOG = logging.getLogger(__name__)


def status(ok, text):
    return f"  [{'✅' if ok else '❌'}] {text}"


def _print_op_info(op_type, info, compute_unit):
    input0 = info.get("input0", {})
    dtypes = input0.get("dtypes", [])
    formats = input0.get("formats", [])
    op_file = info.get("opFile", {}).get("value", "N/A")
    op_interface = info.get("opInterface", {}).get("value", "N/A")
    LOG.info("\n  Op: %s  (compute_unit=%s)", op_type, compute_unit)
    LOG.info("    opFile:      %s", op_file)
    LOG.info("    opInterface: %s", op_interface)
    LOG.info("    dtype combos: %d", len(dtypes))
    for index, (dtype, fmt) in enumerate(zip(dtypes, formats)):
        macro = DTYPE_TO_MACRO.get(dtype.strip(), "?")
        LOG.info("      [%d] %-12s / %-8s  →  -DDTYPE_X=%s", index, dtype.strip(), fmt.strip(), macro)


def inspect_ops_info(build_dir):
    LOG.info("\n" + "═" * 70)
    LOG.info("STAGE 1-3: OpDef → ops-info.json  (dtype enumeration)")
    LOG.info("═" * 70)
    json_files = sorted(glob.glob(str(build_dir / "**" / "aic-*-ops-info.json"), recursive=True))
    if not json_files:
        LOG.info(status(False, "No aic-*-ops-info.json found"))
        return {}
    ops = {}
    for json_path in json_files:
        data = load_json(json_path)
        if not data:
            continue
        compute_unit = Path(json_path).parent.name
        LOG.info("\n  📄 %s", json_path)
        for op_type, info in data.items():
            _print_op_info(op_type, info, compute_unit)
            ops[op_type] = {
                "dtypes": [item.strip() for item in info.get("input0", {}).get("dtypes", [])],
                "op_file": info.get("opFile", {}).get("value", "N/A"),
                "compute_unit": compute_unit,
                "json_path": json_path,
            }
    return ops


def _print_ini_section(section, config):
    op_type = section[65:] if len(section) > 65 else section
    kernel_file = config.get(section, "kernel_file", fallback="N/A")
    kernel_dir = config.get(section, "kernel_dir", fallback="(default)")
    compute_unit = config.get(section, "compute_unit", fallback="(all)")
    LOG.info("    op_type: %s", op_type)
    LOG.info("      kernel_file: %s", kernel_file)
    LOG.info("      kernel_dir:  %s", kernel_dir)
    LOG.info("      compute_unit: %s", compute_unit)


def inspect_source_ini(build_dir):
    LOG.info("\n" + "═" * 70)
    LOG.info("STAGE 2: source_files.ini  (kernel source mapping)")
    LOG.info("═" * 70)
    ini_files = sorted(glob.glob(str(build_dir / "**" / "*_source_files.ini"), recursive=True))
    if not ini_files:
        LOG.info(status(False, "No *_source_files.ini found"))
        return
    for ini_path in ini_files:
        LOG.info("\n  📄 %s", ini_path)
        config = configparser.ConfigParser()
        config.read(ini_path)
        for section in config.sections():
            _print_ini_section(section, config)


def _print_param_file(path, node):
    inputs = node.get("inputs", [])
    dtype = inputs[0].get("dtype", "?") if inputs else "?"
    fmt = inputs[0].get("format", "?") if inputs else "?"
    macro = DTYPE_TO_MACRO.get(dtype, "?")
    orig = DTYPE_TO_ORIG.get(dtype, "?")
    bin_filename = node.get("bin_filename", "N/A")
    LOG.info("\n    📄 %s", Path(path).name)
    LOG.info("      bin_filename: %s", bin_filename)
    LOG.info("      dtype: %s  format: %s", dtype, fmt)
    LOG.info("      → will inject: -DDTYPE_X=%s  -DORIG_DTYPE_X=%s", macro, orig)
    return {"bin_filename": bin_filename, "dtype": dtype, "path": path}


def inspect_compile_params(build_dir):
    LOG.info("\n" + "═" * 70)
    LOG.info("STAGE 4: _param.json × N  (dtype-specific compile params)")
    LOG.info("═" * 70)
    param_files = sorted(glob.glob(str(build_dir / "**" / "*_param.json"), recursive=True))
    if not param_files:
        LOG.info("  (No _param.json found — build may have completed & cleaned temp files)")
        LOG.info("  → dtype info is still recoverable from per-kernel .json files (see Stage 5)")
        return []
    LOG.info("\n  Found %d _param.json file(s):", len(param_files))
    params = []
    for param_path in param_files:
        data = load_json(param_path)
        if not data:
            continue
        for node in data.get("op_list", []):
            params.append(_print_param_file(param_path, node))
    return params


def _print_binary(binary_path):
    json_path = str(binary_path).replace(".o", ".json")
    data = load_json(json_path)
    if not data:
        LOG.info("\n    ⚠️  %s  (no .json — incomplete compilation)", Path(binary_path).name)
        return None
    support_info = data.get("supportInfo", {})
    inputs = support_info.get("inputs", [])
    dtype = inputs[0].get("dtype", "?") if inputs else "?"
    kernel_list = data.get("kernelList", [])
    LOG.info("\n    📦 %s", Path(binary_path).name)
    LOG.info("      dtype:       %s", dtype)
    LOG.info("      core_type:   %s", data.get("core_type", "?"))
    LOG.info("      opParaSize:  %s bytes", data.get("opParaSize", "?"))
    LOG.info("      sub-kernels: %d   ← 应等于 ASCENDC_TPL_SEL 行数（内层枚举）", len(kernel_list))
    for kernel in kernel_list:
        LOG.info("        - %s", kernel["kernelName"])
    return {
        "path": str(binary_path),
        "json_path": json_path,
        "dtype": dtype,
        "bin_name": data.get("binFileName", Path(binary_path).stem),
        "sub_kernels": [kernel["kernelName"] for kernel in kernel_list],
    }


def inspect_kernel_binaries(build_dir, ops_info):
    LOG.info("\n" + "═" * 70)
    LOG.info("STAGE 5: Kernel binaries  (.o files + per-kernel .json)")
    LOG.info("═" * 70)
    o_files = sorted(glob.glob(str(build_dir / "**" / "binary" / "**" / "*.o"), recursive=True))
    o_files = [path for path in o_files if "_CPack_Packages" not in path]
    expected = sum(len(value["dtypes"]) for value in ops_info.values()) if ops_info else "?"
    LOG.info("\n  .o files found: %d  (expected: %s)", len(o_files), expected)
    if isinstance(expected, int) and len(o_files) < expected:
        LOG.info(status(False, f"{expected - len(o_files)} .o file(s) MISSING — some dtype compilations failed!"))
    elif o_files:
        LOG.info(status(True, f"All {len(o_files)} .o file(s) present"))
    return [entry for path in o_files if (entry := _print_binary(path)) is not None]


def _decode_key(key):
    if not key or "/" not in key:
        return ""
    parts = key.split("/")
    if len(parts) < 3:
        return ""
    decoded = []
    for input_part in parts[2:]:
        if "," not in input_part:
            continue
        dtype, fmt = input_part.split(",")[:2]
        try:
            dtype_name = GE_DTYPE_ENUM.get(int(dtype), f"enum={dtype}")
            format_name = GE_FORMAT_ENUM.get(int(fmt), f"enum={fmt}")
            decoded.append(f"{dtype_name}/{format_name}")
        except ValueError:
            continue
    return " | ".join(decoded)


def _print_route_entry(entry, index):
    bin_path = entry.get("binPath", "N/A")
    keys = entry.get("simplifiedKey", [])
    decoded = _decode_key(keys[0] if keys else "")
    LOG.info("    [%d] .o: %s", index, Path(bin_path).name)
    LOG.info("        coreType: %s", entry.get("coreType", "?"))
    if decoded:
        LOG.info("        dtype: %s", decoded)
    LOG.info("        simplifiedKeys (%d):", len(keys))
    for key in keys:
        detail = _decode_key(key)
        LOG.info("          %s%s", key, f"  → {detail}" if detail else "")


def inspect_routing_table(build_dir):
    LOG.info("\n" + "═" * 70)
    LOG.info("STAGE 5: binary_info_config.json  (runtime dispatch routing)")
    LOG.info("═" * 70)
    pattern = str(build_dir / "**" / "binary_info_config.json")
    config_files = [path for path in sorted(glob.glob(pattern, recursive=True)) if "_CPack_Packages" not in path]
    if not config_files:
        LOG.info(status(False, "No binary_info_config.json found"))
        return
    for config_path in config_files:
        data = load_json(config_path)
        if not data:
            continue
        LOG.info("\n  📄 %s", config_path)
        for op_type, info in data.items():
            binary_list = info.get("binaryList", [])
            LOG.info("\n  Op: %s  (%d binary variant(s))", op_type, len(binary_list))
            for index, entry in enumerate(binary_list):
                _print_route_entry(entry, index)


def _print_compile_script(script_path):
    def _asc_opc_line():
        with open(script_path, encoding="utf-8", errors="replace") as handle:
            return next((line for line in handle if "asc_opc" in line), "")

    try:
        command_line = _asc_opc_line()
    except OSError as exc:
        LOG.warning("无法读取编译脚本 %s: %s", script_path, exc)
        return
    if not command_line:
        return
    LOG.info("        cmd: %s...", command_line.strip()[:120])


def _print_work_dir(work_dir):
    LOG.info("\n  📁 %s", work_dir)
    py_files = glob.glob(os.path.join(work_dir, "dynamic", "*.py"))
    if py_files:
        for py_path in py_files:
            LOG.info("    📄 %s (codegen'd Python impl)", Path(py_path).name)
    else:
        LOG.info("    (no codegen'd .py found)")
    param_dir = os.path.join(work_dir, "bin_param")
    if os.path.isdir(param_dir):
        params = glob.glob(os.path.join(param_dir, "*_param.json"))
        scripts = glob.glob(os.path.join(param_dir, "*.sh"))
        LOG.info("    📄 %d _param.json, %d .sh compile scripts", len(params), len(scripts))
        for script in sorted(scripts):
            LOG.info("      → %s", Path(script).name)
            _print_compile_script(script)
    for make_path in glob.glob(os.path.join(work_dir, "*.make")):
        LOG.info("    📄 %s (parallel make file)", Path(make_path).name)


def inspect_codegen_artifacts(build_dir):
    LOG.info("\n" + "═" * 70)
    LOG.info("CODEGEN ARTIFACTS  (working_dir with bin_param/ — kept if build failed or --save-temp-files)")
    LOG.info("═" * 70)
    work_dirs = find_work_dirs(build_dir)
    if not work_dirs:
        LOG.info("  (No working_dir found — build succeeded without --save-temp-files, or not yet run)")
        return
    for work_dir in work_dirs:
        _print_work_dir(work_dir)


def print_summary(ops_info, binaries):
    LOG.info("\n" + "═" * 70)
    LOG.info("SUMMARY")
    LOG.info("═" * 70)
    n_dtypes = sum(len(value["dtypes"]) for value in ops_info.values())
    n_o = len(binaries)
    n_subkernels = sum(len(binary["sub_kernels"]) for binary in binaries)
    LOG.info("  Op types:           %d", len(ops_info))
    LOG.info("  dtype combinations: %d   (外层枚举)", n_dtypes)
    LOG.info("  .o files found:     %d", n_o)
    LOG.info("  Total sub-kernels:  %d   (外层 × 内层)", n_subkernels)
    if n_dtypes > 0:
        if n_o == n_dtypes:
            LOG.info("\n  ✅ Pipeline status: COMPLETE (%d/%d .o files)", n_o, n_dtypes)
            LOG.info("     → 还需核对上面每个 .o 的 sub-kernel 数 = ASCENDC_TPL_SEL 行数")
        elif n_o < n_dtypes:
            LOG.info("\n  ❌ Pipeline status: INCOMPLETE (%d/%d .o files)", n_o, n_dtypes)
            LOG.info("     → %d dtype compilation(s) FAILED", n_dtypes - n_o)
            LOG.info("     → Check build log for asc_opc errors")
        else:
            LOG.info("\n  ⚠️  Pipeline status: UNEXPECTED (%d > %d expected)", n_o, n_dtypes)
    else:
        LOG.info("\n  ⚠️  Cannot determine expected .o count (no ops-info.json)")


def main():
    if len(sys.argv) < 2:
        LOG.error("Usage: python3 inspect_build.py <build_dir>")
        return 2
    build_dir = find_build_dir(sys.argv[1])
    if not build_dir:
        LOG.error("ERROR: build directory not found: %s", sys.argv[1])
        return 2
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    build_dir = Path(build_dir)
    LOG.info("═" * 70)
    LOG.info("  Ascend C Build Pipeline Inspector")
    LOG.info("═" * 70)
    LOG.info("  Build directory: %s", build_dir)
    ops_info = inspect_ops_info(build_dir)
    inspect_source_ini(build_dir)
    inspect_compile_params(build_dir)
    binaries = inspect_kernel_binaries(build_dir, ops_info)
    inspect_routing_table(build_dir)
    inspect_codegen_artifacts(build_dir)
    print_summary(ops_info, binaries)
    if not ops_info:
        return 2
    expected = sum(len(value["dtypes"]) for value in ops_info.values())
    return 1 if len(binaries) < expected else 0


if __name__ == "__main__":
    sys.exit(main())
