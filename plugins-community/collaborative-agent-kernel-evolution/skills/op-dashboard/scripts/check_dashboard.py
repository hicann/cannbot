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
check_dashboard.py — op-dashboard 看板质量闭环检测器 v3

用法:
    python3 ${CLAUDE_SKILL_DIR}/scripts/check_dashboard.py <dashboard.html>
    python3 ...check_dashboard.py <dashboard.html> --strict   # WARN 也视为 FAIL
    python3 ...check_dashboard.py <dashboard.html> --json     # 输出机器可读 JSON

退出码:
    0 — 全部通过（PASS）
    1 — 有 FAIL 项（或 --strict 下有 WARN 项）
    2 — 文件无法读取或 JSON 数据解析失败

检查分组:
    [S] Structural   — HTML 结构完整性（Tab、DOM、JS 函数、自包含）
    [D] Data         — JSON 数据无缺失/undefined 关键字段
    [C] Coverage     — 精度/性能/流图数据覆盖率
    [V] Value        — 数值合理性（speedup、re、UB 大小范围）
    [K] Contract     — op_graph 契约合规（vector/cube）
    [R] Rendering    — 分析文本渲染质量（各 panel 必须章节完整）
    [H] Health       — diagnostics 完整性 + panel analysis 覆盖
"""

import json
import logging
import math
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── 颜色输出 ──────────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def green(t):
    return _c(t, "32")


def yellow(t):
    return _c(t, "33")


def red(t):
    return _c(t, "31")


def bold(t):
    return _c(t, "1")


def dim(t):
    return _c(t, "2")


# ─── 结果收集 ──────────────────────────────────────────────────────────────────
class Results:
    def __init__(self):
        self.items = []  # [{group, name, status, detail}]

    def add(self, group, name, ok, detail="", warn=False):
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        self.items.append({"group": group, "name": name,
                           "status": status, "detail": detail})

    def fail_count(self):
        return sum(1 for i in self.items if i["status"] == "FAIL")

    def warn_count(self):
        return sum(1 for i in self.items if i["status"] == "WARN")

    def pass_count(self):
        return sum(1 for i in self.items if i["status"] == "PASS")

    def print_report(self):
        last_group = None
        for item in self.items:
            g = item["group"]
            if g != last_group:
                logger.info(f"\n  {bold('['+g+']')}")
                last_group = g
            st = item["status"]
            icon = green("✓") if st == "PASS" else (yellow("△") if st == "WARN" else red("✗"))
            line = f"    {icon}  {item['name']}"
            if item["detail"]:
                line += f"  {dim(item['detail'])}"
            logger.info(line)

    def to_dict(self):
        return {
            "summary": {
                "pass": self.pass_count(),
                "warn": self.warn_count(),
                "fail": self.fail_count(),
                "total": len(self.items),
            },
            "items": self.items,
        }


# ─── HTML 解析工具 ─────────────────────────────────────────────────────────────
def _extract_data(html: str) -> dict:
    """从 HTML 中提取 const D = {...} 的 JSON 数据。
    使用 json.JSONDecoder.raw_decode() 替代手动括号计数，
    避免 analysis_html 中的 { } 字符干扰括号平衡计算。
    """
    marker = "const D = "
    start = html.find(marker)
    if start == -1:
        raise ValueError("未找到 'const D = '，可能不是有效的 op-dashboard HTML")
    start += len(marker)
    # Skip optional whitespace before the JSON object
    while start < len(html) and html[start] in ' \t\n\r':
        start += 1
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, start)
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(str(e)) from e


def _has_id(html, id_):
    return f'id="{id_}"' in html or f"id='{id_}'" in html


def _has_fn(html, fn_name):
    return f"function {fn_name}(" in html or f"function {fn_name} (" in html


def _deep_get(obj, *keys, default=None):
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj


# ─── 各组检查 ─────────────────────────────────────────────────────────────────

def check_structural(html: str, r: Results):
    g = "Structural"

    for tab_id in ["tab-algo", "tab-mem", "tab-prec", "tab-perf"]:
        r.add(g, f"Tab 容器 #{tab_id}", _has_id(html, tab_id))

    for dom_id in ["algo-flow", "shape-sel", "ub-bar", "prec-table",
                   "perf-cards", "perf-svg", "perf-note"]:
        r.add(g, f"DOM #{dom_id}", _has_id(html, dom_id))

    # 分析注入槽位（关键渲染依赖）
    for slot in ["mem-analysis-slot", "prec-analysis-slot", "perf-analysis-slot"]:
        ok = _has_id(html, slot)
        r.add(g, f"渲染槽位 #{slot}", ok,
              detail="缺失槽位导致 analysis.md 无法渲染" if not ok else "")

    for fn in ["buildAlgo", "buildMemory", "buildPrecision", "buildPerf",
               "updateShapeVars", "renderOpGraph", "makeIONode", "injectAnalysis"]:
        r.add(g, f"JS function {fn}()", _has_fn(html, fn))

    # injectAnalysis 调用完整性
    for _, slot in [("memory", "mem-analysis-slot"), ("precision",
                                                      "prec-analysis-slot"), ("perf", "perf-analysis-slot")]:
        ok = slot in html and f"injectAnalysis('{slot}'" in html
        r.add(g, f"injectAnalysis({slot}) 调用存在", ok,
              detail="analysis 文本无法注入到页面" if not ok else "")

    cdn_domains = ["cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
                   "fonts.googleapis.com", "ajax.googleapis.com"]
    has_cdn = any(d in html for d in cdn_domains)
    r.add(g, "无外部 CDN 依赖", not has_cdn,
          detail=("发现外部 CDN 引用，离线无法使用" if has_cdn else ""))

    size_kb = len(html.encode("utf-8")) / 1024
    ok_size = 8 < size_kb < 1200
    r.add(g, f"文件大小合理", ok_size,
          detail=f"{size_kb:.1f} KB（期望 8–1200 KB）")


def check_data(html: str, dash: dict, r: Results):
    g = "Data"

    op_name = dash.get("op_name", "")
    r.add(g, "op_name 非空", bool(op_name) and op_name != "Unknown",
          detail=f"op_name='{op_name}'")

    cases = dash.get("cases", [])
    r.add(g, "cases 非空", len(cases) > 0,
          detail=f"共 {len(cases)} 个 case")

    og = dash.get("op_graph", {})
    for field in ["inp_name", "out_name", "inp_tmpl", "out_tmpl"]:
        val = og.get(field, "")
        ok = bool(val) and val != "undefined" and val != "null"
        r.add(g, f"op_graph.{field} 合法", ok,
              detail=f"='{val}'" if not ok else "")

    sc_count = len(og.get("shape_cases") or [])
    r.add(g, "shape_cases 数量与 cases 一致",
          sc_count == len(cases) or sc_count == 0,
          detail=f"shape_cases={sc_count}, cases={len(cases)}" if sc_count != len(cases) else "",
          warn=True)

    critical_paths = ["op_name", "category", "inp_name", "out_name"]
    for k in critical_paths:
        v = dash.get(k)
        if v == "undefined" or v == "null":
            r.add(g, f"D.{k} 无 'undefined' 字面量", False, detail=f"值为 '{v}'")

    ub = dash.get("ub_buffers", [])
    r.add(g, "ub_buffers 存在", isinstance(ub, list),
          detail=f"共 {len(ub)} 个 buffer" if isinstance(ub, list) else "非数组类型")

    # ── 新增：panels 中每个已有 analysis_html 的内容非空且足够长 ──
    panels = dash.get("panels", {})
    for tab in ("memory", "precision", "perf"):
        html_content = panels.get(tab, {}).get("analysis_html", "")
        if html_content:
            # 至少 200 字符（启发式）；简洁但完整的分析也可能稍短，故降为 WARN
            ok = len(html_content) >= 200
            r.add(g, f"panels.{tab}.analysis_html 内容充足",
                  ok,
                  detail=(f"仅 {len(html_content)} 字符（期望 ≥200；若内容已按 SPEC 结构完整可忽略此 WARN）"
                          if not ok else f"{len(html_content)} 字符"),
                  warn=not ok)
        # 若为空，由 Health 部分报 WARN，这里不重复

    # ── 新增：tiling_consts 非空 ──
    tc = dash.get("tiling", {}).get("consts", {})
    r.add(g, "tiling_consts 非空", len(tc) > 0,
          detail=f"{list(tc.keys())}" if tc else "未提取到任何 tiling 常量（检查 op_host/*.cpp）",
          warn=len(tc) == 0)


def check_coverage(dash: dict, r: Results):
    g = "Coverage"

    cases = dash.get("cases", [])
    og = dash.get("op_graph", {})

    def _has_prec(c):
        p = c.get("precision", {})
        return any(p.get(k) is not None
                   for k in ("max_re", "ae_max", "match_rate", "max_diff", "mean_re", "rmse"))
    prec_ok = [c for c in cases if _has_prec(c)]
    prec_pct = len(prec_ok) / max(len(cases), 1) * 100
    r.add(g, f"精度数据覆盖 {len(prec_ok)}/{len(cases)} cases",
          len(prec_ok) == len(cases),
          detail=f"{prec_pct:.0f}%", warn=len(prec_ok) < len(cases))

    perf_ok = [c for c in cases if c.get("performance", {}).get("speedup") is not None]
    perf_pct = len(perf_ok) / max(len(cases), 1) * 100
    r.add(g, f"性能数据覆盖 {len(perf_ok)}/{len(cases)} cases",
          len(perf_ok) > 0,
          detail=f"{perf_pct:.0f}%（msprof multi_case_report.csv）",
          warn=len(perf_ok) == 0)

    units = og.get("units", [])
    r.add(g, f"op_graph 计算单元已提供",
          len(units) > 0,
          detail="needs_algo_flow=True，请提供 algo_flow.json" if not units else f"{len(units)} 个单元",
          warn=len(units) == 0)

    # ── 新增：units 必须有 nodes ──
    if units:
        total_nodes = sum(len(u.get("nodes", [])) for u in units)
        r.add(g, f"op_graph nodes 非空（共 {total_nodes} 个）",
              total_nodes > 0,
              detail="units 存在但所有 nodes 为空，流图无内容" if total_nodes == 0 else "")

    pc = dash.get("pass_comments", [])
    r.add(g, f"Pass 注释存在（{len(pc)} 条）",
          len(pc) > 0,
          detail="kernel .cpp 中未找到 // step N: 或 // Pass N: 注释" if not pc else "",
          warn=len(pc) == 0)

    ub = dash.get("ub_buffers", [])
    r.add(g, f"UB buffer 已解析（{len(ub)} 个）",
          len(ub) > 0,
          detail="未从 *_custom.cpp 解析到 TQue/TBuf" if not ub else "",
          warn=len(ub) == 0)

    n_pass = dash.get("n_pass", 0)
    n_total = dash.get("n_total", 1)
    all_pass = n_pass == n_total and n_total > 0
    r.add(g, f"精度全部通过 {n_pass}/{n_total} PASS",
          all_pass,
          detail=f"{n_pass}/{n_total}" if not all_pass else "",
          warn=not all_pass)

    # ── 新增：n_pass 与 cases 一致性 ──
    cases_passed = sum(1 for c in cases if c.get("precision", {}).get("passed") is True)
    if cases and n_total > 0:
        r.add(g, f"n_pass 与 cases.precision.passed 一致",
              cases_passed == n_pass or cases_passed == 0,
              detail=(f"D.n_pass={n_pass} vs cases中passed={cases_passed}"
                      if cases_passed != n_pass and cases_passed != 0 else ""),
              warn=cases_passed != n_pass and cases_passed != 0)


def _dash_speedups(cases: list) -> list:
    """所有已记录 speedup 的 case 取值。"""
    return [c["performance"]["speedup"]
            for c in cases if c.get("performance", {}).get("speedup") is not None]


def _check_speedup_values(dash: dict, cases: list, speedups: list, r: Results) -> None:
    """Speedup 值域检查；精度失败导致的 0 速比降级为 WARN。"""
    if not speedups:
        return
    bad_sp = [s for s in speedups if not (0.01 <= s <= 100)]
    # 精度全部失败时，speedup=0.0 是运行时崩溃的正常结果，降级为 WARN
    prec_failed_all = dash.get("n_pass", 0) == 0 and dash.get("n_total", 0) > 0
    # 部分精度失败：零速比对应精度失败 case，属预期（崩溃无法产生 profiling），降级为 WARN
    prec_fail_count = sum(1 for c in cases if c.get("precision", {}).get("passed") is False)
    bad_sp_zeros = all(s == 0.0 for s in bad_sp) if bad_sp else False
    prec_partial_fail = bad_sp_zeros and 0 < len(bad_sp) <= max(prec_fail_count, 1)
    r.add("Value", "Speedup 值合理 [0.01x, 100x]",
          len(bad_sp) == 0,
          detail=(f"异常值: {bad_sp}（精度失败 case 的 speedup=0 符合预期）" if bad_sp
                  else f"范围 {min(speedups):.2f}x–{max(speedups):.2f}x"),
          warn=prec_failed_all or prec_partial_fail)


def _check_max_re_values(cases: list, r: Results) -> None:
    """max_re 值域检查。"""
    max_res = [c["precision"]["max_re"]
               for c in cases if c.get("precision", {}).get("max_re") is not None]
    if not max_res:
        return
    bad_re = [v for v in max_res if not (0 <= v <= 1e5)]
    r.add("Value", "max_re 值合理 [0, 1e5]",
          len(bad_re) == 0,
          detail=f"异常值: {bad_re}" if bad_re else f"范围 {min(max_res):.4f}–{max(max_res):.4f}")


def _check_ub_capacity(ub_used: float, ub_total: float, ub_estimated: bool, r: Results) -> None:
    """UB 使用量与物理上限的比较，以及 ub_total_kb 本身的合理性。"""
    g = "Value"
    if ub_used > ub_total:
        if ub_estimated:
            # Sizes came from tileLength fallback — may be over-estimates; WARN only.
            r.add(g, f"UB 估算超出范围 {ub_used:.1f}/{ub_total:.0f} KB",
                  False,
                  detail=f"估算值超出范围: {ub_used:.1f} > {ub_total:.0f} KB（来自 tileLength fallback，可能高估）",
                  warn=True)
        else:
            # Sizes were parsed from InitBuffer — genuine overflow; FAIL.
            r.add(g, f"UB 使用率超限 {ub_used:.1f}/{ub_total:.0f} KB",
                  False,
                  detail=f"超出物理上限: {ub_used:.1f} > {ub_total:.0f} KB（来自 InitBuffer 解析，非估算）")
    elif ub_used == 0:
        # Missing data (kernel not parsed) → WARN (ok=False so Results.add emits WARN not PASS)
        r.add(g, "UB 使用率（ub_used_kb=0，buffer 声明未解析）",
              False, detail="未从 kernel/analysis.md 中提取到 UB buffer，Tab2 数据可能为空",
              warn=True)
    else:
        r.add(g, f"UB 使用率合理 {ub_used:.1f}/{ub_total:.0f} KB", True,
              detail=f"{round(ub_used/ub_total*100,1)}%")

    # ── 新增：ub_total_kb 合理性（已知芯片 UB 范围）──
    in_range = 128 <= ub_total <= 512
    r.add(g, "ub_total_kb 合理（已知芯片范围）",
          in_range,
          detail=f"ub_total_kb={ub_total}（期望 128–512 KB，910B系列=192KB，910=256KB）",
          warn=not in_range)


def _check_avg_speedup(dash: dict, speedups: list, r: Results) -> None:
    """── 修复：avg_speedup 一致性用几何均值 ──"""
    avg_sp = dash.get("avg_speedup")
    if avg_sp is None:
        return
    pos_speedups = [s for s in speedups if s > 0]
    if len(pos_speedups) > 1:
        geo_mean = math.exp(sum(math.log(s) for s in pos_speedups) / len(pos_speedups))
        diff_ok = abs(avg_sp - geo_mean) < 0.1
        r.add("Value", "avg_speedup 与 cases 一致（几何均值）",
              diff_ok,
              detail=f"avg={avg_sp:.2f} vs 几何均值={geo_mean:.2f}" if not diff_ok else f"{avg_sp:.2f}x")
        return
    if speedups:
        r.add("Value", "avg_speedup 存在", True, detail=f"{avg_sp:.2f}x")


def _is_cube_category(dash: dict, op_category: str) -> bool:
    """Cube/CV 算子判定：算子类别关键字命中，或 tiling 常量里出现 L1/L0 形状。"""
    if any(k in op_category for k in ("cube", "convolut", "conv2d", "matmul", "gemm")):
        return True
    return any(k.startswith(("L1Shape", "L0Shape", "L1_", "L0_"))
               for k in dash.get("tiling", {}).get("consts", {}))


def _check_ub_utilization(dash: dict, ub_used: float, ub_total: float, r: Results) -> None:
    """── UB 利用率检查 ──
    Cube/CV 算子主计算在 L1/L0/L0C，UB 只用于向量 Epilogue（bias add 等），
    低利用率属正常设计，不应产生 WARN。只对纯 Vector 算子报警。"""
    if not (ub_total > 0 and ub_used > 0):
        return
    util_pct = ub_used / ub_total * 100
    # op_desc.category: e.g. "matmul", "reduction", "convolution", "elementwise"
    op_category = str(dash.get("category") or "").lower()
    if _is_cube_category(dash, op_category):
        # Cube/CV: 低利用率正常，直接 PASS
        r.add("Value", f"UB 利用率检查（{util_pct:.1f}%）",
              True,
              detail=f"{util_pct:.1f}%（cube 算子 UB 仅用于 Epilogue，属正常）")
        return
    too_low = util_pct < 5
    detail_low = (f"仅 {util_pct:.1f}%，建议增大 tileSize 提升带宽效率"
                  if too_low else f"{util_pct:.1f}%")
    r.add("Value", f"UB 利用率检查（{util_pct:.1f}%）",
          not too_low,
          detail=detail_low,
          warn=too_low)


def check_values(dash: dict, r: Results):
    cases = dash.get("cases", [])
    ub_used = dash.get("ub_used_kb", 0)
    # ub_total_kb should come from chip probe in gen_dashboard.py.
    # Fallback to 192 KB (Ascend910B series baseline per real hardware spec:
    # each vector_core/AIV has 192 KB UB). If missing, the ub_total_kb range
    # check below (128–512 KB) will PASS silently — gen_dashboard.py should
    # always write this field from design_tokens.json chip.ub_kb.
    ub_total = dash.get("ub_total_kb", 192)
    # ub_estimated=True means at least one buffer size came from tileLength fallback
    # (InitBuffer parse failed). False means all sizes were successfully parsed.
    ub_estimated = dash.get("ub_estimated", True)  # default True (conservative)

    speedups = _dash_speedups(cases)
    _check_speedup_values(dash, cases, speedups, r)
    _check_max_re_values(cases, r)
    _check_ub_capacity(ub_used, ub_total, ub_estimated, r)
    _check_avg_speedup(dash, speedups, r)
    _check_ub_utilization(dash, ub_used, ub_total, r)


def _has_external_url(lower: str) -> bool:
    """片段是否引用了外部资源（绝对 URL 或协议相对 URL）。"""
    if "https://" in lower or "http://" in lower:
        return True
    return bool(re.search(r'=\s*(?:"|\'|)\s*//', lower))  # scheme-relative URLs


def _csp_violations(frag_html: str) -> list:
    """列出 Claude 手写 HTML 片段中的危险构造，按固定顺序返回。"""
    lower = frag_html.lower()
    issues = []
    if "<script" in lower:
        issues.append("<script>")
    if _has_external_url(lower):
        issues.append("外部URL")
    if re.search(r'\son[a-z]{1,20}\s*=', lower):
        issues.append("事件处理器属性")
    if "javascript:" in lower:
        issues.append("javascript:URL")
    if "<iframe" in lower:
        issues.append("<iframe>")
    return issues


def _csp_check(r: Results, frag_html: str, label: str) -> None:
    """Check a Claude-authored HTML fragment for XSS vectors beyond script/CDN."""
    issues = _csp_violations(frag_html)
    r.add("Contract", f"{label} 不含危险 HTML（CSP 规则）",
          not issues,
          detail=f"含违规内容：{', '.join(issues)}" if issues else "")


def _check_graph_node(r: Results, prefix: str, node: dict) -> None:
    """JS 兜底渲染器 renderOpGraph 依赖的节点字段检查。"""
    for req in ["api", "formula", "in_tmpl", "out_tmpl"]:
        if req not in node:
            r.add("Contract", f"{prefix}.{req} 存在", False, detail="字段缺失")
    if node.get("api") == "DataCopy":
        r.add("Contract", f"{prefix} 非 DataCopy",
              False, detail="计算流图不应包含 DataCopy（内存搬运节点）")


def _check_op_graph_unit(r: Results, ui: int, unit: dict, check_nodes: bool) -> None:
    """检查 op_graph.units[ui] 的 id、节点数量与（可选的）逐节点字段。"""
    valid_ids = {"vector", "cube"}
    uid = unit.get("id", "")
    r.add("Contract", f"units[{ui}].id='{uid}' 合法",
          uid in valid_ids,
          detail=f"非法 id='{uid}'，必须是 {sorted(valid_ids)} 之一" if uid not in valid_ids else "")

    nodes = unit.get("nodes", [])
    r.add("Contract", f"units[{ui}] nodes 非空",
          len(nodes) > 0,
          detail="nodes 为空" if not nodes else f"{len(nodes)} 个节点")

    if not check_nodes:
        return
    for ni, node in enumerate(nodes):
        _check_graph_node(r, f"units[{ui}].nodes[{ni}]", node)


def _check_ub_viz(r: Results, ub_viz_html: str) -> None:
    """检查 memory panel 的 ub_viz.html 片段。"""
    r.add("Contract", "memory ub_viz.html 已生成",
          bool(ub_viz_html),
          detail="ub_viz.html 缺失或为空，UB 内存可视化将不显示")

    if not ub_viz_html:
        return
    ub_viz_ok = "<svg" in ub_viz_html and len(ub_viz_html) > 300
    r.add("Contract", "memory ub_viz.html 含 SVG 且长度合理",
          ub_viz_ok,
          detail=f"长度={len(ub_viz_html)}, 含svg={'是' if '<svg' in ub_viz_html else '否'}")
    _csp_check(r, ub_viz_html, "ub_viz.html")


def _check_algo_fragments(r: Results, panel: dict) -> None:
    """检查 CC 写入的 flow.html / steps.html / ub_viz.html（替代 algo_flow.json + validate_contract.py）。"""
    algo_p = panel.get("algo", {})
    flow_html = algo_p.get("flow_html", "")
    steps_html = algo_p.get("steps_html", "")

    has_node = "algo-node" in flow_html or "algo-phase" in flow_html
    flow_ok = len(flow_html) > 200 and has_node
    r.add("Contract", "algo flow.html 已生成且含节点元素",
          flow_ok,
          detail=(f"长度={len(flow_html)}，含节点="
                  f"{'是' if has_node else '否'}"
                  f"（期望 >200 字符且含 algo-node/algo-phase）"
                  if not flow_ok else f"长度={len(flow_html)}"))
    if flow_html:
        _csp_check(r, flow_html, "flow.html")

    steps_ok = len(steps_html) > 100
    r.add("Contract", "algo steps.html 已生成",
          steps_ok,
          detail=f"长度={len(steps_html)}（期望 >100 字符）" if not steps_ok else f"长度={len(steps_html)}")
    if steps_html:
        _csp_check(r, steps_html, "steps.html")

    _check_ub_viz(r, panel.get("memory", {}).get("ub_viz_html", ""))


def check_contract(dash: dict, html_path: Path, r: Results):
    og = dash.get("op_graph", {})
    panel = dash.get("panels", {})

    sv = og.get("shape_vars", [])
    sv_ok = isinstance(sv, list) and len(sv) > 0 and all(isinstance(v, str) for v in sv)
    r.add("Contract", f"shape_vars 格式合法 {sv}",
          sv_ok,
          detail="" if sv_ok else "非字符串数组或为空")

    # Per-node required-field checks and DataCopy ban apply when flow.html is absent,
    # since the JS fallback renderer (renderOpGraph) relies on these fields.
    check_nodes = len(panel.get("algo", {}).get("flow_html", "")) <= 200
    for ui, unit in enumerate(og.get("units", [])):
        _check_op_graph_unit(r, ui, unit, check_nodes)

    _check_algo_fragments(r, panel)


# ─── [R] Rendering: 分析文本质量验证 ────────────────────────────────────────────

# 各 panel 在 analysis.md 中必须包含的关键词（来自 SPEC.md 验收规则）
# 同时兼容 _auto_write_analyses 生成的占位标题（"占位"一词作为兜底匹配）
_AUTO_PLACEHOLDER = r"占位|自动占位|需人工确认"
_REQUIRED_SECTIONS = {
    "memory": {
        "切分方案": rf"切分方案|{_AUTO_PLACEHOLDER}",
        "尾块处理": rf"尾块|{_AUTO_PLACEHOLDER}",
        "流水线设计": rf"流水线|{_AUTO_PLACEHOLDER}",
        "UB空间利用": rf"UB.*空间|空间利用|UB.*利用|{_AUTO_PLACEHOLDER}",
        "负载均衡": rf"负载均衡|{_AUTO_PLACEHOLDER}",
    },
    "precision": {
        # [PASS]/[FAIL] 在 _md_to_html 中渲染为 <span class="badge bp">PASS</span>
        "总体结论(PASS/FAIL)": rf"\[PASS\]|\[FAIL\]|badge bp.*PASS|badge bp.*FAIL|>PASS<|>FAIL<|{_AUTO_PLACEHOLDER}",
        "误差类型解读": rf"误差.*类型|类型.*误差|max_re|mean_re|{_AUTO_PLACEHOLDER}",
        "误差分布规律": rf"误差.*分布|分布.*规律|case|{_AUTO_PLACEHOLDER}",
        "误差来源推断": rf"误差.*来源|来源.*推断|{_AUTO_PLACEHOLDER}",
        "风险评估": rf"风险|{_AUTO_PLACEHOLDER}",
    },
    "perf": {
        "基准说明": rf"基准|参考实现|{_AUTO_PLACEHOLDER}",
        "性能规律": rf"性能规律|speedup|加速|{_AUTO_PLACEHOLDER}",
        "瓶颈推断": rf"瓶颈|{_AUTO_PLACEHOLDER}",
        "优化建议": rf"优化建议|建议|{_AUTO_PLACEHOLDER}",
    },
}


def _check_shape_vars_guard(dash: dict, html: str, r: Results) -> None:
    """── 0. JS 致命错误检测（最优先）──
    shape_cases=null 导致 updateShapeVars() 抛 TypeError，使所有 build 函数失效。"""
    if dash.get("op_graph", {}).get("shape_cases") is not None:
        return
    safe_guard = "!og.shape_cases ||" in html or "og.shape_cases &&" in html
    r.add("Rendering", "updateShapeVars null 守卫（防面板全空白）",
          safe_guard,
          detail=("shape_cases=null 但无 null 守卫：导致 updateShapeVars() TypeError，"
                  "精度/性能/算法面板全空白！" if not safe_guard else ""))


def _check_panel_sections(panels: dict, r: Results) -> None:
    """检查各 panel 的 analysis_html 是否嵌入，以及 SPEC.md 要求的章节是否齐备。"""
    for tab, required in _REQUIRED_SECTIONS.items():
        html_content = panels.get(tab, {}).get("analysis_html", "")

        # 1. 检查 analysis_html 实际存在于 D 中（不只是文件在磁盘）
        r.add("Rendering", f"{tab}/analysis_html 已嵌入 D.panels",
              bool(html_content) and len(html_content) >= 100,
              detail=f"长度={len(html_content)}" if html_content else "未嵌入，分析文本不会渲染")

        if not html_content:
            continue
        _check_required_sections(tab, required, html_content, r)


def _check_required_sections(tab: str, required: dict, html_content: str, r: Results) -> None:
    """2. 检查必要章节关键词"""
    for section_name, pattern in required.items():
        found = bool(re.search(pattern, html_content, re.IGNORECASE))
        r.add("Rendering", f"{tab}: 含「{section_name}」",
              found,
              detail="缺少该章节，analysis.md 不符合 SPEC.md 要求" if not found else "")


def _check_overview_data(dash: dict, r: Results) -> None:
    """3./4. 精度总览与性能总览是否有实际数据。"""
    g = "Rendering"
    n_pass = dash.get("n_pass", 0)
    n_total = dash.get("n_total", 0)
    r.add(g, "精度总览有实际数据（n_total > 0）",
          n_total > 0,
          detail="n_total=0，精度面板为空" if n_total == 0 else f"{n_pass}/{n_total} PASS")

    # 精度全部失败时，性能数据缺失是预期行为（运行时崩溃无法产生 profiling），降级为 WARN
    avg_sp = dash.get("avg_speedup")
    r.add(g, "性能总览有实际数据（avg_speedup 非 None）",
          avg_sp is not None and avg_sp > 0,
          detail=("avg_speedup 为空（精度全失败时符合预期，修复精度后应有性能数据）"
                  if avg_sp is None else f"{avg_sp:.2f}x"),
          warn=n_pass == 0 and n_total > 0)


def _check_ub_buffer_fields(dash: dict, r: Results) -> None:
    """5. 检查 UB buffer 有渲染所需字段"""
    ub = dash.get("ub_buffers", [])
    if not ub:
        return
    missing_fields = []
    for b in ub:
        for field in ("name", "kind", "position", "size_kb", "color"):
            if field not in b:
                missing_fields.append(f"{b.get('name','?')}.{field}")
    r.add("Rendering", "UB buffer 字段完整（可渲染）",
          len(missing_fields) == 0,
          detail=f"缺少字段: {missing_fields}" if missing_fields else f"{len(ub)} 个 buffer 均完整")


def _check_graph_renderable(dash: dict, r: Results) -> None:
    """6. 检查 op_graph 有可渲染的 nodes（api+formula 非空）"""
    units = dash.get("op_graph", {}).get("units", [])
    if not units:
        return
    renderable_nodes = 0
    for unit in units:
        for node in unit.get("nodes", []):
            if node.get("api") and node.get("formula"):
                renderable_nodes += 1
    r.add("Rendering", f"op_graph nodes 可渲染（{renderable_nodes} 个有 api+formula）",
          renderable_nodes > 0,
          detail="nodes 中缺少 api 或 formula，算法流图无法渲染" if renderable_nodes == 0 else "")


def _check_tiling_consts(dash: dict, r: Results) -> None:
    """7. Tiling 常量非空（否则 Tiling 策略分析必然空白）"""
    tc = dash.get("tiling", {}).get("consts", {})
    r.add("Rendering", "tiling_consts 非空（Tiling 面板有数据）",
          len(tc) > 0,
          detail="tiling_consts={} 导致 Tiling 策略分析空白，检查 op_host/*.cpp 常量提取"
                 if not tc else f"{list(tc.keys())}",
          warn=len(tc) == 0)


def check_rendering(dash: dict, html: str, r: Results):
    """[R] Rendering — 验证 analysis 文本真实渲染质量 + JS 安全性"""
    _check_shape_vars_guard(dash, html, r)
    _check_panel_sections(dash.get("panels", {}), r)
    _check_overview_data(dash, r)
    _check_ub_buffer_fields(dash, r)
    _check_graph_renderable(dash, r)
    _check_tiling_consts(dash, r)


def check_health(dash: dict, html_path: Path, r: Results):
    g = "Health"

    diags = dash.get("diagnostics")
    r.add(g, "diagnostics 字段存在", isinstance(diags, list),
          detail=f"{len(diags)} 项" if isinstance(diags, list) else "缺失",
          warn=not isinstance(diags, list))

    panels = dash.get("panels")
    r.add(g, "panels 字段存在", isinstance(panels, dict),
          detail=f"{len(panels)} 个 panel" if isinstance(panels, dict) else "缺失",
          warn=not isinstance(panels, dict))

    if not isinstance(panels, dict):
        return

    for tab in ("memory", "precision", "perf"):
        has_analysis = bool(panels.get(tab, {}).get("analysis_html"))
        r.add(g, f"panels.{tab} 含 Claude 分析（analysis.md）",
              has_analysis,
              detail="已嵌入" if has_analysis else f"缺失 — 重新运行 gen_dashboard.py 自动生成",
              warn=not has_analysis)

    has_algo_analysis = bool(panels.get("algo", {}).get("analysis_html"))
    r.add(g, "panels.algo 含说明文字（可选）",
          True,
          detail="已嵌入 Claude 算法说明" if has_algo_analysis else "未生成（可选）")

    if isinstance(diags, list):
        missing_items = [d for d in diags if d.get("level") == "MISSING"]
        r.add(g, f"无 MISSING 数据项",
              len(missing_items) == 0,
              detail=f"{len(missing_items)} 项缺失: {[d.get('source') for d in missing_items]}"
                     if missing_items else "全部数据源已找到",
              warn=len(missing_items) > 0)


# ─── 主入口 ───────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = sys.argv[1:]
    strict = "--strict" in args
    as_json = "--json" in args
    files = [a for a in args if not a.startswith("--")]

    if not files:
        logger.info("用法: python3 check_dashboard.py <dashboard.html> [--strict] [--json]")
        sys.exit(0)

    html_path = Path(files[0])
    if not html_path.exists():
        logger.error(f"错误：文件不存在 {html_path}")
        sys.exit(2)

    html = html_path.read_text(encoding="utf-8", errors="replace")

    try:
        dash = _extract_data(html)
    except Exception as e:
        logger.error(f"错误：无法提取 JSON 数据 — {e}")
        sys.exit(2)

    r = Results()
    check_structural(html, r)
    check_data(html, dash, r)
    check_coverage(dash, r)
    check_values(dash, r)
    check_contract(dash, html_path, r)
    check_rendering(dash, html, r)   # ← 新增
    check_health(dash, html_path, r)

    if as_json:
        logger.info(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
    else:
        size_kb = html_path.stat().st_size / 1024
        logger.info(f"\n{bold('op-dashboard 质量检测 v3')}  {dim(html_path.name)}  {dim(f'{size_kb:.1f} KB')}")
        r.print_report()

        total = len(r.items)
        fp = r.fail_count()
        wp = r.warn_count()
        pp = r.pass_count()

        logger.info(f"\n  {'─'*52}")
        summary = f"  总计 {total} 项：{green(str(pp)+' PASS')}  {yellow(str(wp)+' WARN')}  {red(str(fp)+' FAIL')}"
        logger.info(summary)

        if fp == 0 and wp == 0:
            logger.info(f"  {green('✓ 看板质量优秀，可交付。')}")
        elif fp == 0:
            logger.info(f"  {yellow('△ 看板基本可用，存在警告项，建议修复后交付。')}")
        else:
            logger.info(f"  {red('✗ 存在失败项，看板不完整，请修复后重新生成。')}")
        logger.info("")

    fail = r.fail_count() > 0 or (strict and r.warn_count() > 0)
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
