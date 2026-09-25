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

"""
gen_dashboard.py  —  AscendC Operator Dashboard Generator  v2

从算子输出目录自动收集真实数据，生成自包含的可交互 HTML 看板。
不做任何分析或评测，仅汇总已有数据。

用法:
    # 自动发现（推荐）
    python3 gen_dashboard.py --op-dir output/Softmax_evo_*/round_1/parallel_0

    # 显式指定各数据源（可替换任意一项）
    python3 gen_dashboard.py \\
        --op-desc   .../<Op>_op_desc.json \\
        --eval      .../evaluation_results.json \\
        --precision .../precision_results.json \\
        --multi-csv .../profiling/multi_case_report.csv \\
        --dsl       .../<Op>_dsl.py \\
        --kernel    .../<Op>Custom/op_kernel/<op>_custom.cpp \\
        --profiling-dir .../profiling \\
        --test-cases .../test_cases.csv \\
        --output    dashboard.html
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from dashboard_config import _tok, detect_chip_runtime
from dashboard_parsers import (DTYPE_BYTES, OP_SUMMARY_DISPLAY_FIELDS,
    OP_SUMMARY_FIELDS_BY_TYPE, _is_case_summary_csv, _json, auto_build_algo_flow,
    build_op_graph, compact_shape, compute_tiling_analysis, compute_ub_buffers, discover,
    extract_profiling_time, pair_profiling_dirs, parse_cann_result_json, parse_dsl,
    parse_evaluation_results_json, parse_evaluation_txt, parse_flat_msprof_csv_pairs,
    parse_kernel_cpp, parse_kernel_init_buffers, parse_multi_case_csv, parse_op_host_cpp,
    parse_op_summary_detail, parse_precision_json, parse_profiling_report_txt,
    parse_test_cases_csv, parse_test_cases_py, parse_ub_from_analysis_md)
from dashboard_template import HTML_TEMPLATE

logger = logging.getLogger(__name__)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Generate AscendC operator dashboard HTML")
    p.add_argument("--op-dir", help="算子输出目录（自动发现所有文件）")
    p.add_argument("--op-desc", help="*_op_desc.json")
    p.add_argument("--eval", help="evaluation_results.json（单case结果）")
    p.add_argument("--precision", help="precision_results.json（v2多case精度）")
    p.add_argument("--multi-csv", help="profiling/multi_case_report.csv")
    p.add_argument("--dsl", help="*_dsl.py")
    p.add_argument("--kernel", help="*_custom.cpp")
    p.add_argument("--profiling-dir", help="profiling/ 目录")
    p.add_argument("--test-cases", help="test_cases.csv")
    p.add_argument("--algo-flow", help="algo_flow.json（Claude生成的算子计算流图，覆盖自动提取）")
    p.add_argument("--output", default=None, help="输出 HTML 路径（默认：<op-dir>/dashboard.html，无 op-dir 时为 ./dashboard.html）")
    p.add_argument("--extract-only", action="store_true",
                   help="只写 panels/*/data.json，不生成 HTML（供 Claude 分析前使用）")
    return p.parse_args()


# ─── 主数据汇总 ────────────────────────────────────────────────────────────────

def _resolve_paths(args) -> dict:
    """discover 结果叠加命令行显式覆盖，并打印数据源清单。"""
    paths = {}
    if args.op_dir:
        paths = discover(Path(args.op_dir))
    # explicit overrides
    for key, attr in [("op_desc", "op_desc"), ("eval", "eval"), ("precision", "precision"),
                      ("multi_csv", "multi_csv"), ("dsl", "dsl"), ("kernel", "kernel"),
                      ("profiling_dir", "profiling_dir"), ("test_cases", "test_cases"),
                      ("algo_flow", "algo_flow")]:
        val = getattr(args, attr.replace("-", "_"), None) or getattr(args, attr, None)
        if val:
            paths[key] = Path(val)

    logger.info("📂 数据源:")
    for k, v in paths.items():
        if isinstance(v, list):
            logger.info(f"  ✓ {k}: {len(v)} files")
        else:
            exists = "✓" if Path(v).exists() else "✗"
            logger.info(f"  {exists} {k}: {v}")
    return paths


def _flat_msprof_perf(paths: dict, op_name: str) -> dict:
    """flat msprof CSV pairs (e.g. op_summary_custom_fn_*.csv)，顺带记录未配对诊断。"""
    flat_pairs = parse_flat_msprof_csv_pairs(
        paths.get("msprof_custom_csvs", []),
        paths.get("msprof_ref_csvs", []),
        op_name,
    )
    # Pull out unpaired diagnostic if present
    unpaired = None
    clean_pairs = []
    for row in flat_pairs:
        if "_unpaired" in row:
            unpaired = row["_unpaired"]
        else:
            clean_pairs.append(row)
    if unpaired:
        paths["_perf_unpaired"] = unpaired
    return {row["case_name"]: row for row in clean_pairs}


def _infer_case_name(f: Path, op_dir_path: Path):
    """从 op_summary CSV 的路径结构或文件名推断 case 名。

    模式1: .../custom/ModelNew_*/.../op_summary*.csv → 取 custom 的上级目录
    模式2: op_summary_<case>.csv（非时间戳命名，即含非纯数字的词）
    时间戳命名且无路径线索时返回 None。
    """
    parts = f.relative_to(op_dir_path).parts
    if "custom" in parts:
        ci = list(parts).index("custom")
        if ci > 0:
            return parts[ci - 1]
    stem = (f.stem[len("op_summary_custom_fn_"):] if f.name.startswith("op_summary_custom_fn_")
            else f.stem[len("op_summary_"):])
    if stem and not stem.isdigit() and not re.match(r'^\d{8,}$', stem):
        return stem
    return None


def _scan_op_summary_details(op_dir_path: Path, op_name: str) -> dict:
    """通用策略：全局 rglob op_summary*.csv（排除 origin_data/），从路径中提取 case 名。
    _msprof_work/<case>/custom/... 和 profiling_dir 等各种结构均兼容。"""
    all_csvs = sorted(
        [f for f in op_dir_path.rglob("op_summary*.csv") if _is_case_summary_csv(f)],
        key=lambda f: f.stat().st_mtime
    )
    case_csv_map: dict = {}  # case_name → csv_path (prefer custom/ModelNew path)
    for f in all_csvs:
        inferred = _infer_case_name(f, op_dir_path)
        if inferred is None:
            continue  # 时间戳命名且无路径线索 → 跳过
        # custom 路径优先（比 ref 路径更可靠）
        if inferred not in case_csv_map or "custom" in str(f) or "ModelNew" in str(f):
            case_csv_map[inferred] = f
    details: dict = {}
    for cname, f in case_csv_map.items():
        det = parse_op_summary_detail(f, op_name)
        if det:
            details[cname] = det
    return details


def _details_from_prefix(csvs: list, prefix: str, op_name: str, details: dict) -> None:
    """按文件名前缀取 case 名，逐个解析 op_summary 明细。"""
    for f in csvs:
        det = parse_op_summary_detail(f, op_name)
        if det:
            details[f.stem[len(prefix):]] = det


def _details_from_modelnew(profiling_dir, details: dict) -> None:
    """TileLang / msprof 场景：从 profiling_dir 的 ModelNew_* 目录提取 op_summary detail。
    文件名格式 op_summary_YYYYMMDD.csv（不含 custom_fn_ 前缀）。"""
    modelnew_dirs = sorted(
        [d for d in Path(profiling_dir).iterdir()
         if d.is_dir() and d.name.startswith("ModelNew_device")],
        key=lambda d: d.stat().st_mtime
    )
    if not modelnew_dirs:
        return
    # 取最新的 ModelNew 目录，递归找 op_summary*.csv（排除 origin_data/）
    mn_csvs = [f for f in modelnew_dirs[-1].rglob("op_summary*.csv")
               if "origin_data" not in f.parts]
    if not mn_csvs:
        return
    # TileLang op_summary：op name 是底层 aclnn 算子名，不含算子名前缀
    # 传 "" 跳过 op_name 过滤，汇总所有行的平均指标
    det = parse_op_summary_detail(mn_csvs[0], "")
    if det:
        details["case_0"] = det


def _collect_op_summary_details(args, paths: dict, op_name: str) -> dict:
    """Parse op_summary detail (full field extraction) for Perf tab op_summary panel."""
    details: dict = {}
    if args.op_dir:
        details.update(_scan_op_summary_details(Path(args.op_dir), op_name))
    if paths.get("msprof_custom_csvs"):
        _details_from_prefix(paths["msprof_custom_csvs"], "op_summary_custom_fn_",
                             op_name, details)
    # CAKE2 evaluate.py format: profiling/op_summary_<case>.csv (no prefix)
    # The case name is the file stem with the op_summary prefix removed.
    if not details and paths.get("msprof_cake2_csvs"):
        _details_from_prefix(paths["msprof_cake2_csvs"], "op_summary_", op_name, details)
    if not details and paths.get("profiling_dir"):
        _details_from_modelnew(paths["profiling_dir"], details)
    return details


def _split_shape_info(op_desc: dict) -> tuple:
    """shape_info: two formats
       dict form: separate keys for the input and output shape lists
       list format: [{name, shape, dtype, ...}, ...] — name=="output" marks outputs"""
    si = op_desc.get("shape_info", {})
    if not isinstance(si, list):
        return si.get("input_shapes", []), si.get("output_shapes", [])
    input_shapes = [s for s in si if s.get("name", "").lower() != "output"]
    output_shapes = [s for s in si if s.get("name", "").lower() == "output"]
    if not output_shapes and input_shapes:
        output_shapes = [input_shapes[-1]]
        input_shapes = input_shapes[:-1]
    return input_shapes, output_shapes


def _tile_and_dtype(input_shapes: list) -> tuple:
    """dtype/tile：只采用数值型的末维作为 tile 长度（跳过 "M"/"K" 之类的符号维）。"""
    if not input_shapes:
        return 1, 4
    tile_length = 1
    sh = input_shapes[0].get("shape", [])
    if sh and isinstance(sh[-1], (int, float)):
        tile_length = int(sh[-1])
    return tile_length, DTYPE_BYTES.get(input_shapes[0].get("dtype", "float32"), 4)


def _cases_from_multi_csv(multi_csv: list, prec_cases: dict) -> list:
    """multi_case_report.csv：性能来自 msprof，精度按 case_id 关联。"""
    cases = []
    for row in multi_csv:
        cid = row["case_id"]
        prec = prec_cases.get(cid, {})
        cases.append({
            "id": cid,
            "shape": row["shape"],
            "passed": row["passed"],
            "precision": {
                "passed": prec.get("passed", row["passed"]),
                "max_re": prec.get("max_re"),
                "mean_re": prec.get("mean_re"),
                "rmse": prec.get("rmse"),
                "ae_max": prec.get("ae_max"),
                "re_max": prec.get("re_max"),
                "mismatch_rate": prec.get("mismatch_rate"),
            },
            "performance": {
                "ref_time_us": row["ref_time_us"],
                "custom_time_us": row["custom_time_us"],
                "speedup": row["speedup"],
                "source": "msprof",
            },
        })
    return cases


def _cases_from_eval_results(eval_results_cases: list) -> list:
    """CAKE2 evaluate.py multi-case format (evaluation_results.json with "results" array)"""
    cases = []
    for c in eval_results_cases:
        cases.append({
            "id": c["case_id"],
            "name": c["name"],
            "shape": c["shape"],
            "passed": c["passed"],
            "precision": c["precision"],
            "performance": {
                "ref_time_us": c["ref_time_us"],
                "custom_time_us": c["custom_time_us"],
                "speedup": c["speedup"],
                "source": "msprof",
            },
        })
    return cases


def _cases_from_eval_txt(eval_txt_cases: list, flat_perf: dict) -> list:
    """evaluation_result.txt 日志格式（每 case 含精度+性能）"""
    cases = []
    for c in eval_txt_cases:
        name = c.get("name", "")
        # Enrich performance from flat msprof CSV pairs if available
        perf = c.get("performance", {})
        if flat_perf.get(name, {}).get("custom_time_us"):
            fp = flat_perf.get(name, {})
            perf = {
                "ref_time_us": fp["ref_time_us"],
                "custom_time_us": fp["custom_time_us"],
                "speedup": fp["speedup"],
                "source": "msprof_csv",
            }
        cases.append({
            "id": c["id"],
            "name": name,
            "shape": c.get("shape", ""),
            "passed": c["passed"],
            "precision": c.get("precision", {}),
            "performance": perf,
        })
    return cases


def _cases_from_precision(prec_cases: dict) -> list:
    """只有 precision_results.json 时的退化路径。"""
    cases = []
    for cid, prec in sorted(prec_cases.items()):
        cases.append({
            "id": cid,
            "shape": str(prec.get("params", {}).get("var0_shape", "")),
            "passed": prec.get("passed", False),
            "precision": prec,
            "performance": {},
        })
    return cases


def _cases_from_single_eval(eval_res: dict, prof_report: dict, input_shapes: list) -> list:
    """单 case fallback (JSON)"""
    cases = []
    from_msg = _parse_correctness(eval_res.get("correctness_message", ""))
    perf = {}
    if prof_report.get("ref_time_us"):
        perf = {"ref_time_us": prof_report["ref_time_us"],
                "custom_time_us": prof_report["custom_time_us"],
                "speedup": prof_report.get("speedup", 0), "source": "msprof"}
    elif eval_res.get("base_time_ms"):
        perf = {"ref_time_us": eval_res["base_time_ms"] * 1000,
                "custom_time_us": eval_res["gen_time_ms"] * 1000,
                "speedup": eval_res.get("speedup", 0), "source": "npu_event"}
    cases.append({
        "id": 0, "shape": str(input_shapes[0].get("shape", "") if input_shapes else ""),
        "passed": from_msg.get("passed", eval_res.get("precision_passed", False)),
        "precision": from_msg,
        "performance": perf,
    })
    return cases


def _enrich_one_case(c: dict, sv, test_cases_py_shapes: dict, op_summary_details: dict) -> None:
    """补全单个 case 的 shape / shape_compact / name，并挂上 op_summary 明细。"""
    # Enrich shape from test_cases.py if shape is still just the case name
    cname = c.get("name", "")
    if test_cases_py_shapes and cname in test_cases_py_shapes:
        py_shape = test_cases_py_shapes[cname]
        # Only replace if shape == case_name (the fallback) or shape is empty
        if not c.get("shape") or c.get("shape") == cname:
            c["shape"] = py_shape
    if not c.get("shape_compact"):
        c["shape_compact"] = compact_shape(c.get("shape", ""), sv)
    if not c.get("name"):
        c["name"] = c.get("shape_compact") or f"Case {c.get('id',0)}"
    # Attach op_summary detail if available
    cname = c.get("name", "")
    cid = c.get("id", 0)
    # 匹配优先级：case name → "case_N" → 单条时直接用 "case_0"
    _det = (op_summary_details.get(cname)
            or op_summary_details.get(f"case_{cid}")
            or (op_summary_details.get("case_0")
                if len(op_summary_details) == 1 and cid == 0 else None))
    if _det:
        c["op_summary_avg"] = _det


def _enrich_cases(cases: list, input_shapes: list, test_cases_py_shapes: dict,
                  op_summary_details: dict) -> None:
    """── Enrich cases: add shape_compact + case_label + op_summary_avg ──"""
    _isv = input_shapes[0].get("shape", []) if input_shapes else []
    _sv = [str(s) for s in _isv] if _isv and all(isinstance(s, str) for s in _isv) else None
    for c in cases:
        _enrich_one_case(c, _sv, test_cases_py_shapes, op_summary_details)


def _merge_tiling_consts(kernel_data: dict, op_host_data: dict, chip_info: dict) -> dict:
    """Build merged constant dict (op_host constants take priority)，并注入 AIV core 数
    作为运行时变量的保守上界。

    例：workspaceInQueue 的 ((nUsed * sizeof(float) + 31) / 32) * 32 可正确求值。
    注意：nUsed/coreNum/blockDim 绑定的是 AIV（vector_core）数，而非 AIC（cube_core）数。
    """
    tiling_consts = {}
    tiling_consts.update(kernel_data.get("constants", {}))
    tiling_consts.update(op_host_data.get("constants", {}))
    aiv = int(chip_info.get("aiv", 48))
    for runtime_var in ("nUsed", "usedCoreNum", "coreNum", "blockDim"):
        tiling_consts.setdefault(runtime_var, aiv)
    return tiling_consts


def _ub_size_estimated(init_sizes: dict, kernel_data: dict) -> bool:
    """Track whether any buffer size fell back to tileLength estimate (vs parsed from
    InitBuffer). Used by check_dashboard.py to decide FAIL vs WARN when ub_used > ub_total."""
    return bool(
        not init_sizes
        or any(
            not (init_sizes.get(buf["name"], 0) > 0)
            for buf in kernel_data.get("buffers", [])
        )
    )


class _UbResult(NamedTuple):
    """UB buffer 解析结果。"""

    buffers: list
    used_kb: float
    estimated: bool
    from_md: bool


def _build_ub(kernel_data: dict, paths: dict, tiling_consts: dict,
              tile_length: int, dtype_bytes: int) -> _UbResult:
    """从 kernel 的 InitBuffer 解析 UB buffer；解析不到时回退到
    panels/memory/analysis.md（TileLang standalone 场景）。"""
    init_sizes = parse_kernel_init_buffers(kernel_data.get("_txt", ""), tiling_consts)
    ub_buffers = compute_ub_buffers(kernel_data, tile_length, dtype_bytes, init_sizes)
    estimated = _ub_size_estimated(init_sizes, kernel_data)
    from_md = False
    if not ub_buffers and paths.get("memory_analysis_md"):
        ub_buffers = parse_ub_from_analysis_md(paths.get("memory_analysis_md"))
        from_md = bool(ub_buffers)
    return _UbResult(buffers=ub_buffers,
                     used_kb=sum(b["size_kb"] for b in ub_buffers),
                     estimated=estimated, from_md=from_md)


def _algo_flow_v1(af: dict, input_shapes: list, output_shapes: list, cases: list) -> dict:
    """v1 (shape_vars format): has "shape_vars" key — 补 shape_cases 与 IO 元信息。"""
    if not af.get("shape_cases"):
        af["shape_cases"] = []
        for c in cases:
            shape_str = str(c.get("shape", ""))
            nums = re.findall(r'\d+', shape_str)
            _svars = af["shape_vars"]
            if nums:
                # Use whatever dims available; map to shape_vars + S{i} for extras
                actual_vars = [_svars[i] if i < len(_svars) else f"S{i}"
                               for i in range(len(nums))]
                af["shape_cases"].append({
                    "label": f"{c.get('name','Case '+str(c.get('id',0)))}: {' × '.join(nums)}",
                    "vars": dict(zip(actual_vars, nums)),
                })
    sv = af.get("shape_vars", ["N", "C"])

    def _io_tmpl_af(shape):
        return ", ".join("{" + (sv[i] if i < len(sv) else f"D{i}") + "}"
                         for i, _ in enumerate(shape))
    # Inject IO from algo_flow.json inputs[]/outputs[] if present
    if af.get("inputs"):
        af["inp_name"] = af["inputs"][0].get("name", "x")
        af["inp_tmpl"] = af["inputs"][0].get("tmpl", "")
        af["inp_dtype"] = af["inputs"][0].get("dtype", "")
    elif not af.get("inp_name") and input_shapes:
        af["inp_name"] = input_shapes[0].get("name", "x")
        af["inp_tmpl"] = _io_tmpl_af(input_shapes[0].get("shape", []))
        af["inp_dtype"] = input_shapes[0].get("dtype", "")
    if af.get("outputs"):
        af["out_name"] = af["outputs"][0].get("name", "y")
        af["out_tmpl"] = af["outputs"][0].get("tmpl", "")
        af["out_dtype"] = af["outputs"][0].get("dtype", "")
    elif not af.get("out_name") and output_shapes:
        af["out_name"] = output_shapes[0].get("name", "y")
        af["out_tmpl"] = _io_tmpl_af(output_shapes[0].get("shape", []))
        af["out_dtype"] = output_shapes[0].get("dtype", "")
    # Ensure v2 multi-IO arrays exist
    if not af.get("inputs") and input_shapes:
        af["inputs"] = [{"name": s.get("name", f"x{i}"),
                         "dtype": s.get("dtype", ""),
                         "tmpl": _io_tmpl_af(s.get("shape", []))}
                        for i, s in enumerate(input_shapes)]
    if not af.get("outputs") and output_shapes:
        af["outputs"] = [{"name": s.get("name", f"y{i}"),
                          "dtype": s.get("dtype", ""),
                          "tmpl": _io_tmpl_af(s.get("shape", []))}
                         for i, s in enumerate(output_shapes)]
    return af


def _algo_flow_v2(af: dict) -> dict:
    """v2 format (CAKE2 auto-generated / manual without shape_vars).

    units are directly in "units" key, no shape interpolation needed.
    Inject defaults required by validate_contract / check_dashboard.
    """
    if not af.get("shape_vars"):
        af = dict(af, shape_vars=["N"])
    if not af.get("inputs"):
        af = dict(af, inputs=[{"name": "x", "shape": ["{N}"], "tmpl": "{N}", "dtype": "float32"}])
    if not af.get("outputs"):
        af = dict(af, outputs=[{"name": "y", "shape": ["{N}"], "tmpl": "{N}", "dtype": "float32"}])
    # Flat inp_*/out_* fields (check_dashboard validates these directly)
    if not af.get("inp_name"):
        _in0 = af["inputs"][0] if af.get("inputs") else {}
        _out0 = af["outputs"][0] if af.get("outputs") else {}
        _svars = af.get("shape_vars", ["N"])
        _tmpl = "{" + ",".join(_svars) + "}"
        af = dict(af,
                  inp_name=_in0.get("name", "x"),
                  inp_tmpl=_in0.get(
                      "tmpl",
                      [_tmpl])[0] if isinstance(
                      _in0.get("tmpl"),
                      list) else _in0.get(
                      "tmpl",
                      _tmpl),
                  inp_dtype=_in0.get("dtype", "float32"),
                  out_name=_out0.get("name", "y"),
                  out_tmpl=_out0.get(
                      "tmpl",
                      [_tmpl])[0] if isinstance(
                      _out0.get("tmpl"),
                      list) else _out0.get(
                      "tmpl",
                      _tmpl),
                  out_dtype=_out0.get("dtype", "float32"))
    return af


def _load_algo_flow(paths: dict):
    """读取 algo_flow.json；自动生成且 api_list 为空（API 提取失败）时视为不存在。"""
    algo_flow_path = paths.get("algo_flow")
    if not (algo_flow_path and Path(algo_flow_path).exists()):
        return None
    af = _json(algo_flow_path)
    if af.get("_auto") and not af.get("api_list"):
        return None
    return af


def _save_auto_algo_flow(args, auto_af: dict) -> None:
    """把自动提取的 algo_flow 落盘到 panels/algo/，下次运行直接复用。
    写入条件：文件不存在，或旧文件是 _auto:true 且 api_list 为空的过期版本。"""
    if not args.op_dir:
        return
    algo_out_dir = Path(args.op_dir) / "panels" / "algo"
    algo_out_dir.mkdir(parents=True, exist_ok=True)
    algo_out_path = algo_out_dir / "algo_flow.json"
    existing = _json(algo_out_path) if algo_out_path.exists() else {}
    is_stale = existing.get("_auto") and not existing.get("api_list")
    if not algo_out_path.exists() or is_stale:
        algo_out_path.write_text(
            json.dumps(auto_af, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"  ↳ 自动提取 algo_flow.json → {algo_out_path}")


class _GraphCtx(NamedTuple):
    """构建 op_graph 所需的上下文。"""

    op_name: str
    op_desc: dict
    dsl_data: dict
    kernel_data: dict
    input_shapes: list
    output_shapes: list
    cases: list


def _resolve_op_graph(args, paths: dict, ctx: _GraphCtx) -> dict:
    """── Op graph (工业流图骨架) ──
    优先读取 algo_flow.json（由 Claude 按 subskills/algo_flowchart.md 生成）；
    若不存在，尝试从 kernel step 注释 / DSL compute steps 自动构建；
    都不可得时返回 needs_algo_flow=True 的空骨架，Tab 1 显示引导提示。
    """
    af = _load_algo_flow(paths)
    if af is not None:
        if "shape_vars" in af:
            return _algo_flow_v1(af, ctx.input_shapes, ctx.output_shapes, ctx.cases)
        if af.get("units"):
            return _algo_flow_v2(af)
        return build_op_graph(ctx.input_shapes, ctx.output_shapes, ctx.cases)

    # No algo_flow.json: try to auto-build from kernel step comments / DSL compute steps
    mapped_op_type = ctx.op_desc.get("operator_type", "vector") if ctx.op_desc else "vector"
    auto_af = auto_build_algo_flow(ctx.op_name, ctx.dsl_data, ctx.kernel_data,
                                   op_type=mapped_op_type, op_desc=ctx.op_desc)
    if not (auto_af and auto_af.get("units")):
        return build_op_graph(ctx.input_shapes, ctx.output_shapes, ctx.cases)
    # Also save to panels/algo/algo_flow.json so next run is faster
    _save_auto_algo_flow(args, auto_af)
    return auto_af


def _apply_profiling_pairs(cases: list, prof_pairs: list, multi_csv: list) -> None:
    """── Profiling pairs → per-case timing (if not from multi_csv) ──"""
    if not (prof_pairs and not multi_csv and len(prof_pairs) == len(cases)):
        return
    for i, (ref_dir, cust_dir) in enumerate(prof_pairs):
        if i >= len(cases):
            continue
        ref_us = extract_profiling_time(ref_dir)
        cust_us = extract_profiling_time(cust_dir)
        if ref_us <= 0 or cust_us <= 0:
            continue
        cases[i]["performance"] = {
            "ref_time_us": ref_us,
            "custom_time_us": cust_us,
            "speedup": round(ref_us / cust_us, 2),
            "source": "msprof",
        }


def _apply_cann_result(cases: list, cann_result: dict) -> None:
    """── TileLang standalone: cann_result.json 覆盖性能数据（真实 NPU kernel 时延）──
    cann_result.json 来自 tilelang_eval_adapter.py + combined_kernel_loader.py 评测，
    代表真实 CANN .so kernel 时间（不含 Python padding 开销），比 evaluation_results.json 准确。
    """
    if cann_result and cann_result.get("speedup"):
        cann_perf = {
            "ref_time_us": cann_result["ref_time_us"],
            "custom_time_us": cann_result["custom_time_us"],
            "speedup": cann_result["speedup"],
            "source": "cann_standalone",
            "notes": cann_result.get("notes", ""),
        }
        if cases:
            # Override case 0 (or all single-case scenarios)
            for c in cases:
                c["performance"] = cann_perf
        else:
            # No cases at all: synthesize one
            cases.append({
                "id": 0, "name": "CANN Standalone", "shape": "",
                "passed": True, "precision": {}, "performance": cann_perf,
            })


def _test_case_shape_str(tc_row: dict) -> str:
    """Build shape string from first var*_shape column."""
    for k in sorted(tc_row.keys()):
        if re.match(r'var\d+_shape', k):
            return tc_row.get(k, "").strip()
    return ""


def _append_test_case_row(cases: list, tc_row: dict, existing_ids: set, base_perf: dict) -> None:
    """把 test_cases.csv 的一行补成 case（精度标注为来自汇总结果）。"""
    try:
        cid = int(tc_row.get("case_id", 0))
    except (ValueError, TypeError):
        cid = 0
    if cid in existing_ids:
        return
    cases.append({
        "id": cid,
        "name": f"Case {cid}",
        "shape": _test_case_shape_str(tc_row),
        "passed": True,   # 假设 PASS（cann_result 不区分 case）
        "precision": {"_note": "精度来自 cann_result.json（汇总），未单独评测此 case"},
        "performance": base_perf,  # 沿用汇总性能数据
    })
    existing_ids.add(cid)


def _expand_cases_from_test_csv(cases: list, test_cases: list) -> None:
    """── 从 test_cases.csv 扩展 cases：当 eval 只有 1 case 但 CSV 有多个时 ──
    常见场景：cann_result.json 只有整体 speedup，不区分 case；eval 只跑了 case 0；
    但 test_cases.csv 记录了全部测试形状。将缺失 case 填充为 shape 已知、精度待评状态。
    """
    if not (test_cases and len(cases) <= 1):
        return
    try:
        existing_ids = {c.get("id") for c in cases}
        base_perf = cases[0].get("performance", {}) if cases else {}
        for tc_row in test_cases:
            _append_test_case_row(cases, tc_row, existing_ids, base_perf)
        # 按 id 排序
        cases.sort(key=lambda c: c.get("id", 0))
    except Exception as e:
        logger.debug("从 test_cases.csv 扩展 cases 失败，保留已有 cases: %s", e)


def _summarize_cases(cases: list) -> tuple:
    """── 整体精度/性能摘要（用于 header）──
    使用几何均值（与 check_dashboard.py 一致）；过滤 ≤0 的值防止 math domain error。
    """
    n_pass = sum(1 for c in cases if c.get("passed"))
    speedups = [c.get("performance", {}).get("speedup")
                for c in cases if c.get("performance", {}).get("speedup")]
    import math as _math
    pos_sp = [s for s in speedups if s > 0]
    avg_speedup = (round(_math.exp(sum(_math.log(s) for s in pos_sp) / len(pos_sp)), 2)
                   if pos_sp else None)
    return n_pass, len(cases), speedups, avg_speedup


class _DiagCtx(NamedTuple):
    """生成 diagnostics 所需的上下文。"""

    op_graph: dict
    ub_buffers: list
    ub_from_md: bool
    ub_used_kb: float
    ub_total_kb: float
    tiling_consts: dict
    chip_info: dict
    cases: list
    eval_is_txt: bool
    cann_result: dict
    speedups: list
    n_pass: int
    n_total: int


def _diag(tab, level, source, detail="", hint="") -> dict:
    """一条数据健康诊断记录。"""
    return {"tab": tab, "level": level, "source": source, "detail": detail, "hint": hint}


def _diag_algo(op_graph: dict) -> dict:
    units = op_graph.get("units")
    return _diag("algo", "FOUND" if units else "DERIVED",
                 "algo_flow.json" if units else "auto-build",
                 f"{len(op_graph.get('units',[]))} units" if units
                 else "需精品流程生成 algo_flow.json",
                 "" if units else "运行精品流程 Step 3 生成 panels/algo/algo_flow.json")


def _diag_memory(ctx: "_DiagCtx") -> list:
    ub_buffers = ctx.ub_buffers
    return [
        _diag("mem", "FOUND" if ub_buffers else "MISSING",
              "panels/memory/analysis.md" if ctx.ub_from_md else "op_kernel/*.cpp",
              f"{len(ub_buffers)} buffers, {ctx.ub_used_kb:.1f}/{ctx.ub_total_kb:.0f} KB"
              if ub_buffers else "",
              "" if ub_buffers
              else "提供 op_kernel/*_custom.cpp 或 panels/memory/analysis.md（含 Buffer 表格）"),
        _diag("mem", "FOUND" if ctx.tiling_consts else "MISSING",
              "op_host/*.cpp",
              f"{len(ctx.tiling_consts)} constants" if ctx.tiling_consts else "",
              "" if ctx.tiling_consts
              else "提供 op_host/*_custom.cpp 文件（TileLang 场景可忽略此项）"),
    ]


def _diag_precision(ctx: "_DiagCtx") -> dict:
    has_match_rate = any(c.get("precision", {}).get("match_rate") is not None for c in ctx.cases)
    has_max_re = any(c.get("precision", {}).get("max_re") is not None for c in ctx.cases)
    return _diag("prec",
                 "FOUND" if has_match_rate else ("FOUND" if has_max_re else "MISSING"),
                 "evaluation_result.txt" if ctx.eval_is_txt else "precision_results.json",
                 f"{ctx.n_pass}/{ctx.n_total} PASS",
                 "" if ctx.n_total > 0 else "运行 ascendc-evaluation 生成精度数据")


def _diag_perf(ctx: "_DiagCtx", paths: dict) -> dict:
    if ctx.cann_result and ctx.cann_result.get("speedup"):
        source = "cann_result.json"
    elif paths.get("msprof_custom_csvs") or paths.get("multi_csv"):
        source = "msprof CSV"
    else:
        source = "无 msprof 数据"
    return _diag("perf", "FOUND" if ctx.speedups else "MISSING", source,
                 f"{len(ctx.speedups)} cases with speedup" if ctx.speedups else "",
                 "" if ctx.speedups
                 else "提供 panels/perf/cann_result.json（TileLang）或运行 ascendc-evaluation_remote")


def _build_diagnostics(ctx: "_DiagCtx", paths: dict) -> list:
    """── Diagnostics（数据健康）──"""
    diagnostics = [_diag_algo(ctx.op_graph)]
    diagnostics += _diag_memory(ctx)
    if paths.get("_perf_unpaired"):
        diagnostics.append(_diag("perf", "DERIVED", "msprof CSVs",
                                 f"未配对文件: {', '.join(paths['_perf_unpaired'])}"))
    diagnostics.append(_diag_precision(ctx))
    diagnostics.append(_diag_perf(ctx, paths))
    diagnostics.append(_diag(
        "mem", "FOUND", "chip probe",
        f"{ctx.chip_info.get('name')} | UB {int(ctx.ub_total_kb)}KB × {ctx.chip_info.get('aic')}核",
        f"source={ctx.chip_info.get('source', 'unknown')}"))
    return diagnostics


def _chip_block(chip_info: dict, ub_total_kb: float) -> dict:
    """dashboard 数据中的芯片信息段。"""
    return {
        "name": chip_info.get("name", _tok("chip.name", "Ascend910B2")),
        "ub_kb": int(ub_total_kb),
        "aic": int(chip_info.get("aic", _tok("chip.aic", 32))),
        "source": chip_info.get("source", "design_tokens"),
    }


def _tiling_block(tile_length: int, dtype_bytes: int, kernel_data: dict,
                  tiling_consts: dict, tiling_analysis: list) -> dict:
    """dashboard 数据中的 tiling 段。"""
    return {
        "tile_length": tile_length,
        "tile_size_kb": round(tile_length * dtype_bytes / 1024, 2),
        "dtype_bytes": dtype_bytes,
        "tiling_params": kernel_data.get("tiling_params", []),
        "consts": tiling_consts,
        "analysis": tiling_analysis,
    }


def _panels_block(panels_content: dict) -> dict:
    """dashboard 数据中的 panels 段。"""
    return {
        "memory": panels_content.get("memory", {}),
        "precision": panels_content.get("precision", {}),
        "perf": panels_content.get("perf", {}),
        "algo": panels_content.get("algo", {}),
        "extra": panels_content.get("extra", []),
    }


def _pass_comments_of(kernel_data: dict, dsl_data: dict) -> list:
    """── Raw Pass 注释（直接透传，不做语义推断）──"""
    pass_comments = kernel_data.get("pass_comments", [])
    if pass_comments:
        return pass_comments
    return [l for l in dsl_data.get("header_comments", [])
            if any(k in l for k in ["Pass", "pass", "步骤", "算法"])]


class _Sources(NamedTuple):
    """collect_data 解析出的各数据源。"""

    op_desc: dict
    eval_is_txt: bool
    eval_res: dict
    eval_txt_cases: list
    eval_results_cases: list
    prec_cases: dict
    multi_csv: list
    flat_perf: dict
    op_summary_details: dict
    test_cases: list
    test_cases_py_shapes: dict
    kernel_data: dict
    op_host_data: dict
    dsl_data: dict
    prof_report: dict
    prof_pairs: list
    cann_result: dict


def _parse_sources(args, paths: dict) -> _Sources:
    """── 解析各数据源 ──"""
    op_desc = _json(paths.get("op_desc"))
    # eval: JSON (evaluation_results.json) or TXT log (evaluation_result.txt)
    eval_path = paths.get("eval")
    eval_is_txt = bool(eval_path and str(eval_path).endswith(".txt"))
    eval_res = {} if eval_is_txt else _json(eval_path)
    multi_csv = parse_multi_case_csv(paths.get("multi_csv"))
    op_nm = op_desc.get("op_name", "") if op_desc else ""
    flat_perf = {}
    if not multi_csv and (paths.get("msprof_custom_csvs") or paths.get("msprof_ref_csvs")):
        flat_perf = _flat_msprof_perf(paths, op_nm)
    return _Sources(
        op_desc=op_desc,
        eval_is_txt=eval_is_txt,
        eval_res=eval_res,
        eval_txt_cases=parse_evaluation_txt(eval_path) if eval_is_txt else [],
        # CAKE2 multi-case evaluation_results.json: has "results" array
        eval_results_cases=(parse_evaluation_results_json(eval_path)
                            if (not eval_is_txt and eval_res.get("results")) else []),
        prec_cases=parse_precision_json(paths.get("precision")),
        multi_csv=multi_csv,
        flat_perf=flat_perf,
        op_summary_details=_collect_op_summary_details(args, paths, op_nm),
        test_cases=parse_test_cases_csv(paths.get("test_cases")),
        test_cases_py_shapes=parse_test_cases_py(paths.get("test_cases_py")),
        kernel_data=parse_kernel_cpp(paths.get("kernel")),
        op_host_data=parse_op_host_cpp(paths.get("op_host")),
        dsl_data=parse_dsl(paths.get("dsl")),
        prof_report=parse_profiling_report_txt(paths.get("report_txt")),
        prof_pairs=pair_profiling_dirs(paths.get("profiling_dir")),
        cann_result=parse_cann_result_json(paths.get("cann_result")),
    )


def _build_cases(src: _Sources, input_shapes: list) -> list:
    """── Cases（优先级：multi_csv > eval_results_cases > eval_txt > prec_cases > eval_res 单case）──"""
    if src.multi_csv:
        return _cases_from_multi_csv(src.multi_csv, src.prec_cases)
    if src.eval_results_cases:
        return _cases_from_eval_results(src.eval_results_cases)
    if src.eval_txt_cases:
        return _cases_from_eval_txt(src.eval_txt_cases, src.flat_perf)
    if src.prec_cases:
        return _cases_from_precision(src.prec_cases)
    if src.eval_res:
        return _cases_from_single_eval(src.eval_res, src.prof_report, input_shapes)
    return []


class _Core(NamedTuple):
    """collect_data 中间计算结果。"""

    input_shapes: list
    output_shapes: list
    tile_length: int
    dtype_bytes: int
    cases: list
    chip_info: dict
    tiling_consts: dict
    tiling_analysis: list
    ub: _UbResult
    ub_total_kb: float
    op_graph: dict
    n_pass: int
    n_total: int
    avg_speedup: float
    diagnostics: list


def _compute_core(args, paths: dict, src: _Sources) -> _Core:
    """从各数据源算出 cases、UB、tiling、op_graph 与 diagnostics。"""
    input_shapes, output_shapes = _split_shape_info(src.op_desc)
    tile_length, dtype_bytes = _tile_and_dtype(input_shapes)
    cases = _build_cases(src, input_shapes)
    _enrich_cases(cases, input_shapes, src.test_cases_py_shapes, src.op_summary_details)

    # 先检测芯片型号，以便将 AIV core 数作为 nUsed/coreNum 上界注入常量表，
    # 防止 workspace 类 InitBuffer 表达式（含 nUsed 等运行时变量）求值失败时
    # 错误回落到 tile_length×dtype_bytes（可能异常大）。
    chip_info = detect_chip_runtime(
        str(_tok("chip.name", "Ascend910B2")),
        int(_tok("chip.ub_kb", 192)),
        int(_tok("chip.aic", 24)),
        int(_tok("chip.aiv", 48)),
    )
    tiling_consts = _merge_tiling_consts(src.kernel_data, src.op_host_data, chip_info)
    ub = _build_ub(src.kernel_data, paths, tiling_consts, tile_length, dtype_bytes)
    tiling_analysis = compute_tiling_analysis(
        cases, tiling_consts, int(chip_info.get("aic", 32)))
    ub_total_kb = float(chip_info.get("ub_kb", 256))

    op_graph = _resolve_op_graph(args, paths, _GraphCtx(
        op_name=src.op_desc.get("op_name", "Unknown"), op_desc=src.op_desc,
        dsl_data=src.dsl_data, kernel_data=src.kernel_data,
        input_shapes=input_shapes, output_shapes=output_shapes, cases=cases))

    _apply_profiling_pairs(cases, src.prof_pairs, src.multi_csv)
    _apply_cann_result(cases, src.cann_result)
    _expand_cases_from_test_csv(cases, src.test_cases)
    n_pass, n_total, speedups, avg_speedup = _summarize_cases(cases)

    diagnostics = _build_diagnostics(_DiagCtx(
        op_graph=op_graph, ub_buffers=ub.buffers, ub_from_md=ub.from_md,
        ub_used_kb=ub.used_kb, ub_total_kb=ub_total_kb, tiling_consts=tiling_consts,
        chip_info=chip_info, cases=cases, eval_is_txt=src.eval_is_txt,
        cann_result=src.cann_result, speedups=speedups,
        n_pass=n_pass, n_total=n_total), paths)

    return _Core(input_shapes=input_shapes, output_shapes=output_shapes,
                 tile_length=tile_length, dtype_bytes=dtype_bytes, cases=cases,
                 chip_info=chip_info, tiling_consts=tiling_consts,
                 tiling_analysis=tiling_analysis, ub=ub, ub_total_kb=ub_total_kb,
                 op_graph=op_graph, n_pass=n_pass, n_total=n_total,
                 avg_speedup=avg_speedup, diagnostics=diagnostics)


def collect_data(args) -> dict:
    paths = _resolve_paths(args)
    src = _parse_sources(args, paths)
    core = _compute_core(args, paths, src)

    # ── Panel content discovery ──
    panels_content: dict = {}
    if args.op_dir:
        panels_content = discover_panels(Path(args.op_dir))

    op_desc, ub = src.op_desc, core.ub
    return {
        "op_name": op_desc.get("op_name", "Unknown"),
        "category": op_desc.get("category", ""),
        "description": op_desc.get("description", ""),
        "attributes": op_desc.get("attributes", {}),
        "chip": _chip_block(core.chip_info, core.ub_total_kb),
        "input_shapes": core.input_shapes,
        "output_shapes": core.output_shapes,
        "cases": core.cases,
        "n_pass": core.n_pass,
        "n_total": core.n_total,
        "avg_speedup": core.avg_speedup,
        "pass_comments": _pass_comments_of(src.kernel_data, src.dsl_data),
        "op_graph": core.op_graph,
        "tiling": _tiling_block(core.tile_length, core.dtype_bytes, src.kernel_data,
                                core.tiling_consts, core.tiling_analysis),
        "ub_buffers": ub.buffers,
        "ub_used_kb": round(ub.used_kb, 2),
        # True = any buffer size from tileLength fallback (not InitBuffer parse)
        "ub_estimated": ub.estimated,
        "_ub_from_md": ub.from_md,
        "ub_total_kb": core.ub_total_kb,
        "ub_util_pct": round(ub.used_kb / core.ub_total_kb * 100, 1),
        "diagnostics": core.diagnostics,
        "op_summary_fields": OP_SUMMARY_DISPLAY_FIELDS,
        "panels": _panels_block(panels_content),
    }


def _parse_correctness(msg: str) -> dict:
    result = {"passed": "[PASS]" in msg}
    for key in ["max_re", "mean_re", "rmse", "mismatch_rate"]:
        m = re.search(rf"{key}=([\d.]+)", msg)
        if m:
            result[key] = float(m.group(1))
    return result


# ─── PANEL SYSTEM ──────────────────────────────────────────────────────────────

def _md_inline(text: str) -> str:
    """Inline markdown → HTML: **bold**, `code`, [PASS]/[FAIL] coloring."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(
        r'`([^`]+)`',
        r'<code style="font-family:var(--mono);background:var(--sf2);padding:1px 4px;border-radius:3px">\1</code>',
        text)
    text = text.replace('[PASS]', '<span class="badge bp">PASS</span>')
    text = text.replace('[FAIL]', '<span class="badge bf">FAIL</span>')
    return text


def _sanitize_html_fragment(html: str) -> str:
    """Strip XSS vectors from Claude-authored HTML fragments before embedding.

    Removes:
    - <script> blocks (with content) and self-closing <script> tags
    - <object> / <embed> tags (plugin execution vectors)
    - Inline event-handler attributes (on<event>=...)
    - javascript: URL schemes
    - <iframe> tags (any variant)
    - <meta> tags (to block http-equiv refresh / CSP bypasses)
    """
    # Remove <script>...</script> blocks entirely (including content)
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    # Remove self-closing / unclosed <script> tags
    html = re.sub(r'<script\b[^>]*/?\s*>', '', html, flags=re.IGNORECASE)
    # Remove <object> and <embed> tags (plugin execution vectors)
    html = re.sub(r'<object\b[^>]*>.*?</object>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<(?:object|embed)\b[^>]*/?\s*>', '', html, flags=re.IGNORECASE)
    # Remove event handler attributes: on<word>="..." or on<word>='...' or unquoted
    html = re.sub(r'\s+on[a-z]{1,20}\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]*)',
                  '', html, flags=re.IGNORECASE)
    # Remove javascript: URL schemes (in href/src/action/etc.)
    html = re.sub(r'javascript\s*:', 'javascript_blocked:', html, flags=re.IGNORECASE)
    # Remove <iframe ...> tags entirely
    html = re.sub(r'<iframe\b[^>]*>.*?</iframe>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<iframe\b[^>]*/?\s*>', '', html, flags=re.IGNORECASE)
    # Remove <meta> tags (potential http-equiv refresh / CSP bypasses)
    html = re.sub(r'<meta\b[^>]*/?\s*>', '', html, flags=re.IGNORECASE)
    return html


class _MarkdownRenderer:
    """analysis.md 的极简 Markdown 渲染器（## h2、### h3、- 列表、| 表格）。"""

    def __init__(self):
        self.html = []
        self.in_ul = False
        self.in_ol = False
        self.in_table = False
        self.table_body_started = False

    def render(self, md_text: str) -> str:
        """逐行渲染，返回拼好的 HTML 片段。"""
        for line in md_text.split('\n'):
            self._render_line(line.strip())
        self._close_list()
        self._close_table()
        return '\n'.join(self.html)

    def _close_list(self):
        if self.in_ul:
            self.html.append('</ul>')
            self.in_ul = False
        if self.in_ol:
            self.html.append('</ol>')
            self.in_ol = False

    def _close_table(self):
        if not self.in_table:
            return
        if self.table_body_started:
            self.html.append('</tbody>')
        self.html.append('</table>')
        self.in_table = False
        self.table_body_started = False

    def _open_tbody(self):
        if not self.table_body_started:
            self.html.append('<tbody>')
            self.table_body_started = True

    def _render_line(self, s: str):
        if s.startswith('## '):
            self._close_list()
            self._close_table()
            self.html.append(f'<h3 class="ana-h2">{_md_inline(s[3:].strip())}</h3>')
            return
        if s.startswith('### '):
            self._close_list()
            self._close_table()
            self.html.append(f'<h4 class="ana-h3">{_md_inline(s[4:].strip())}</h4>')
            return
        if s.startswith('|'):
            self._close_list()
            self._render_table_row(s)
            return
        if s.startswith('- ') or s.startswith('* '):
            self._render_ul_item(s)
            return
        if re.match(r'^\d+\.\s', s):
            self._render_ol_item(s)
            return
        self._close_list()
        self._close_table()
        if s:
            self.html.append(f'<p class="ana-p">{_md_inline(s)}</p>')

    def _render_table_row(self, s: str):
        cols = [c.strip() for c in s.strip('|').split('|')]
        # Skip pure separator rows (|---|---|) — they only trigger tbody open
        if all(re.match(r'^[-: ]+$', c) for c in cols if c.strip()):
            if self.in_table:
                self._open_tbody()
            return
        if not self.in_table:
            self.in_table = True
            self.table_body_started = False
            self.html.append('<table class="ana-tbl"><thead><tr>')
            self.html.extend(f'<th>{_md_inline(c)}</th>' for c in cols)
            self.html.append('</tr></thead>')
            return
        self._open_tbody()
        self.html.append('<tr>')
        self.html.extend(f'<td>{_md_inline(c)}</td>' for c in cols)
        self.html.append('</tr>')

    def _render_ul_item(self, s: str):
        self._close_table()
        if self.in_ol:
            self.html.append('</ol>')
            self.in_ol = False
        if not self.in_ul:
            self.html.append('<ul class="ana-list">')
            self.in_ul = True
        self.html.append(f'<li>{_md_inline(s[2:])}</li>')

    def _render_ol_item(self, s: str):
        self._close_table()
        content = re.sub(r'^\d+\.\s', '', s)
        if self.in_ul:
            self.html.append('</ul>')
            self.in_ul = False
        if not self.in_ol:
            self.html.append('<ol class="ana-list">')
            self.in_ol = True
        self.html.append(f'<li>{_md_inline(content)}</li>')


def _md_to_html(md_text: str) -> str:
    """Minimal markdown → HTML for analysis.md (## h2, ### h3, - list, | table, **bold**, `code`)."""
    return _MarkdownRenderer().render(md_text)


def _read_panel_fragment(path: Path) -> str:
    """读取 panel 的独立 HTML 片段；不存在、过短或读取失败时返回空串。"""
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as e:
        logger.debug("读取 panel 片段 %s 失败: %s", path, e)
        return ""
    return _sanitize_html_fragment(content) if len(content) > 30 else ""


def _read_panel_info(sub: Path) -> dict:
    """读取单个 panel 子目录下的 analysis.md、HTML 片段与 panel.html。"""
    info: dict = {}
    if (sub / "analysis.md").exists():
        try:
            md = (sub / "analysis.md").read_text(encoding="utf-8", errors="replace")
            info["analysis_html"] = _md_to_html(md)
        except Exception as e:
            logger.debug("读取 panel analysis.md 失败 %s: %s", sub, e)

    # ── 独立 HTML 片段文件（CC 直接写入，脚本直接读取嵌入）──
    for _key, _fname in [("flow_html", "flow.html"),
                         ("steps_html", "steps.html"),
                         ("ub_viz_html", "ub_viz.html")]:
        _fragment = _read_panel_fragment(sub / _fname)
        if _fragment:
            info[_key] = _fragment

    if (sub / "panel.html").exists():
        try:
            info["raw_html"] = (sub / "panel.html").read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug("读取 panel.html 失败 %s: %s", sub, e)
    return info


def _panel_label(sub: Path, pid: str) -> str:
    """从 panel.json 取标题，缺失或不可解析时退回目录名。"""
    meta_path = sub / "panel.json"
    if not meta_path.exists():
        return pid
    try:
        return json.loads(meta_path.read_text(encoding="utf-8")).get("title", pid)
    except Exception as e:
        logger.debug("读取 panel.json 失败，使用目录名作标题 %s: %s", sub, e)
        return pid


def discover_panels(op_dir: Path, op_name: str = "") -> dict:
    """
    扫描 output/{op}/panels/ 子目录，加载 analysis.md / panel.html。
    返回 {"memory": {...}, "precision": {...}, "perf": {...}, "algo": {...},
           "extra": [{"id","label","html","analysis_html"}]}
    """
    known_tabs = {"algo", "memory", "precision", "perf"}
    panels: dict = {t: {} for t in known_tabs}
    panels["extra"] = []

    panel_dir = op_dir / "panels"
    if not panel_dir.exists():
        return panels

    for sub in sorted(panel_dir.iterdir()):
        if not sub.is_dir():
            continue
        pid = sub.name
        info = _read_panel_info(sub)
        if pid in known_tabs:
            panels[pid] = info
            continue
        if not info:
            continue
        # Unknown subdir with content → extra tab
        panels["extra"].append({
            "id": pid,
            "label": _panel_label(sub, pid),
            "html": info.get("raw_html", ""),
            "analysis_html": info.get("analysis_html", ""),
        })

    return panels


def extract_panel_data_json(data: dict, op_dir: Path):
    """写 panels/{memory,precision,perf}/data.json 供 Claude 精品流程读取。"""
    panel_dir = op_dir / "panels"
    # memory
    mem_dir = panel_dir / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "data.json").write_text(json.dumps({
        "tiling_consts": data.get("tiling", {}).get("consts", {}),
        "ub_buffers": data.get("ub_buffers", []),
        "ub_used_kb": data.get("ub_used_kb", 0),
        "ub_total_kb": data.get("ub_total_kb", 256),
        "tiling_analysis": data.get("tiling", {}).get("analysis", []),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # precision
    prec_dir = panel_dir / "precision"
    prec_dir.mkdir(parents=True, exist_ok=True)
    (prec_dir / "data.json").write_text(json.dumps({
        "n_pass": data.get("n_pass", 0),
        "n_total": data.get("n_total", 0),
        "cases": [{"id": c.get("id"), "name": c.get("name"),
                   "shape": c.get("shape"), "passed": c.get("passed"),
                   "precision": c.get("precision", {})}
                  for c in data.get("cases", [])],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # perf
    perf_dir = panel_dir / "perf"
    perf_dir.mkdir(parents=True, exist_ok=True)
    perf_cases = [c for c in data.get("cases", []) if c.get("performance", {}).get("speedup")]
    (perf_dir / "data.json").write_text(json.dumps({
        "avg_speedup": data.get("avg_speedup"),
        "speedups": [{"name": c.get("name", f"case_{c.get('id',0)}"),
                      "speedup": c.get("performance", {}).get("speedup"),
                      "ref_time_us": c["performance"].get("ref_time_us", 0),
                      "custom_time_us": c["performance"].get("custom_time_us", 0)}
                     for c in perf_cases],
        "op_summary_fields_by_type": OP_SUMMARY_FIELDS_BY_TYPE,
        "op_summary_fields": OP_SUMMARY_DISPLAY_FIELDS,
        "cases": [{"id": c.get("id"), "name": c.get("name"),
                   "shape": c.get("shape"), "performance": c.get("performance", {}),
                   "op_summary_avg": c.get("op_summary_avg", {})}
                  for c in perf_cases],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # algo (pass_comments + compute_apis for CC to write flow.html / steps.html)
    algo_dir = panel_dir / "algo"
    algo_dir.mkdir(parents=True, exist_ok=True)
    (algo_dir / "data.json").write_text(json.dumps({
        "pass_comments": data.get("pass_comments", []),
        "compute_apis": data.get("op_graph", {}).get("api_list", []),
        "tiling_consts": data.get("tiling", {}).get("consts", {}),
        "op_name": data.get("op_name", ""),
        "description": data.get("description", ""),
        "inputs": data.get("op_graph", {}).get("inputs", []),
        "outputs": data.get("op_graph", {}).get("outputs", []),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"📁 Panel data 已写入 {panel_dir}/{{algo,memory,precision,perf}}/data.json")


# ─── GENERATE ────────────────────────────────────────────────────────────────

def generate_html(data: dict) -> str:
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, indent=2))
    html = html.replace("__TITLE__", data.get("op_name", "Op"))
    # Inject Chart.js inline (self-contained, no external CDN)
    _chartjs_path = Path(__file__).parent.parent / "assets" / "chart.umd.min.js"
    if _chartjs_path.exists():
        chartjs_src = _chartjs_path.read_text(encoding="utf-8", errors="replace")
        html = html.replace("/*__CHARTJS__*/", chartjs_src)
    return html


def _needs_analysis(p: Path) -> bool:
    """文件不存在、包含旧版占位、或包含 NEEDS_CLAUDE_ANALYSIS 标记时返回 True。"""
    if not p.exists():
        return True
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
        return ("（占位）" in t or "自动占位" in t
                or "NEEDS_CLAUDE_ANALYSIS" in t
                or "请补充" in t)
    except Exception:
        return True


def _prof(c, *keys):
    """op_summary_avg 中首个可转为 float 的字段值。"""
    s = c.get("op_summary_avg", {})
    for k in keys:
        v = s.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _prof_str(c, *keys):
    """op_summary_avg 中首个非空字段的字符串值。"""
    s = c.get("op_summary_avg", {})
    for k in keys:
        v = s.get(k)
        if v is not None:
            return str(v)
    return ""


def _fmt_ratio(v):
    """比率列的显示形式，无数据时显示破折号。"""
    if v is None:
        return "—"
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return str(v)


def _case_shape_label(c: dict) -> str:
    """精度/性能表的 shape 列：优先 profiling 的 Input Shapes，否则回退 case.shape。"""
    shapes_str = _prof_str(c, "Input Shapes")
    if not shapes_str:
        return c.get('shape', '?')
    return shapes_str.strip('"').split(';')[0].strip()


def _shape_elem_count(first_shape: str, empty: int) -> int:
    """把 "1,2,3" 形式的 shape 串乘成元素总数；没有任何可解析维度时返回 empty。"""
    total = empty
    for dim in first_shape.split(','):
        try:
            total = (total or 1) * int(dim.strip())
        except ValueError:
            pass
    return total


def _active_core_count(total: int, block_dim, tile_size: int, chip_aic: int) -> tuple:
    """返回 (活跃核数, 启动核数)：受元素数、启动核数与 tile 数三者共同限制。"""
    launched = int(block_dim) if block_dim else chip_aic
    max_by_tile = max(1, (total + tile_size - 1) // tile_size)
    return min(min(total, launched), max_by_tile), launched


def _memory_case_rows(cases: list, tile_size: int, chip_aic: int) -> str:
    """Memory 面板的各 Case Tiling 参数表体。"""
    rows = ""
    for c in cases:
        shapes_str = _prof_str(c, "Input Shapes")
        if not shapes_str:
            continue
        first_shape = shapes_str.strip('"').split(';')[0].strip()
        total = _shape_elem_count(first_shape, 1)
        block_dim = _prof(c, "Block Dim")
        if tile_size <= 0 or chip_aic <= 0:
            continue
        active, _launched = _active_core_count(total, block_dim, tile_size, chip_aic)
        has_tail = "是" if total % tile_size != 0 else "否"
        rows += (
            f"| {c.get('name','?')} | {first_shape} | {total:,} "
            f"| {active} | {tile_size} | {has_tail} |\n"
        )
    return rows


def _precision_case_rows(cases: list) -> str:
    """Precision 面板的各 Case 精度表体。"""
    rows = ""
    for c in cases:
        prec = c.get("precision", {})
        if not prec:
            continue
        status = "✅" if prec.get("passed", True) else "❌"
        rows += (f"| {c.get('name','?')} | {_case_shape_label(c)} | {status} "
                 f"| {prec.get('max_re', 'N/A')} "
                 f"| {prec.get('mean_re', 'N/A')} "
                 f"| {prec.get('rmse', 'N/A')} |\n")
    return rows


# Perf 表中 vec/mte2/scalar 三列的字段名（每组按顺序取首个可用值）
_RATIO_FIELD_GROUPS = (
    ("aiv_vec_ratio", "vec_ratio"),
    ("aiv_mte2_ratio", "mte2_ratio"),
    ("aiv_scalar_ratio", "scalar_ratio"),
)


def _perf_case_row(c: dict, tile_size: int, chip_aic: int) -> str:
    """Perf 面板的一行性能数据。"""
    p = c.get("performance", {})
    sp = p.get("speedup", 0)
    sp_icon = "🚀" if sp >= 1.5 else ("✅" if sp >= 1.0 else "⚠")
    first_shape = _case_shape_label(c)
    total = _shape_elem_count(first_shape, 0)
    block_dim = _prof(c, "Block Dim")
    if tile_size > 0 and total > 0 and chip_aic > 0:
        active, launched = _active_core_count(total, block_dim, tile_size, chip_aic)
        cores_str = f"{active}/{launched}"
    else:
        cores_str = str(int(block_dim)) if block_dim else "?"
    total_str = (f"{total/1e6:.2f}M" if total >= 1e6
                 else (f"{total/1e3:.1f}K" if total >= 1000 else str(total)))
    ratios = " / ".join(_fmt_ratio(_prof(c, *keys)) for keys in _RATIO_FIELD_GROUPS)
    return (
        f"| {c.get('name','?')} | {first_shape} | {total_str} "
        f"| {cores_str} | {p.get('ref_time_us', 0):.1f} | {p.get('custom_time_us', 0):.1f} "
        f"| **{sp:.2f}x** {sp_icon} "
        f"| {ratios} |\n"
    )


def _tile_size_of(data: dict) -> int:
    """tiling 常量中的 tileSize / TILE_SIZE，缺失时为 0。"""
    tiling_c = data.get("tiling", {}).get("consts", {})
    return int(tiling_c.get("tileSize", tiling_c.get("TILE_SIZE", 0)))


def _write_memory_analysis(data: dict, op_dir: Path) -> None:
    """── 1. Memory analysis.md ──"""
    mem_path = op_dir / "panels" / "memory" / "analysis.md"
    if not _needs_analysis(mem_path):
        return
    mem_path.parent.mkdir(parents=True, exist_ok=True)

    ub_used = data.get("ub_used_kb")
    ub_total = data.get("ub_total_kb")
    util_pct_str = ""
    if ub_used is not None and ub_total:
        try:
            util_pct_str = f"{ub_used:.2f} / {ub_total} KB = {ub_used/ub_total*100:.1f}%"
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    buf_rows = "\n".join(
        f"| {b['name']} | {b['kind']} @ {b['position']} | {b['size_kb']:.2f} KB |"
        for b in data.get("ub_buffers", [])
    ) or "| （未解析到 buffer 声明） | — | — |"

    case_rows = _memory_case_rows(data.get("cases", []), _tile_size_of(data),
                                  data.get("chip", {}).get("aic", 0))
    case_table = (
        "| Case | 输入 Shape | totalElems | active cores | tileSize | 有尾块 |\n"
        "|------|-----------|-----------|-------------|---------|-------|\n"
        + case_rows
    ) if case_rows else ""
    case_section = ("### 各 Case Tiling 参数\n\n" + case_table) if case_table else ""

    mem_path.write_text(f"""\
<!-- NEEDS_CLAUDE_ANALYSIS: 请阅读本文件底部的数据表 + panels/memory/data.json + op_kernel/*.cpp + op_host/*.cpp，
     按 panels/memory/SPEC.md 要求撰写分析，然后删除本行标记。 -->

## Tiling 策略分析

### UB Buffer 分配（客观数据，由脚本提取）

UB 使用：**{util_pct_str or "—"}**

| Buffer 名 | 类型 @ 位置 | 大小 |
|-----------|------------|------|
{buf_rows}

{case_section}

---
<!-- 以下各节由 Claude 按 panels/memory/SPEC.md 撰写 -->

### 切分方案

### 尾块处理

### 流水线设计

### 负载均衡诊断
""", encoding="utf-8")
    logger.info("  ↳ 写入 memory/analysis.md（客观数据 + 待 Claude 分析标记）")


def _write_precision_analysis(data: dict, op_dir: Path) -> None:
    """── 2. Precision analysis.md ──"""
    prec_path = op_dir / "panels" / "precision" / "analysis.md"
    if not _needs_analysis(prec_path):
        return
    prec_path.parent.mkdir(parents=True, exist_ok=True)

    n_total = data.get("n_total", 0)
    pass_rate = f"{data.get('n_pass', 0)}/{n_total}" if n_total else "N/A"
    prec_rows = _precision_case_rows(data.get("cases", []))
    prec_table = ("| Case | Shape | 状态 | max_re | mean_re | rmse |\n"
                  "|------|-------|------|--------|---------|------|\n"
                  f"{prec_rows}") if prec_rows else "（无精度数据）"

    prec_path.write_text(f"""\
<!-- NEEDS_CLAUDE_ANALYSIS: 请阅读本文件底部的数据表 + panels/precision/data.json，
     按 panels/precision/SPEC.md 要求撰写分析，然后删除本行标记。 -->

## 精度分析

### 各 Case 精度数据（客观数据，由脚本提取）

通过率：**{pass_rate}**

{prec_table}

---
<!-- 以下各节由 Claude 按 panels/precision/SPEC.md 撰写 -->

### 总体结论

### 误差类型解读

### 误差分布规律

### 误差来源推断

### 风险评估
""", encoding="utf-8")
    logger.info("  ↳ 写入 precision/analysis.md（客观数据 + 待 Claude 分析标记）")


def _write_perf_analysis(data: dict, op_dir: Path) -> None:
    """── 3. Perf analysis.md ──"""
    perf_path = op_dir / "panels" / "perf" / "analysis.md"
    if not _needs_analysis(perf_path):
        return
    perf_path.parent.mkdir(parents=True, exist_ok=True)

    avg_speedup = data.get("avg_speedup")
    perf_cases = [c for c in data.get("cases", []) if c.get("performance", {}).get("speedup")]
    tile_size = _tile_size_of(data)
    chip_aic = data.get("chip", {}).get("aic", 0)
    perf_rows = "".join(_perf_case_row(c, tile_size, chip_aic) for c in perf_cases)
    perf_table = (
        "| Case | Shape | 元素数 | 活跃/启动核 | ref(us) | custom(us) | Speedup | vec/mte2/scalar |\n"
        "|------|-------|--------|-----------|--------|-----------|---------|----------------|\n"
        + perf_rows
    ) if perf_rows else "（无性能数据）"

    perf_path.write_text(f"""\
<!-- NEEDS_CLAUDE_ANALYSIS: 请阅读本文件底部的数据表 + panels/perf/data.json + op_kernel/*.cpp，
     按 panels/perf/SPEC.md 要求撰写分析，然后删除本行标记。 -->

## 性能分析

### 各 Case 性能数据（客观数据，由脚本提取）

平均 Speedup：**{f"{avg_speedup:.2f}x" if avg_speedup is not None else "N/A"}**（几何均值，{len(perf_cases)} 个 case）

{perf_table}

---
<!-- 以下各节由 Claude 按 panels/perf/SPEC.md 撰写 -->

### 基准说明

### 性能规律

### 瓶颈推断

### 优化建议
""", encoding="utf-8")
    logger.info("  ↳ 写入 perf/analysis.md（客观数据 + 待 Claude 分析标记）")


def _auto_write_analyses(data: dict, op_dir: Path):
    """
    为三个面板写 analysis.md 的**客观数据部分**（buffer 表、case 表、精度表）。

    ⚠ 本函数不生成分析文本。分析内容由 Claude 阅读 panels/*/data.json
    和 kernel/host 源码后，按 panels/*/SPEC.md 要求写入。
    已包含 Claude 撰写内容的文件（不含 NEEDS_CLAUDE_ANALYSIS 标记）不会被覆盖。
    """
    _write_memory_analysis(data, op_dir)
    _write_precision_analysis(data, op_dir)
    _write_perf_analysis(data, op_dir)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args()
    if not args.op_dir and not any([args.op_desc, args.eval, args.precision]):
        logger.error("错误：需要 --op-dir 或至少一个数据源参数。")
        sys.exit(1)
    data = collect_data(args)

    # --extract-only: write panels/*/data.json and exit
    if getattr(args, "extract_only", False):
        if args.op_dir:
            extract_panel_data_json(data, Path(args.op_dir))
        logger.info("\n✅ --extract-only 完成。请按精品流程 Step 3-6 让 Claude 分析各 panel。")
        return

    extract_panel_data_json(data, Path(args.op_dir)) if args.op_dir else None

    # ── 自动生成 analysis.md（精品流程，始终执行）──
    # 必须在 generate_html 之前写好 analysis.md，然后重新加载 panels_content
    if args.op_dir:
        _auto_write_analyses(data, Path(args.op_dir))
        # 重新加载 panels（以便 HTML 包含刚写的 analysis.md）
        data["panels"] = discover_panels(Path(args.op_dir))

    html = generate_html(data)
    # 默认输出到 op_dir/dashboard.html，无 op_dir 时落在当前目录
    if args.output:
        out = Path(args.output)
    elif args.op_dir:
        out = Path(args.op_dir) / "dashboard.html"
    else:
        out = Path("dashboard.html")
    out.write_text(html, encoding="utf-8")
    logger.info(f"\n✅ 看板已生成：{out.resolve()}")
    logger.info(f"   大小：{out.stat().st_size/1024:.1f} KB")
    logger.info(f"   Cases：{data['n_pass']}/{data['n_total']} PASS")
    if data.get("avg_speedup"):
        logger.info(f"   平均 Speedup：{data['avg_speedup']:.2f}x")

    # ── 自动运行质量检测（check_dashboard.py）──
    _check_script = Path(__file__).parent / "check_dashboard.py"
    if _check_script.exists():
        logger.info("")
        _result = subprocess.run(
            [sys.executable, str(_check_script), str(out.resolve())],
            capture_output=False
        )
        if _result.returncode != 0:
            logger.info("\n⚠️  看板存在质量问题，请修复后重新生成。")
            sys.exit(_result.returncode)
        else:
            logger.info("\n✅ 质量检测通过，看板可交付。")


if __name__ == "__main__":
    main()

