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
dashboard_template.py  —  op-dashboard 的 HTML 模板

单一字符串常量 HTML_TEMPLATE，含内联 CSS 与 JS。占位符 __DATA__ /
__TITLE__ / __CHARTJS__ 由 gen_dashboard.generate_html 替换。
"""

# ─── HTML TEMPLATE ────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>__TITLE__ — AscendC Dashboard</title>
<script>/*__CHARTJS__*/</script>
<style>
/* ══ 变量 ══ */
:root{
  --bg:#f6f8fa;--sf:#fff;--sf2:#f0f2f5;--sf3:#e8ecf0;
  --bd:#d0d7de;--bdl:#e8ecf0;
  --tx:#1a1a1a;--tx2:#57606a;--tx3:#8b949e;
  --ac:#0969da;--gn:#1a7f37;--rd:#cf222e;--or:#bf8700;--pu:#8250df;
  --mono:'SF Mono',Consolas,'Courier New',monospace;
  --r:8px;--rl:12px;--sh:0 1px 4px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.05);
}
@media(prefers-color-scheme:dark){:root{
  --bg:#0d1117;--sf:#161b22;--sf2:#1c2128;--sf3:#21262d;
  --bd:#30363d;--bdl:#21262d;--tx:#e6edf3;--tx2:#8b949e;--tx3:#6e7681;
  --ac:#58a6ff;--gn:#3fb950;--rd:#f85149;--or:#d29922;--pu:#a371f7;
}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--tx);font-size:14px;line-height:1.5}
code,.mono{font-family:var(--mono)}

/* ── Header ── */
.hdr{padding:24px 32px 0;max-width:1100px;margin:0 auto}
.hdr-row{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.hdr-name{font-size:26px;font-weight:700;letter-spacing:-.03em;font-family:var(--mono)}
.hdr-cat{font-size:11px;padding:3px 10px;border-radius:16px;background:rgba(130,80,223,.1);color:var(--pu);font-weight:600;border:1px solid rgba(130,80,223,.2)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.chip{background:var(--sf);border:1px solid var(--bd);border-radius:16px;padding:4px 12px;font-size:12px;font-family:var(--mono)}
.chip b{color:var(--ac)}
.chip.pass b{color:var(--gn)}.chip.warn b{color:var(--or)}.chip.fail b{color:var(--rd)}
.desc{margin-top:10px;font-size:13px;color:var(--tx2);max-width:820px;line-height:1.7}

/* ── Tabs ── */
.tab-bar{display:flex;padding:0 32px;max-width:1100px;margin:18px auto 0;border-bottom:1px solid var(--bd);overflow-x:auto}
.tb{padding:9px 18px;font-size:13px;cursor:pointer;border:none;background:none;color:var(--tx2);border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;transition:color .15s,border-color .15s;display:flex;align-items:center;gap:6px;font-family:inherit}
.tb:hover{color:var(--tx)}.tb.active{color:var(--ac);border-bottom-color:var(--ac);font-weight:600}

/* ── Content ── */
.content{max-width:1100px;margin:0 auto;padding:24px 32px 56px}
.tp{display:none}.tp.active{display:block}

/* ── Cards ── */
.card{background:var(--sf);border:1px solid var(--bd);border-radius:var(--rl);padding:20px;margin-bottom:16px;box-shadow:var(--sh)}
.ct{font-size:14px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.ct .ico{font-size:16px}
.lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--tx3);margin-bottom:8px}

/* ── Badges ── */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:980px;font-size:12px;font-weight:600}
.bp{background:rgba(26,127,55,.1);color:var(--gn);border:1px solid rgba(26,127,55,.2)}
.bf{background:rgba(207,34,46,.1);color:var(--rd);border:1px solid rgba(207,34,46,.2)}
.bw{background:rgba(191,135,0,.1);color:var(--or);border:1px solid rgba(191,135,0,.2)}
.bi{background:rgba(9,105,218,.08);color:var(--ac);border:1px solid rgba(9,105,218,.15)}

/* ══ TAB 1: 算法图示（工业级计算逻辑流） ══ */
/* IO tensor block */
.tv{display:inline-flex;flex-direction:column;align-items:center;gap:3px}
.tg{display:flex;flex-direction:column;border-radius:3px;overflow:hidden}
.tr{display:flex}.tc{border:1px solid rgba(255,255,255,.25)}
.td{font-size:11px;color:var(--tx3);font-family:var(--mono)}
.tn{font-size:12px;font-weight:700;font-family:var(--mono)}

/* Shape selector bar */
.shape-bar{display:flex;align-items:center;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.shape-bar label{font-size:12px;font-weight:600;color:var(--tx2);white-space:nowrap}
.shape-bar select{background:var(--sf);color:var(--tx);border:1px solid var(--bd);border-radius:var(--r);padding:6px 12px;font-size:13px;font-family:var(--mono);cursor:pointer;outline:none}
.shape-bar select:focus{border-color:var(--ac)}

/* IO node (input / output tensor) */
.io-node{background:var(--sf);border:1.5px solid var(--ac);border-radius:var(--r);padding:12px 20px;text-align:center;display:inline-flex;flex-direction:column;align-items:center;gap:6px}
.io-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--tx3)}
.io-name{font-size:15px;font-weight:700;font-family:var(--mono);color:var(--ac)}
.io-shape{font-size:12px;font-family:var(--mono);color:var(--tx2)}
.io-dtype{font-size:10px;color:var(--tx3);font-family:var(--mono)}

/* Arrow between units */
.flow-arrow{text-align:center;color:var(--tx3);font-size:22px;padding:6px 0;user-select:none}

/* Hardware unit group */
.unit-group{border-radius:12px;padding:16px 20px;width:fit-content;max-width:100%;box-sizing:border-box}
.unit-hdr{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;margin-bottom:14px;font-family:var(--mono)}
.unit-nodes{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.unit-sep{color:var(--tx3);font-size:20px;align-self:center;padding:0 2px;user-select:none}

/* API node card */
.api-node{background:var(--sf);border-radius:8px;padding:12px 14px;min-width:110px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.api-name{font-family:var(--mono);font-size:13px;font-weight:700;margin-bottom:4px}
.api-formula{font-size:11px;color:var(--tx2);font-family:var(--mono);margin:3px 0;line-height:1.4}
.api-shape{font-size:10px;color:var(--tx3);font-family:var(--mono);margin-top:3px}

/* Flow outer container */
.flow-col{display:flex;flex-direction:column;align-items:center;gap:0;width:100%}

/* ── Claude-written algo flow HTML classes ── */
.algo-flow{display:flex;flex-direction:column;align-items:center;gap:4px;width:100%;padding:8px 0}
.algo-phase{border:2px solid var(--bd);border-radius:8px;padding:12px 16px;margin:2px 0;width:100%;max-width:640px;box-sizing:border-box;display:flex;flex-direction:column;gap:4px}
.algo-phase[data-core="AIC"]{border-color:#bf8700;background:#fffbf0}
.algo-phase[data-core="AIV"]{border-color:#8250df;background:#f5f0ff}
.algo-phase-lbl{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-bottom:4px}
.algo-phase[data-core="AIC"] .algo-phase-lbl{color:#bf8700}
.algo-phase[data-core="AIV"] .algo-phase-lbl{color:#8250df}
.algo-node{border-radius:6px;padding:7px 12px;margin:2px auto;font-family:var(--mono);font-size:12px;line-height:1.5;max-width:360px;width:auto;box-sizing:border-box;text-align:center}
.algo-node.input{background:#dff0fc;border:1px solid #0969da;color:#0550ae}
.algo-node.output{background:#dcfce7;border:1px solid #1a7f37;color:#166534}
.algo-node.workspace{background:#f6f8fa;border:1px dashed #8c959f;color:#57606a}
.algo-node.compute{background:#fff8c5;border:1px solid #bf8700;color:#7d4e00}
.algo-node.sync{background:#fef2f2;border:1.5px dashed #cf222e;color:#a40e26}
.algo-arrow{color:var(--tx3);font-size:20px;line-height:1;text-align:center;padding:2px 0}
.algo-arrow-lbl{font-size:11px;color:var(--tx3);font-family:var(--mono);margin-left:4px}
.algo-gate{background:#e8f4fd;border:1px solid #54aeff;border-radius:6px;padding:5px 10px;font-size:11px;font-family:var(--mono);color:#0550ae;margin:2px auto;max-width:600px;width:100%;box-sizing:border-box;text-align:center}
.algo-steps{display:flex;flex-direction:column;gap:10px;width:100%}
.algo-step{display:flex;gap:10px;align-items:flex-start}
.algo-step-num{background:var(--ac);color:#fff;border-radius:50%;min-width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:2px}
.algo-step-body{font-size:13px;line-height:1.6;color:var(--tx1)}
.algo-step-code{font-family:var(--mono);font-size:11px;color:var(--tx2);background:#f6f8fa;padding:2px 6px;border-radius:3px;display:inline-block;margin-top:2px}

/* Algo steps list (raw Pass comments) */
.as-list{list-style:none;counter-reset:s}
.as-list li{counter-increment:s;display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:1px solid var(--bdl);font-size:13px}
.as-list li:last-child{border-bottom:none}
.as-list li::before{content:counter(s);min-width:22px;height:22px;background:var(--sf2);border:1px solid var(--bd);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--ac);font-family:var(--mono);flex-shrink:0}

/* ══ TAB 2: 内存 Tiling ══ */
.ub-bar{display:flex;height:36px;border-radius:var(--r);overflow:hidden;border:1px solid var(--bd);background:var(--sf3)}
.ub-seg{display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:600;color:#fff;overflow:hidden;cursor:default;position:relative;min-width:3px;transition:opacity .15s}
.ub-seg:hover{opacity:.85;outline:2px solid rgba(0,0,0,.4);z-index:2}
.ub-labels-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:11px;font-family:var(--mono)}
.ub-label-chip{display:flex;align-items:center;gap:4px;padding:2px 7px;border-radius:4px;background:var(--sf2);border:1px solid var(--bd);cursor:default;white-space:nowrap}
.ub-label-swatch{width:10px;height:10px;border-radius:2px;flex-shrink:0}
.ub-free{background:var(--sf3);color:var(--tx3)}
.ub-ruler{position:relative;height:14px;margin-top:2px}

/* ── Claude-written UB viz HTML classes ── */
.ub-alloc{display:flex;gap:20px;align-items:center;padding:8px 0;flex-wrap:wrap}
.ub-alloc-legend{display:flex;flex-direction:column;gap:5px;flex:1;min-width:160px}
.ub-alloc-row{display:flex;align-items:center;gap:7px;font-size:12px}
.ub-free-bar{display:flex;align-items:center;gap:7px;font-size:12px;margin-top:2px;padding-top:5px;border-top:1px solid var(--bdl)}
.ub-alloc-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.ub-alloc-label{font-family:var(--mono);color:var(--tx1);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ub-alloc-pct{font-size:10px;font-family:var(--mono);min-width:48px;text-align:right}
.ub-alloc-size{font-family:var(--mono);color:var(--tx3);min-width:56px;text-align:right}
#ub-viz-slot{margin-top:12px}
.ub-tick{position:absolute;bottom:0;font-size:9px;color:var(--tx3);font-family:var(--mono);transform:translateX(-50%)}
.ub-tick::before{content:'';position:absolute;top:0;left:50%;width:1px;height:6px;background:var(--bd)}
.ub-labels{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.ub-lbl{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--tx2)}
.ub-dot{width:10px;height:10px;border-radius:2px;flex-shrink:0}

.dt{width:100%;border-collapse:collapse;font-size:13px}
.dt th{background:var(--sf2);padding:8px 14px;text-align:left;font-size:11px;font-weight:600;color:var(--tx3);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--bd)}
.dt td{padding:8px 14px;border-bottom:1px solid var(--bdl);vertical-align:middle}
.dt tr:last-child td{border-bottom:none}
.val{font-family:var(--mono);font-weight:600;color:var(--tx)}
.note{font-size:11px;color:var(--tx3);margin-top:2px}
.pipe-tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;font-family:var(--mono)}

/* ══ TAB 3: 精度 ══ */
/* Shape selector */
.shape-sel{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.shape-sel label{font-size:12px;font-weight:600;color:var(--tx2)}
.shape-sel select{background:var(--sf);color:var(--tx);border:1px solid var(--bd);border-radius:var(--r);padding:6px 12px;font-size:13px;font-family:var(--mono);cursor:pointer;outline:none}
.shape-sel select:focus{border-color:var(--ac)}

/* Precision overview table */
.poc{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px}
.poc th{background:var(--sf2);padding:9px 14px;text-align:center;font-size:11px;font-weight:600;color:var(--tx3);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--bd)}
.poc th:first-child{text-align:left}
.poc td{padding:9px 14px;border-bottom:1px solid var(--bdl);text-align:center;vertical-align:middle;cursor:pointer;transition:background .15s}
.poc td:first-child{text-align:left}
.poc tr:hover td{background:rgba(9,105,218,.03)}
.poc tr.sel td{background:rgba(9,105,218,.06);border-bottom-color:var(--ac)}
.poc tr:last-child td{border-bottom:none}

/* Metric cards */
.mg{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:12px;margin-bottom:16px}
.mc{background:var(--sf2);border:1px solid var(--bdl);border-radius:var(--r);padding:14px}
.mc-lbl{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--tx3);margin-bottom:5px}
.mc-val{font-size:22px;font-weight:700;font-family:var(--mono);letter-spacing:-.02em}
.mc-lim{font-size:11px;color:var(--tx3);margin-top:2px;font-family:var(--mono)}
.mc-bar{height:4px;border-radius:2px;background:var(--sf3);margin-top:8px;overflow:hidden}
.mc-fill{height:100%;border-radius:2px;transition:width .5s}
.mc-ok{color:var(--gn)}.mc-w{color:var(--or)}.mc-bad{color:var(--rd)}

/* Cross-case comparison chart */
.svg-chart{width:100%;overflow:visible}

/* ══ TAB 4: 性能 ══ */
.perf-summary{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.sp-card{background:var(--sf2);border:1px solid var(--bdl);border-radius:var(--r);padding:12px 14px;text-align:center;min-width:130px;max-width:200px;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-start}
.sp-val{font-size:28px;font-weight:800;font-family:var(--mono);letter-spacing:-.03em;line-height:1.1;text-align:center}
.sp-unit{font-size:11px;color:var(--tx2);margin-top:2px;text-align:center}
.sp-shape{font-size:11px;color:var(--tx3);font-family:var(--mono);margin-top:4px;max-width:170px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center}
.sp-timing{font-size:10px;color:var(--tx3);margin-top:2px;text-align:center}
.sp-good{color:var(--gn)}.sp-ok{color:var(--or)}.sp-slow{color:var(--rd)}
/* tiling analysis */
.til-dims{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.til-block{background:var(--sf2);border:1px solid var(--bdl);border-radius:var(--r);padding:10px 16px;flex:1;min-width:140px}
.til-block-title{font-size:10px;color:var(--tx3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.til-block-val{font-size:18px;font-weight:700;font-family:var(--mono);color:var(--tx1)}
.til-block-note{font-size:11px;color:var(--tx3);margin-top:2px}
.til-insight{margin-top:10px;padding:10px 14px;background:var(--sf2);border-left:3px solid var(--ac);border-radius:0 var(--r) var(--r) 0;font-size:12px;color:var(--tx2);line-height:1.6}
.bal-bar{display:inline-block;width:48px;height:6px;background:var(--bdl);border-radius:3px;vertical-align:middle;margin-left:4px;overflow:hidden}
.bal-fill{height:100%;border-radius:3px;background:var(--gn)}

.chart-wrap{position:relative;width:100%}
.chart-title{font-size:12px;color:var(--tx2);margin-bottom:8px;font-weight:600}

/* Perf note */
.pnote{font-size:12px;color:var(--tx2);background:rgba(9,105,218,.05);border:1px solid rgba(9,105,218,.12);border-radius:var(--r);padding:10px 14px;line-height:1.7}
.pnote b{color:var(--ac)}

/* ── responsive ── */
@media(max-width:700px){
  .hdr,.tab-bar,.content{padding-left:16px;padding-right:16px}
  .mg{grid-template-columns:1fr 1fr}
  .perf-summary{flex-direction:column}
}

/* ══ Analysis markdown rendering (panels/*.md) ══ */
.ana-section{margin-bottom:16px;padding:16px 18px;background:var(--sf2);
  border-left:3px solid var(--ac);border-radius:0 var(--r) var(--r) 0}
.ana-section .ana-origin{font-size:10px;color:var(--tx3);margin-bottom:10px;
  font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.ana-h2{font-size:14px;font-weight:700;margin:14px 0 6px;color:var(--tx);
  padding-bottom:4px;border-bottom:1px solid var(--bdl)}
.ana-h2:first-child{margin-top:0}
.ana-h3{font-size:13px;font-weight:600;margin:10px 0 4px;color:var(--tx2)}
.ana-p{font-size:13px;color:var(--tx2);line-height:1.65;margin:4px 0}
.ana-list{font-size:13px;color:var(--tx2);margin:4px 0 4px 18px;line-height:1.65}
.ana-list li{margin:2px 0}
.ana-tbl{border-collapse:collapse;font-size:12px;margin:8px 0;width:100%}
.ana-tbl th{background:var(--sf3);padding:6px 10px;font-size:11px;font-weight:600;
  color:var(--tx3);text-align:left;border-bottom:1px solid var(--bd)}
.ana-tbl td{padding:6px 10px;border-bottom:1px solid var(--bdl);color:var(--tx2)}
.ana-tbl tr:last-child td{border-bottom:none}

/* ══ Data Health bar ══ */
.dh-bar{border:1px solid var(--bdl);border-radius:var(--r);margin-bottom:12px;
  font-size:12px;overflow:hidden}
.dh-hdr{display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;
  background:var(--sf2);user-select:none;font-weight:600;font-size:12px;color:var(--tx2)}
.dh-hdr:hover{background:var(--sf3)}
.dh-counts{display:flex;gap:8px;margin-left:auto;font-weight:400}
.dh-body{display:none;padding:8px 14px 10px}
.dh-body.open{display:block}
.dh-item{display:flex;align-items:baseline;gap:8px;padding:4px 0;
  border-bottom:1px solid var(--bdl);font-size:12px}
.dh-item:last-child{border-bottom:none}
.dh-icon{font-weight:700;min-width:14px}
.dh-msg{color:var(--tx2);flex:1}
.dh-hint{color:var(--tx3);font-size:11px;font-family:var(--mono)}
.dh-found .dh-icon{color:var(--gn)}.dh-derived .dh-icon{color:var(--or)}
.dh-missing .dh-icon{color:var(--rd)}
.dh-found-c{color:var(--gn);font-weight:600}
.dh-derived-c{color:var(--or);font-weight:600}
.dh-missing-c{color:var(--rd);font-weight:600}

/* ══ Precision v2 ══ */
.prec-heat-bar{display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:12px;color:var(--tx2);flex-wrap:wrap}
.prec-heat-bar label{font-weight:600}
.prec-heat-bar select{background:var(--sf);color:var(--tx);border:1px solid var(--bd);border-radius:var(--r);padding:4px 8px;font-size:12px;font-family:inherit;cursor:pointer;outline:none}
.prec-heat-bar select:focus{border-color:var(--ac)}
.heat-legend-wrap{display:flex;align-items:center;gap:6px;margin-left:auto}
.heat-grad-bar{width:120px;height:8px;border-radius:4px;border:1px solid var(--bdl);position:relative}
.heat-grad-ticks{position:relative;width:120px;height:12px}
.heat-tick{position:absolute;transform:translateX(-50%);font-size:9px;font-family:var(--mono);color:var(--tx3)}
.heat-lbl{font-size:10px;font-family:var(--mono);color:var(--tx3)}
.prec-kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:14px}
.prec-kpi{background:var(--sf2);border:1px solid var(--bdl);border-radius:var(--r);padding:10px 12px}
.prec-kpi .k{font-size:10px;color:var(--tx3);text-transform:uppercase;letter-spacing:.05em;font-weight:700}
.prec-kpi .v{font-size:20px;font-family:var(--mono);font-weight:800;line-height:1.15;margin-top:3px}
.prec-kpi .n{font-size:11px;color:var(--tx3);margin-top:2px}
/* Precision summary table v2 */
.pst{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}
.pst thead th{background:var(--sf2);padding:8px 12px;text-align:center;font-size:10px;font-weight:700;color:var(--tx3);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:2}
.pst thead th:first-child{text-align:left;min-width:130px}
.pst tbody td{padding:8px 12px;text-align:center;border-bottom:1px solid var(--bdl);vertical-align:middle;transition:background .15s}
.pst tbody td:first-child{text-align:left}
.pst tbody tr.pst-case{cursor:pointer}
.pst tbody tr.pst-case:hover td{background:rgba(9,105,218,.04)}
.pst tbody tr.pst-case.pst-open td{background:rgba(9,105,218,.05);border-bottom-color:var(--ac)}
.pst-name{font-weight:600;font-size:12px}
.pst-shape{font-size:10px;color:var(--tx3);font-family:var(--mono);margin-top:2px}
.pst-metric-val{font-size:11px;font-family:var(--mono);color:var(--tx2)}
/* Expandable detail row */
.pst-detail{display:none}.pst-detail.pst-open{display:table-row}
.pst-dpanel{background:var(--sf2);padding:16px 20px;border-top:2px solid var(--ac)}
.pst-charts{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-bottom:14px}
.pst-chart-box{background:var(--sf);border:1px solid var(--bdl);border-radius:var(--r);padding:12px}
.pst-chart-box h5{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--tx3);margin-bottom:8px}
.pst-chart-box canvas{max-height:160px}
/* Threshold table */
.pst-thr{width:100%;border-collapse:collapse;font-size:11px;margin-top:10px}
.pst-thr th,.pst-thr td{padding:5px 10px;border:1px solid var(--bdl);text-align:center}
.pst-thr th{background:var(--sf);color:var(--tx3);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.03em}
.pst-thr td:first-child{text-align:left;font-weight:600;color:var(--tx2)}
.thr-ok{background:rgba(26,127,55,.08);color:var(--gn)}
.thr-warn{background:rgba(191,135,0,.08);color:var(--or)}
.thr-fail{background:rgba(207,34,46,.08);color:var(--rd)}
/* Floating tooltip */
.prec-tip{display:none;position:fixed;z-index:9999;background:var(--sf);border:1px solid var(--bd);
  border-radius:var(--rl);padding:10px 14px;font-size:11px;line-height:1.7;min-width:200px;max-width:300px;
  box-shadow:0 8px 24px rgba(0,0,0,.18);pointer-events:none}
.prec-tip.vis{display:block}
.prec-tip-title{font-weight:700;margin-bottom:5px;color:var(--ac);font-size:12px}
.prec-tip-row{display:flex;justify-content:space-between;gap:10px}
.prec-tip-lbl{color:var(--tx2)}.prec-tip-val{font-family:var(--mono);color:var(--tx)}

/* ══ Perf v2 ══ */
.perf-hist-wrap{position:relative;width:100%}
.perf-hist-wrap canvas{max-height:200px}
.case-sel-bar{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.case-sel-bar label{font-size:12px;font-weight:600;color:var(--tx2);white-space:nowrap}
.case-sel-bar select{background:var(--sf);color:var(--tx);border:1px solid var(--bd);border-radius:var(--r);
  padding:6px 12px;font-size:13px;font-family:var(--mono);cursor:pointer;outline:none;flex:1;max-width:380px}
.case-sel-bar select:focus{border-color:var(--ac)}
/* KPI hero cards */
.kpi-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.kpi-card{background:var(--sf2);border:1px solid var(--bdl);border-radius:var(--r);padding:11px 14px;flex:1;min-width:110px}
.kpi-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--tx3);margin-bottom:4px}
.kpi-val{font-size:20px;font-weight:800;font-family:var(--mono);letter-spacing:-.02em;color:var(--tx);line-height:1.1}
.kpi-unit{font-size:10px;color:var(--tx3);margin-top:2px}
/* AIV/AIC time breakdown bar */
.breakdown-title{font-size:11px;font-weight:700;color:var(--tx2);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.breakdown-stack{height:28px;border-radius:var(--r);overflow:hidden;display:flex;border:1px solid var(--bdl);background:var(--sf3);margin-bottom:6px}
.breakdown-seg{display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:#fff;overflow:hidden;transition:all .2s;cursor:default}
.breakdown-seg:hover{opacity:.78}
.breakdown-legend{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.breakdown-legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--tx2)}
.breakdown-legend-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}
/* Charts grid */
.perf-detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}
.perf-detail-grid.three-cols{grid-template-columns:1fr 1fr 1fr}
.perf-chart-card{background:var(--sf);border:1px solid var(--bdl);border-radius:var(--r);padding:13px}
.perf-chart-card h5{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--tx3);margin-bottom:8px}
.perf-chart-card canvas{max-height:160px}
/* Op summary table */
.ops-tbl{width:100%;border-collapse:collapse;font-size:12px}
.ops-tbl th{background:var(--sf2);padding:6px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--tx3);text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd)}
.ops-tbl td{padding:6px 12px;border-bottom:1px solid var(--bdl)}
.ops-tbl tr:last-child td{border-bottom:none}
.ops-key{color:var(--tx2);font-weight:600;white-space:nowrap;min-width:160px}
.ops-val{font-family:var(--mono);color:var(--tx)}
@media(max-width:700px){.perf-detail-grid{grid-template-columns:1fr}.pst-charts{grid-template-columns:1fr}}
</style>
</head>
<body>

<!-- Header -->
<div class="hdr">
  <div class="hdr-row">
    <span class="hdr-name" id="hdr-name"></span>
    <span class="hdr-cat"  id="hdr-cat"></span>
    <span id="hdr-badges"></span>
  </div>
  <div class="chips" id="hdr-chips"></div>
  <p class="desc" id="hdr-desc"></p>
</div>

<!-- Tabs -->
<div class="tab-bar" id="main-tab-bar">
  <button class="tb active" data-tab="algo">⚙️ 算法图示</button>
  <button class="tb" data-tab="mem">🗄 内存 &amp; Tiling</button>
  <button class="tb" data-tab="prec">🎯 精度分析</button>
  <button class="tb" data-tab="perf">⚡ 性能报告</button>
</div>

<div class="content">

<!-- ══ Tab: 算法图示 ══ -->
<div class="tp active" id="tab-algo">
  <div class="dh-bar" id="dh-algo" style="display:none">
    <div class="dh-hdr" onclick="toggleDH('dh-algo')">▶ Data Health <span class="dh-counts" id="dh-algo-counts"></span></div>
    <div class="dh-body" id="dh-algo-body"></div>
  </div>
  <div id="algo-analysis-slot"></div>
  <div class="card">
    <div class="ct">
      <span class="ico">⚙️</span>计算逻辑流
      <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
        <label class="shape-bar" style="margin:0" for="shape-sel">
          <span>测试 Shape：</span>
          <select id="shape-sel" onchange="updateShapeVars()"></select>
        </label>
      </div>
    </div>
    <div class="flow-col" id="algo-flow"></div>
  </div>
  <div class="card">
    <div class="ct"><span class="ico">📋</span>算法步骤注释</div>
    <div id="algo-steps"></div>
  </div>
</div>

<!-- ══ Tab: 内存 & Tiling ══ -->
<div class="tp" id="tab-mem">
  <div class="dh-bar" id="dh-mem" style="display:none">
    <div class="dh-hdr" onclick="toggleDH('dh-mem')">▶ Data Health <span class="dh-counts" id="dh-mem-counts"></span></div>
    <div class="dh-body" id="dh-mem-body"></div>
  </div>
  <div class="card">
    <div class="ct"><span class="ico">🔪</span>Tiling 策略分析</div>
    <div id="tiling-strategy"></div>
    <div id="tiling-table" style="margin-top:14px"></div>
  </div>
  <div class="card">
    <div class="ct"><span class="ico">📦</span>UB 内存分配
      <span id="ub-badge" class="badge bi" style="margin-left:auto;font-size:11px"></span>
    </div>
    <div class="lbl" id="ub-header-lbl">Unified Buffer — 地址空间（单核视图）</div>
    <div id="ub-donut-container" style="margin:8px 0"></div>
    <div class="ub-bar" id="ub-bar" style="display:none"></div>
    <div class="ub-ruler" id="ub-ruler" style="display:none"></div>
    <div class="ub-labels" id="ub-labels" style="display:none"></div>
    <div id="ub-table" style="margin-top:16px"></div>
    <div id="ub-viz-slot"></div>
  </div>
  <div id="mem-analysis-slot"></div>
</div>

<!-- ══ Tab: 精度 ══ -->
<div class="tp" id="tab-prec">
  <div class="dh-bar" id="dh-prec" style="display:none">
    <div class="dh-hdr" onclick="toggleDH('dh-prec')">▶ Data Health <span class="dh-counts" id="dh-prec-counts"></span></div>
    <div class="dh-body" id="dh-prec-body"></div>
  </div>
  <div id="prec-fail-banner" style="display:none;margin:0 0 12px 0;padding:10px 14px;border-radius:6px;background:var(--er2,#fff0f0);border:1px solid var(--er1,#cf222e);color:var(--er3,#82071e);font-size:13px;line-height:1.6"></div>
  <div class="card">
    <div class="ct"><span class="ico">📊</span>精度总览
      <div id="prec-heat-bar" class="prec-heat-bar" style="margin-left:auto"></div>
    </div>
    <div id="prec-kpi-row" class="prec-kpi-row"></div>
    <div style="overflow-x:auto">
      <table class="pst" id="prec-table"></table>
    </div>
  </div>
  <div id="prec-analysis-slot"></div>
</div>

<!-- ══ Tab: 性能 ══ -->
<div class="tp" id="tab-perf">
  <div class="dh-bar" id="dh-perf" style="display:none">
    <div class="dh-hdr" onclick="toggleDH('dh-perf')">▶ Data Health <span class="dh-counts" id="dh-perf-counts"></span></div>
    <div class="dh-body" id="dh-perf-body"></div>
  </div>
  <div id="perf-prec-warn" style="display:none;margin:0 0 12px 0;padding:10px 14px;border-radius:6px;background:var(--er2,#fff8f0);border:1px solid var(--er1,#f97316);color:var(--er3,#9a3412);font-size:13px;line-height:1.5"></div>
  <!-- Overview histogram -->
  <div class="card">
    <div class="ct"><span class="ico">⚡</span>加速比概览
      <span id="perf-avg-badge" class="badge bi" style="margin-left:auto;font-size:11px"></span>
    </div>
    <div id="perf-cards">
      <div class="perf-hist-wrap"><canvas id="perf-hist-canvas"></canvas></div>
    </div>
    <svg id="perf-svg" style="display:none;height:0"></svg>
    <div class="pnote" id="perf-note" style="margin-top:12px"></div>
  </div>
  <!-- Case detail -->
  <div class="card" id="perf-case-detail-card">
    <div class="ct"><span class="ico">🔬</span>Case 详情
      <div class="case-sel-bar" style="margin:0 0 0 auto">
        <label>Shape：</label>
        <select id="perf-case-sel" onchange="showCaseDetail(parseInt(this.value))"></select>
      </div>
    </div>
    <div class="kpi-row" id="perf-kpi-row"></div>
    <div id="perf-aiv-section"></div>
    <div class="perf-detail-grid" id="perf-charts-grid"></div>
    <div id="perf-ops-detail"></div>
  </div>
  <div id="perf-analysis-slot"></div>
</div>

</div><!-- /content -->

<script>
// ═══════════════════════════════════════════════════
// DATA
// ═══════════════════════════════════════════════════
const D = __DATA__;

// ═══════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════
const $  = id => document.getElementById(id);
const el = (tag, cls, html) => { const e=document.createElement(tag); if(cls)e.className=cls; if(html!==undefined)e.innerHTML=html; return e; };
const fmtN = (v, d=3) => v==null?'—':Math.abs(v)<0.001?v.toExponential(2):v.toFixed(d);
const fmtErr = (v, d=5) => {
  if(v==null) return '—';
  const base = Math.abs(v)<0.001 ? v.toExponential(2) : v.toFixed(d);
  const av = Math.abs(v);
  if(av===0) return base;
  const p = Math.log2(av);
  const k = Math.round(p);
  const nearPow2 = Math.abs(p-k) < 1e-6;
  if(nearPow2){
    return `${base} (~2^${k})`;
  }
  return base;
};
const fmtKB= kb => kb>=1 ? kb.toFixed(1)+' KB' : (kb*1024).toFixed(0)+' B';
const spCls= sp => sp>=2?'sp-good':sp>=1.2?'sp-ok':'sp-slow';

function shapeAsBracket(shapeText){
  let t = (shapeText || '').trim();
  if(!t) return '[]';
  if(t.startsWith('[') && t.endsWith(']')) return t;
  if(t.startsWith('(') && t.endsWith(')')) t = t.slice(1, -1).trim();
  const parts = t.split(',').map(s => s.trim()).filter(Boolean);
  if(parts.length) return `[${parts.join(',')}]`;
  return `[${t}]`;
}

// Tensor block (matrix visualization)
function tensorBlock(name, shape, dtype, color){
  const sz=8, maxC=6;
  const gr=d=>typeof d==='string'?3:d<=128?2:d<=1024?3:d<=4096?5:6;
  const rows=shape.length>=2?gr(shape[shape.length-2]):2;
  const cols=gr(shape[shape.length-1]);
  let grid='';
  for(let r=0;r<Math.min(rows,maxC);r++){
    grid+='<div class="tr">';
    for(let c=0;c<Math.min(cols,maxC);c++){
      const op=(0.45+Math.random()*.5).toFixed(2);
      grid+=`<div class="tc" style="width:${sz}px;height:${sz}px;background:${color};opacity:${op}"></div>`;
    }
    grid+='</div>';
  }
  return `<div class="tv">
    <div class="tn" style="color:${color}">${name}</div>
    <div class="tg">${grid}</div>
    <div class="td">[${shape.join(', ')}]</div>
    <div class="td" style="color:var(--tx3)">${dtype}</div>
  </div>`;
}

// SVG bar chart helper
function svgBar(svgId, groups, series, colors, yLabel, groupTitles){
  const svg = $(svgId);
  if(!svg||!groups.length) return;
  const W=svg.parentElement.clientWidth||800, H=parseInt(svg.getAttribute('height')||200);
  const padL=50, padR=20, padT=20, padB=60;
  const chartW=W-padL-padR, chartH=H-padT-padB;
  const nGroups=groups.length, nSeries=series.length;
  const allVals=series.flatMap(s=>s.values).filter(v=>v!=null&&v>0);
  if(!allVals.length) return;
  const maxV=Math.max(...allVals)*1.15;
  const barW=Math.min(40, (chartW/nGroups/nSeries)*0.8);
  const groupW=chartW/nGroups;
  let html='';

  // Y gridlines + labels
  for(let i=0;i<=4;i++){
    const v=maxV*i/4;
    const y=padT+chartH-(chartH*i/4);
    html+=`<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="var(--bdl)" stroke-width="1"/>`;
    html+=`<text x="${padL-6}" y="${y+4}" text-anchor="end" font-size="10" fill="var(--tx3)" font-family="var(--mono)">${v.toFixed(1)}</text>`;
  }
  // Y axis label
  html+=`<text x="12" y="${padT+chartH/2}" text-anchor="middle" font-size="10" fill="var(--tx3)" transform="rotate(-90,12,${padT+chartH/2})">${yLabel||''}</text>`;

  // Bars
  series.forEach((s,si)=>{
    groups.forEach((g,gi)=>{
      const v=s.values[gi];
      if(v==null||v<=0) return;
      const barH=Math.max(2,(v/maxV)*chartH);
      const x=padL+gi*groupW+(groupW-(nSeries*barW+(nSeries-1)*2))/2+si*(barW+2);
      const y=padT+chartH-barH;
      const fullLabel=groupTitles?groupTitles[gi]:g;
      html+=`<rect x="${x}" y="${y}" width="${barW}" height="${barH}" fill="${colors[si]||'#888'}" rx="2" opacity="0.85">
        <title>${fullLabel}\n${s.name}: ${v.toFixed(2)}</title>
      </rect>`;
      if(barH>16){
        html+=`<text x="${x+barW/2}" y="${y+barH/2+4}" text-anchor="middle" font-size="9" fill="#fff" font-weight="600">${v.toFixed(1)}</text>`;
      } else {
        html+=`<text x="${x+barW/2}" y="${y-3}" text-anchor="middle" font-size="9" fill="var(--tx3)">${v.toFixed(1)}</text>`;
      }
    });
  });

  // X labels — short, with tooltip via <title> on surrounding group rect
  groups.forEach((g,gi)=>{
    const x=padL+gi*groupW+groupW/2;
    const fullLabel=groupTitles?groupTitles[gi]:g;
    const label=g.length>12?g.slice(0,11)+'…':g;
    // Invisible rect for group hover tooltip
    html+=`<rect x="${padL+gi*groupW}" y="${padT}" width="${groupW}" height="${chartH+padB}" fill="transparent">
      <title>${fullLabel}</title></rect>`;
    html+=`<text x="${x}" y="${H-padB+18}" text-anchor="middle" font-size="10" fill="var(--tx2)" font-family="var(--mono)">${label}</text>`;
  });

  // Legend
  series.forEach((s,si)=>{
    const lx=padL+si*100;
    html+=`<rect x="${lx}" y="${H-14}" width="10" height="10" fill="${colors[si]}" rx="2"/>`;
    html+=`<text x="${lx+14}" y="${H-4}" font-size="10" fill="var(--tx2)">${s.name}</text>`;
  });

  svg.setAttribute('width', W);
  svg.innerHTML = html;
}

// ═══════════════════════════════════════════════════
// HEADER
// ═══════════════════════════════════════════════════
function buildHeader(){
  document.title = D.op_name+' — AscendC Dashboard';
  $('hdr-name').textContent = D.op_name;
  if(D.category) $('hdr-cat').textContent = D.category;

  // badges
  const badges = $('hdr-badges');
  if(D.n_total>0){
    const allPass = D.n_pass===D.n_total;
    const b=el('span','badge '+(allPass?'bp':'bf'));
    b.textContent = allPass ? `✓ ${D.n_pass}/${D.n_total} PASS` : `✗ ${D.n_pass}/${D.n_total} PASS`;
    badges.appendChild(b);
  }

  // chips
  const chip=(label,val,cls='')=>`<span class="chip ${cls}"><b>${label}</b> ${val}</span>`;
  let chips = chip('芯片', D.chip.name) + chip('UB', `${D.chip.ub_kb}KB × ${D.chip.aic}核`);
  if(D.input_shapes&&D.input_shapes[0]) chips+=chip('dtype', D.input_shapes[0].dtype||'');
  if(D.avg_speedup){
    const cls=D.avg_speedup>=2?'pass':D.avg_speedup>=1.2?'warn':'fail';
    chips+=chip('Avg Speedup',`${D.avg_speedup.toFixed(2)}x`,cls);
  }
  chips+=chip('Cases', `${D.n_pass}/${D.n_total}`);
  $('hdr-chips').innerHTML = chips;
  $('hdr-desc').textContent = D.description||'';
}

// ═══════════════════════════════════════════════════
// TAB 1: 算法图示（工业级计算逻辑流）
// ═══════════════════════════════════════════════════
let _flowHtmlTemplate = null;  // Claude flow.html 模板，供 shape 切换时重渲染

function _applyFlowShapeVars(template){
  const og = D.op_graph;
  if(!og || !og.shape_cases || !og.shape_cases.length) return template;
  const idx = parseInt(($('shape-sel')||{}).value) || 0;
  const vars = (og.shape_cases[idx] && og.shape_cases[idx].vars) || {};
  let result = template;
  Object.entries(vars).forEach(([k,v]) => { result = result.replaceAll('{'+k+'}', v); });
  return result;
}
function buildAlgo(){
  const og = D.op_graph;
  const P  = D.panels || {};

  // Populate shape selector
  const sel = $('shape-sel');
  const cases = (og && og.shape_cases) || [];
  cases.forEach((c,i) => {
    const opt = document.createElement('option');
    opt.value = i; opt.textContent = c.label;
    sel.appendChild(opt);
  });

  // ── 计算流程图：优先 Claude 生成的 flow.html，退回 JS 渲染 ──
  const flowDiv = $('algo-flow');
  if(P.algo && P.algo.flow_html && P.algo.flow_html.length > 50){
    _flowHtmlTemplate = P.algo.flow_html;   // 存模板，shape 切换时重渲染
    flowDiv.innerHTML = _applyFlowShapeVars(_flowHtmlTemplate);
  } else {
    renderOpGraph();
  }

  // ── 算法步骤：优先 Claude 生成的 steps.html，退回 pass_comments 列表 ──
  const stepsDiv = $('algo-steps');
  if(P.algo && P.algo.steps_html && P.algo.steps_html.length > 50){
    stepsDiv.innerHTML = P.algo.steps_html;
  } else {
    const comments = D.pass_comments || [];
    if(!comments.length){
      stepsDiv.innerHTML='<p style="color:var(--tx3);font-size:13px">（未找到 Pass 注释；请检查 kernel .cpp 注释格式，或运行精品流程生成 steps.html）</p>';
    } else {
      const ul = document.createElement('ul');
      ul.className = 'as-list';
      comments.forEach(c=>{
        const li=el('li');
        li.innerHTML=`<span style="font-family:var(--mono);font-size:12px;color:var(--tx2)">${c}</span>`;
        ul.appendChild(li);
      });
      stepsDiv.appendChild(ul);
    }
  }
}

function makeIONode(name, tmpl, dtype, kind){
  const d = el('div','');
  d.style.cssText='display:flex;justify-content:center;width:100%';
  const inner = el('div','io-node');
  const isIn = kind==='input';
  inner.style.borderColor = isIn ? 'var(--ac)' : 'var(--gn)';
  inner.innerHTML=`
    <div class="io-lbl">${isIn?'输入 Input':'输出 Output'}</div>
    <div class="io-name" style="color:${isIn?'var(--ac)':'var(--gn)'}">${name}</div>
    <div class="io-shape"><span data-sv="${tmpl}">${shapeAsBracket(tmpl)}</span></div>
    <div class="io-dtype">${dtype}</div>`;
  d.appendChild(inner);
  return d;
}

function makeIORow(ioArray, kind){
  // Renders a flex row of IO nodes for multi-input or multi-output
  const row = el('div','');
  row.style.cssText='display:flex;justify-content:center;flex-wrap:wrap;gap:12px;width:100%';
  ioArray.forEach(io=>{
    const inner = el('div','io-node');
    const isIn = kind==='input';
    inner.style.borderColor = isIn ? 'var(--ac)' : 'var(--gn)';
    inner.innerHTML=`
      <div class="io-lbl">${isIn?'输入 Input':'输出 Output'}</div>
      <div class="io-name" style="color:${isIn?'var(--ac)':'var(--gn)'}">${io.name||'?'}</div>
      <div class="io-shape"><span data-sv="${io.tmpl||''}">${shapeAsBracket(io.tmpl||'')}</span></div>
      <div class="io-dtype">${io.dtype||''}</div>`;
    row.appendChild(inner);
  });
  return row;
}

function makeFlowArrow(){
  return el('div','flow-arrow','▼');
}

function renderOpGraph(){
  const og = D.op_graph;
  const flow = $('algo-flow');
  flow.innerHTML = '';
  if(!og){ flow.innerHTML='<p style="color:var(--tx3)">（无算子图数据）</p>'; return; }

  // Input IO nodes — use v2 inputs[] if available, fallback to legacy inp_name
  const inputArr = (og.inputs && og.inputs.length)
    ? og.inputs
    : [{name: og.inp_name, tmpl: og.inp_tmpl, dtype: og.inp_dtype}];
  flow.appendChild(makeIORow(inputArr, 'input'));

  // No units → contract-first guidance
  if(!og.units || og.units.length === 0){
    flow.appendChild(makeFlowArrow());
    const ph = el('div','');
    ph.style.cssText='text-align:center;padding:32px 20px;color:var(--tx2);background:var(--sf2);border:1.5px dashed var(--bd);border-radius:var(--rl);width:fit-content;max-width:540px;align-self:center';
    ph.innerHTML=`<div style="font-size:28px;margin-bottom:10px">📐</div>
      <div style="font-weight:700;margin-bottom:8px">计算流图需由 Claude 生成</div>
      <div style="font-size:12px;color:var(--tx3);line-height:1.9;font-family:var(--mono)">
        1. 阅读 <b>panels/algo/SPEC.md</b> 了解生成规则<br>
        2. 参考 <b>panels/algo/example_softmax.json</b> 格式<br>
        3. 校验：<b>python3 scripts/validate_contract.py algo_flow.json</b><br>
        4. 重新生成看板：加 <b>--algo-flow panels/algo/algo_flow.json</b> 参数
      </div>`;
    flow.appendChild(ph);
  } else {
    // Units
    og.units.forEach((unit, ui) => {
      flow.appendChild(makeFlowArrow());

      const grp = el('div','unit-group');
      grp.style.cssText=`background:${unit.bg};border:2px solid ${unit.accent}40;`;

      const hdr = el('div','unit-hdr');
      hdr.style.color = unit.accent;
      hdr.textContent = unit.label;
      grp.appendChild(hdr);

      const nodesRow = el('div','unit-nodes');
      unit.nodes.forEach((node, ni) => {
        if(ni>0) nodesRow.appendChild(el('div','unit-sep','→'));

        const nd = el('div','api-node');
        nd.style.borderLeft = `3px solid ${unit.accent}`;

        const sameShape = node.in_tmpl === node.out_tmpl;
        nd.innerHTML=`
          <div class="api-name" style="color:${unit.accent}">${node.api}</div>
          <div class="api-formula">${node.formula}</div>
          <div class="api-shape">
            <span data-sv="${node.in_tmpl}">${shapeAsBracket(node.in_tmpl)}</span>
            ${!sameShape ? ` → <span data-sv="${node.out_tmpl}">${shapeAsBracket(node.out_tmpl)}</span>` : ''}
          </div>`;
        nodesRow.appendChild(nd);
      });
      grp.appendChild(nodesRow);
      flow.appendChild(grp);
    });
  }

  flow.appendChild(makeFlowArrow());
  // Output IO nodes — use v2 outputs[] if available, fallback to legacy out_name
  const outputArr = (og.outputs && og.outputs.length)
    ? og.outputs
    : [{name: og.out_name, tmpl: og.out_tmpl, dtype: og.out_dtype}];
  flow.appendChild(makeIORow(outputArr, 'output'));

  // Apply current shape vars
  updateShapeVars();
}

function updateShapeVars(){
  const og = D.op_graph;
  // shape_cases may be null (auto-generated flow) or empty array — guard both
  if(!og || !og.shape_cases || !og.shape_cases.length) return;
  // Claude flow.html: 重新注入带 shape 替换的模板
  if(_flowHtmlTemplate){
    $('algo-flow').innerHTML = _applyFlowShapeVars(_flowHtmlTemplate);
  }
  const idx = parseInt($('shape-sel').value) || 0;
  const vars = og.shape_cases[idx] && og.shape_cases[idx].vars || {};
  document.querySelectorAll('[data-sv]').forEach(node => {
    let text = node.getAttribute('data-sv');
    Object.entries(vars).forEach(([k,v]) => {
      text = text.replaceAll('{'+k+'}', v);
    });
    node.textContent = shapeAsBracket(text);
  });
}

// ═══════════════════════════════════════════════════
// TAB 2: 内存 & Tiling
// ═══════════════════════════════════════════════════
function buildMemory(){
  const bufs = D.ub_buffers||[];
  const total = D.ub_total_kb, used = D.ub_used_kb;
  const tc = D.tiling.consts||{};
  const aic = D.chip.aic||32;

  // ── 更新 UB 头部标题（动态填入真实 KB 数）──
  const hdrLbl = $('ub-header-lbl');
  if(hdrLbl) hdrLbl.textContent = `Unified Buffer — ${total} KB 地址空间（单核视图）`;

  // ── Tiling 策略分析 ──────────────────────────────
  const strategy = $('tiling-strategy');
  const L1_M=tc.L1_M||tc['L1Shape_M'], L1_N=tc.L1_N||tc['L1Shape_N'], L1_K=tc.L1_K||tc['L1Shape_K'];
  const EP_M=tc.EPILOGUE_TILE_M||tc.ep_tile_m;
  const WS=tc.WORKSPACE_STAGES||1;

  // Cube/CV 算子：L1 tile 维度块
  if(L1_M||L1_N||L1_K){
    const dims=`<div class="til-dims">
      ${L1_M&&L1_N?`<div class="til-block">
        <div class="til-block-title">AIC Cube Tile (M×N)</div>
        <div class="til-block-val">${L1_M} × ${L1_N}</div>
        <div class="til-block-note">${L1_K?`K stride = ${L1_K}`:''}</div>
      </div>`:''}
      ${EP_M&&L1_N?`<div class="til-block">
        <div class="til-block-title">AIV Vector Epilogue</div>
        <div class="til-block-val">${EP_M} × ${L1_N}</div>
        <div class="til-block-note">per epilogue tile</div>
      </div>`:''}
      ${WS?`<div class="til-block">
        <div class="til-block-title">双缓冲 Pipeline</div>
        <div class="til-block-val">${WS} stages</div>
        <div class="til-block-note">AIC↔AIV 流水深度</div>
      </div>`:''}
      <div class="til-block">
        <div class="til-block-title">AIC 核心数</div>
        <div class="til-block-val">${aic}</div>
        <div class="til-block-note">${D.chip.name||'Ascend'}</div>
      </div>
    </div>`;
    strategy.innerHTML=dims;
  } else {
    // Vector 算子：展示 BLOCK_DIM + tileSize 等向量 tiling 参数
    const blockDim = tc.BLOCK_DIM||tc.blockDim||tc.BLOCK_NUM;
    const tileSize = tc.tileSize||tc.TILE_SIZE||tc.tile_size||tc.TILE_LENGTH||tc.tile_length;
    const tileKB   = tileSize ? (tileSize * (D.tiling.dtype_bytes||4) / 1024).toFixed(1) : null;
    const tilePar  = D.tiling.tiling_params||[];
    if(blockDim||tileSize){
      const pblocks = [
        blockDim ? `<div class="til-block">
          <div class="til-block-title">AIV 核心数</div>
          <div class="til-block-val">${blockDim}</div>
          <div class="til-block-note">${D.chip.name||'Ascend'}</div>
        </div>` : '',
        tileSize ? `<div class="til-block">
          <div class="til-block-title">Tile 大小</div>
          <div class="til-block-val">${tileSize} 元素</div>
          <div class="til-block-note">${tileKB ? tileKB+' KB / tile' : ''}</div>
        </div>` : '',
        tileSize && blockDim ? `<div class="til-block">
          <div class="til-block-title">UB 利用率</div>
          <div class="til-block-val">${used} / ${total} KB</div>
          <div class="til-block-note">${total ? ((used/total)*100).toFixed(1)+'%' : ''}</div>
        </div>` : '',
      ].filter(Boolean).join('');
      strategy.innerHTML = `<div class="til-dims">${pblocks}</div>`;
      if(tilePar.length){
        strategy.innerHTML += `<div style="margin-top:10px;font-size:12px;color:var(--tx2);font-family:var(--mono)">
          Tiling params: ${tilePar.join(', ')}</div>`;
      }
    }
  }

  // Per-case load analysis table
  const ta = D.tiling.analysis||[];
  if(ta.length){
    let thead=`<table class="dt" style="width:100%">
      <thead><tr>
        <th>Case</th><th>M × K × N</th>
        <th>AIC Tiles</th><th>尾块</th>
        <th>Tiles/Core</th><th>负载均衡</th>
      </tr></thead>`;
    let tbody='<tbody>';
    ta.forEach(r=>{
      const tStr=r.tiles_m!=null?`${r.tiles_m}×${r.tiles_n}=${r.total_tiles}`:`${r.tiles_n} tiles`;
      const tailStr=r.has_tail
        ?`<span style="color:var(--or)">✓ ${[r.tail_m?'M':'',r.tail_k?'K':'',r.tail_n?'N':''].filter(Boolean).join('+')}</span>`
        :`<span style="color:var(--tx3)">无</span>`;
      const balCls=r.balance_pct===100?'color:var(--gn)':r.balance_pct>=50?'color:var(--or)':'color:var(--rd)';
      const balBar=`<span class="bal-bar"><span class="bal-fill" style="width:${r.balance_pct}%;background:${r.balance_pct===100?'var(--gn)':r.balance_pct>=50?'var(--or)':'var(--rd)'}"></span></span>`;
      const starStr=r.balance_pct===100?' <b style="color:var(--gn)">★</b>':'';
      tbody+=`<tr>
        <td style="font-family:var(--mono);font-size:12px;color:var(--tx2)">${r.case_name}</td>
        <td style="font-family:var(--mono);font-size:12px">${r.M||'?'}×${r.K||'?'}×${r.N||'?'}</td>
        <td class="val">${tStr}</td>
        <td>${tailStr}</td>
        <td class="val">${r.tiles_per_core}</td>
        <td><span style="${balCls};font-weight:600">${r.balance_pct}%</span>${balBar}${starStr}</td>
      </tr>`;
    });
    tbody+='</tbody></table>';
    const tDiv=el('div');
    tDiv.innerHTML=thead+tbody;
    strategy.appendChild(tDiv);

    // Insight text
    const tailCases=ta.filter(r=>r.has_tail);
    const perfectCases=ta.filter(r=>r.balance_pct===100);
    const worstBal=Math.min(...ta.map(r=>r.balance_pct));
    let insight='';
    if(tailCases.length)
      insight+=`<b>尾块处理：</b>${tailCases.map(r=>r.case_name).join('、')} 含非对齐尾块（M/N 不整除 tile size），内核需在边界做条件判断或 pad 处理。`;
    if(insight) insight+='<br>';
    if(perfectCases.length)
      insight+=`<b>完美均衡：</b>${perfectCases.map(r=>r.case_name).join('、')} tiles = ${aic} 的整数倍，所有 AIC 核满载。`;
    else if(worstBal<50)
      insight+=`<b>负载不均：</b>最低均衡率 ${worstBal}%，建议调整 tile 尺寸或测试 shape 覆盖更大规模。`;
    if(insight){
      const ins=el('div','til-insight');
      ins.innerHTML=insight;
      strategy.appendChild(ins);
    }
  } else if(Object.keys(tc).length===0){
    // No constants found — show fallback tiling params
    const fallback=el('div','til-insight');
    fallback.innerHTML='<b>未解析到 constexpr tile 常量</b>：请提供 <code>op_host/*.cpp</code> 文件路径。<br>'
      +(D.tiling.tiling_params&&D.tiling.tiling_params.length
        ?`Tiling 参数：${D.tiling.tiling_params.join(', ')}`:'');
    strategy.appendChild(fallback);
  }

  // Simplified constants table (right panel info)
  const til=$('tiling-table');
  const KNOWN=[
    ['L1Shape_M','AIC tile M'],['L1Shape_N','AIC tile N'],['L1Shape_K','AIC tile K'],
    ['L1_M','AIC tile M'],['L1_N','AIC tile N'],['L1_K','AIC tile K'],
    ['EPILOGUE_TILE_M','AIV epilogue M'],['WORKSPACE_STAGES','双缓冲 stages'],
  ];
  const kvRows=[];
  const seen=new Set();
  KNOWN.forEach(([k,desc])=>{
    if(tc[k]!=null&&!seen.has(desc)){kvRows.push([desc,tc[k]]); seen.add(desc);}
  });
  if(kvRows.length){
    let html=`<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">`;
    kvRows.forEach(([label,val])=>{
      html+=`<div style="background:var(--sf3);border:1px solid var(--bdl);border-radius:6px;padding:5px 10px;font-size:12px">
        <span style="color:var(--tx3)">${label}</span>
        <span style="font-family:var(--mono);font-weight:700;margin-left:6px">${val}</span>
      </div>`;
    });
    html+='</div>';
    til.innerHTML=html;
  }

  // ── UB Memory ──────────────────────────────────
  const ubOverflow = used > total;
  const ubBadge = $('ub-badge');
  if(ubOverflow){
    ubBadge.textContent = `${used} KB / ${total} KB — ⚠ 估算值超出 UB`;
    ubBadge.style.background = '#ffeaea';
    ubBadge.style.color = '#cf222e';
    ubBadge.style.borderColor = '#cf222e44';
  } else {
    ubBadge.textContent = `${used} KB / ${total} KB — ${D.ub_util_pct}% 占用`;
  }

  // Detect multi-kernel groups (e.g. K1 / K2)
  const groups = [...new Set(bufs.map(b=>b.kernel_group||'').filter(g=>g))];
  const isMultiKernel = groups.length > 1;

  function renderUBBar(container, barBufs, barTotal) {
    const barUsed = barBufs.reduce((s,b)=>s+b.size_kb,0);
    const utilPct  = barTotal > 0 ? barUsed / barTotal * 100 : 0;
    const lowUtil  = utilPct < 25; // 当利用率 < 25% 时启用放大视图

    // ── 主条形图（全尺度，精确比例）──
    const barLbl = el('div');
    barLbl.style.cssText='font-size:10px;color:var(--tx3);font-family:var(--mono);margin-bottom:2px';
    barLbl.textContent = lowUtil ? `全尺度 (0–${barTotal} KB)` : '';
    if(lowUtil) container.appendChild(barLbl);

    const bar = el('div','ub-bar');
    const barScale = utilPct > 100 ? barUsed : barTotal; // 溢出时以实际使用量为 100% 基准
    barBufs.forEach(b=>{
      const pct=(b.size_kb/barScale*100).toFixed(2);
      const seg=el('div','ub-seg');
      seg.style.cssText=`width:${pct}%;background:${b.color}`;
      seg.title=`${b.name}  ${fmtKB(b.size_kb)}  (${pct}%)`;
      if(parseFloat(pct)>10) seg.textContent=b.name.length>9?b.name.slice(0,7)+'…':b.name;
      bar.appendChild(seg);
    });
    if(utilPct <= 100){
      const freePct=((barTotal-barUsed)/barTotal*100).toFixed(2);
      const f=el('div','ub-seg ub-free');
      f.style.width=freePct+'%'; f.title=`空闲  ${fmtKB(barTotal-barUsed)}  (${freePct}%)`;
      if(parseFloat(freePct)>8) f.textContent='空闲';
      bar.appendChild(f);
    }
    container.appendChild(bar);

    // ── 刻度尺 ──
    const ruler=el('div','ub-ruler');
    [0,64,128,192,256].filter(kb=>kb<=barTotal).forEach(kb=>{
      const t=el('div','ub-tick',`${kb}KB`);
      t.style.left=`${kb/barTotal*100}%`;
      ruler.appendChild(t);
    });
    container.appendChild(ruler);

    // ── 放大视图（仅低利用率时显示：按使用区域比例展开至全宽）──
    if(lowUtil && barBufs.length > 0){
      const zoomLbl = el('div');
      zoomLbl.style.cssText='font-size:10px;color:var(--ac);font-family:var(--mono);margin:8px 0 2px;font-weight:600';
      zoomLbl.textContent = `⬛ 已分配区域放大 (0–${fmtKB(barUsed)}, 各 buffer 等比)`;
      container.appendChild(zoomLbl);

      const zoomBar = el('div','ub-bar');
      zoomBar.style.cssText='height:28px;border-radius:4px;overflow:hidden;display:flex;border:1px solid var(--bd)';
      barBufs.forEach(b=>{
        const pct = barUsed > 0 ? (b.size_kb / barUsed * 100).toFixed(2) : 0;
        const seg = el('div','ub-seg');
        seg.style.cssText=`width:${pct}%;background:${b.color};min-width:0`;
        seg.title=`${b.name}  ${fmtKB(b.size_kb)}`;
        seg.textContent = b.name;
        zoomBar.appendChild(seg);
      });
      container.appendChild(zoomBar);

      const zoomRuler = el('div','ub-ruler');
      // 刻度按使用量等分
      const steps = Math.min(barBufs.length, 4);
      for(let i=0; i<=steps; i++){
        const kb = (barUsed / steps * i).toFixed(1);
        const t = el('div','ub-tick', `${kb}KB`);
        t.style.left = `${(i/steps*100).toFixed(1)}%`;
        zoomRuler.appendChild(t);
      }
      container.appendChild(zoomRuler);
    }

    // ── 图例标签 ──
    const row = el('div','ub-labels-row');
    barBufs.forEach(b=>{
      const chip = el('div','ub-label-chip');
      chip.title = `${b.kind} @ ${b.position}`;
      const sw = el('div','ub-label-swatch');
      sw.style.background = b.color;
      const lbl = el('span');
      lbl.textContent = `${b.name}  ${fmtKB(b.size_kb)}`;
      chip.appendChild(sw); chip.appendChild(lbl);
      row.appendChild(chip);
    });
    const fc = el('div','ub-label-chip');
    const fs = el('div','ub-label-swatch');
    fs.style.background = 'var(--sf3)';
    fs.style.border = '1px solid var(--bd)';
    const fl = el('span'); fl.style.color='var(--tx3)';
    // 当利用率低时补充设计建议（避免基于固定 buffer 数量和 dtype 的硬编码公式）
    const suggestion = lowUtil ? `  ⚠ 当前 ${utilPct.toFixed(1)}% 利用率，建议适当增大 tileSize 以提高 UB 利用率和性能` : '';
    fl.textContent = `空闲  ${fmtKB(barTotal-barUsed)}${suggestion}`;
    fc.appendChild(fs); fc.appendChild(fl); row.appendChild(fc);
    container.appendChild(row);
  }

  function renderUBDonut(container, barBufs, barTotal) {
    const used = barBufs.reduce((s,b)=>s+b.size_kb, 0);
    const free = barTotal - used;
    const overflow = free < 0;
    const W = 200, H = 200, cx = W/2, cy = H/2, R = 80, r = 50;

    // 当估算值超出 UB 总量时（通常因 tileLength 回退估算），仅显示各 buffer 比例，不加"空闲"段
    const allSegs = overflow
      ? barBufs.map(b=>({label:b.name, kb:b.size_kb, color:b.color}))
      : [...barBufs.map(b=>({label:b.name, kb:b.size_kb, color:b.color})),
         {label:'空闲', kb:free, color:'#e8eaed'}];
    // 当溢出时以 used 为基准做比例，否则以 barTotal 为基准
    const pieBase = overflow ? used : barTotal;
    let startAngle = -Math.PI/2;

    const pathData = allSegs.map(seg => {
        const angle = (seg.kb / pieBase) * 2 * Math.PI;
        const endAngle = startAngle + angle;
        const x1 = cx + R * Math.cos(startAngle);
        const y1 = cy + R * Math.sin(startAngle);
        const x2 = cx + R * Math.cos(endAngle);
        const y2 = cy + R * Math.sin(endAngle);
        const xi1 = cx + r * Math.cos(startAngle);
        const yi1 = cy + r * Math.sin(startAngle);
        const xi2 = cx + r * Math.cos(endAngle);
        const yi2 = cy + r * Math.sin(endAngle);
        const large = angle > Math.PI ? 1 : 0;
        const d = `M${x1},${y1} A${R},${R},0,${large},1,${x2},${y2} L${xi2},${yi2} A${r},${r},0,${large},0,${xi1},${yi1} Z`;
        const result = {d, color: seg.color, label: seg.label, kb: seg.kb};
        startAngle = endAngle;
        return result;
    });

    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.style.cssText = 'display:block;margin:0 auto';

    pathData.forEach(seg => {
        const path = document.createElementNS(svgNS, 'path');
        path.setAttribute('d', seg.d);
        path.setAttribute('fill', seg.color);
        path.setAttribute('stroke', 'var(--bg)');
        path.setAttribute('stroke-width', '2');
        path.title = `${seg.label}: ${fmtKB(seg.kb)}`;
        const title = document.createElementNS(svgNS, 'title');
        title.textContent = `${seg.label}  ${fmtKB(seg.kb)}  (${(seg.kb/pieBase*100).toFixed(1)}%)`;
        path.appendChild(title);
        svg.appendChild(path);
    });

    // 中心文字：已用/总量（溢出时显示警告色）
    const centerColor = overflow ? '#cf222e' : 'var(--tx)';
    const t1 = document.createElementNS(svgNS, 'text');
    t1.setAttribute('x', cx); t1.setAttribute('y', cy - 8);
    t1.setAttribute('text-anchor', 'middle');
    t1.setAttribute('font-size', '14'); t1.setAttribute('font-weight', '700');
    t1.setAttribute('fill', centerColor);
    t1.textContent = fmtKB(used);
    const t2 = document.createElementNS(svgNS, 'text');
    t2.setAttribute('x', cx); t2.setAttribute('y', cy + 10);
    t2.setAttribute('text-anchor', 'middle');
    t2.setAttribute('font-size', '10'); t2.setAttribute('fill', 'var(--tx3)');
    t2.textContent = `/ ${fmtKB(barTotal)}`;
    const t3 = document.createElementNS(svgNS, 'text');
    t3.setAttribute('x', cx); t3.setAttribute('y', cy + 24);
    t3.setAttribute('text-anchor', 'middle');
    t3.setAttribute('font-size', '10');
    t3.setAttribute('fill', overflow ? '#cf222e' : 'var(--tx3)');
    t3.textContent = overflow ? `⚠ 估算值超出 UB` : `${(used/barTotal*100).toFixed(1)}% 已用`;
    svg.appendChild(t1); svg.appendChild(t2); svg.appendChild(t3);
    container.appendChild(svg);

    // 图例
    const row = el('div','ub-labels-row');
    row.style.justifyContent = 'center';
    barBufs.forEach(b=>{
        const chip = el('div','ub-label-chip');
        const sw = el('div','ub-label-swatch'); sw.style.background = b.color;
        const lbl = el('span'); lbl.textContent = `${b.name}  ${fmtKB(b.size_kb)}`;
        chip.appendChild(sw); chip.appendChild(lbl);
        row.appendChild(chip);
    });
    // 空闲 chip — 仅在未溢出时显示；溢出时显示估算警告
    const fc = el('div','ub-label-chip');
    const fs = el('div','ub-label-swatch'); fs.style.background='#e8eaed'; fs.style.border='1px solid var(--bd)';
    const fl = el('span');
    if(overflow){
      fl.style.color='#cf222e';
      fl.textContent = `⚠ 估算值超出单核 UB — buffer 大小基于 tileLength 推算，实际运行时由 Tiling 决定`;
    } else {
      fl.style.color='var(--tx3)';
      const suggestion = (used/barTotal) < 0.3 ? `  ⚠ 仅 ${(used/barTotal*100).toFixed(0)}%，建议增大 tileSize` : '';
      fl.textContent = `空闲  ${fmtKB(free)}${suggestion}`;
    }
    fc.appendChild(fs); fc.appendChild(fl); row.appendChild(fc);
    container.appendChild(row);
  }

  const donutContainer = $('ub-donut-container');
  const hasVizHtml = !!(D.panels && D.panels.memory && D.panels.memory.ub_viz_html
                        && D.panels.memory.ub_viz_html.length > 50);
  if(hasVizHtml){
    // Claude 写了 ub_viz.html，隐藏 JS 生成的 donut，避免重复
    if(donutContainer) donutContainer.style.display = 'none';
  } else if(isMultiKernel){
    // Multi-kernel: one sub-donut per group, each occupying full 256KB scale
    groups.forEach(grp=>{
      const grpBufs = bufs.filter(b=>(b.kernel_group||'')==grp);
      const grpUsed = grpBufs.reduce((s,b)=>s+b.size_kb,0);
      const wrap = el('div');
      wrap.style.cssText='margin-bottom:10px';
      const lbl=el('div');
      lbl.style.cssText='font-size:11px;font-weight:700;color:var(--tx2);margin-bottom:3px;font-family:var(--mono)';
      lbl.textContent=`${grp} UB  (${fmtKB(grpUsed)} / ${fmtKB(total)})`;
      wrap.appendChild(lbl);
      renderUBDonut(wrap, grpBufs, total);
      donutContainer.appendChild(wrap);
    });
  } else {
    renderUBDonut(donutContainer, bufs, total);
  }

  const ubTable=$('ub-table');
  const t=el('table','dt');
  t.innerHTML=`<thead><tr><th>缓冲区</th><th>类型</th><th>位置</th><th>大小</th><th>用途</th></tr></thead>`;
  const tb=el('tbody');
  bufs.forEach(b=>{
    const tr=el('tr');
    tr.innerHTML=`<td><span style="display:inline-flex;align-items:center;gap:6px">
        <span style="width:10px;height:10px;border-radius:2px;background:${b.color};flex-shrink:0;display:inline-block"></span>
        <span class="val" style="font-size:12px">${b.name}</span></span></td>
      <td><span class="pipe-tag" style="background:${b.color}22;color:${b.color};border:1px solid ${b.color}44">${b.kind}</span></td>
      <td><span class="pipe-tag" style="background:${b.color}14;color:${b.color}">${b.position}</span></td>
      <td><b class="val">${fmtKB(b.size_kb)}</b></td>
      <td style="color:var(--tx3);font-size:12px">${b.purpose||''}</td>`;
    tb.appendChild(tr);
  });
  const tot=el('tr');
  tot.innerHTML=`<td colspan="3" style="text-align:right;color:var(--tx2);font-size:12px">已用合计</td>
    <td><b class="val" style="color:var(--ac)">${fmtKB(used)}</b> / ${fmtKB(total)}</td><td></td>`;
  tb.appendChild(tot);
  t.appendChild(tb); ubTable.appendChild(t);

  // ── Claude-written UB 分配可视化（ub_viz.html）──
  const vizSlot = $('ub-viz-slot');
  const P = D.panels||{};
  if(vizSlot && P.memory && P.memory.ub_viz_html && P.memory.ub_viz_html.length > 50){
    vizSlot.innerHTML = P.memory.ub_viz_html;
  }
}

// ═══════════════════════════════════════════════════
// TAB 3: 精度 v2 — Chart.js + Heatmap + Expandable rows
// ═══════════════════════════════════════════════════
const PREC_COL_DEFS = [
  {key:'match_rate',   label:'MATCH %',   fmt:v=>v!=null?v.toFixed(1)+'%':'—',        isStr:true},
  {key:'max_re',       label:'MAX_RE',    fmt:v=>fmtN(v,4), thresh:10.0},
  {key:'mean_re',      label:'MEAN_RE',   fmt:v=>fmtN(v,4), thresh:2.0},
  {key:'rmse',         label:'RMSE',      fmt:v=>fmtN(v,5), thresh:2.0},
  {key:'max_diff',     label:'MAX_DIFF',  fmt:v=>fmtErr(v,5),       isAE:true},
  {key:'mean_diff',    label:'MEAN_DIFF', fmt:v=>fmtErr(v,5),       isAE:true},
  {key:'ae_max',       label:'AE_MAX',    fmt:v=>fmtErr(v,5),       isAE:true},
  {key:'mismatch_rate',label:'MISMATCH',  fmt:v=>v!=null?fmtN(v,4):'—'},
];
const precActiveCols = [];
const precCharts = {};
const precOpenRows = new Set();
const precHeatCells = [];
// Tooltip element (created once, reused)
const _precTip = document.createElement('div');
_precTip.className = 'prec-tip'; document.body.appendChild(_precTip);

function buildPrecision(){
  const cases = D.cases||[];
  if(!cases.length){
    $('prec-table').innerHTML='<tr><td colspan="99" style="color:var(--tx3);padding:16px">（无精度数据）</td></tr>';
    return;
  }

  // FAIL banner：精度未全通过时，顶部显示失败 case 汇总
  const failBanner=$('prec-fail-banner');
  if(failBanner){
    const failCases=cases.filter(c=>!(c.precision||{}).passed);
    if(failCases.length>0){
      failBanner.style.display='';
      failBanner.replaceChildren();

      const title=document.createElement('b');
      title.textContent=`✗ 精度未通过（${D.n_pass}/${D.n_total} PASS）— FAIL Case 诊断`;
      failBanner.appendChild(title);
      failBanner.appendChild(document.createElement('br'));

      const table=document.createElement('table');
      table.style.marginTop='6px';
      table.style.width='100%';
      table.style.fontSize='12px';
      table.style.borderCollapse='collapse';

      const thead=document.createElement('thead');
      const headRow=document.createElement('tr');
      headRow.style.textAlign='left';
      headRow.style.borderBottom='1px solid var(--er1,#cf222e)';
      ['Case','Shape','MAX_RE','MATCH%','MAX_DIFF'].forEach(label=>{
        const th=document.createElement('th');
        th.style.padding='3px 8px';
        th.textContent=label;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      const tbody=document.createElement('tbody');
      failCases.forEach(c=>{
        const p=c.precision||{};
        const maxre=p.max_re!=null?p.max_re.toFixed(4):'—';
        const mr=p.match_rate!=null?p.match_rate.toFixed(1)+'%':'—';
        const md=p.max_diff!=null?p.max_diff.toExponential(3):'—';

        const row=document.createElement('tr');
        row.style.borderBottom='1px solid rgba(207,34,46,.15)';

        const caseCell=document.createElement('td');
        caseCell.style.padding='3px 8px';
        caseCell.style.fontWeight='600';
        caseCell.textContent=c.name||('Case '+c.id);
        row.appendChild(caseCell);

        const shapeCell=document.createElement('td');
        shapeCell.style.padding='3px 8px';
        shapeCell.style.color='var(--tx3,#666)';
        shapeCell.style.fontSize='11px';
        shapeCell.textContent=c.shape||'';
        row.appendChild(shapeCell);

        const maxreCell=document.createElement('td');
        maxreCell.style.padding='3px 8px';
        maxreCell.textContent=maxre;
        row.appendChild(maxreCell);

        const mrCell=document.createElement('td');
        mrCell.style.padding='3px 8px';
        mrCell.textContent=mr;
        row.appendChild(mrCell);

        const mdCell=document.createElement('td');
        mdCell.style.padding='3px 8px';
        mdCell.textContent=md;
        row.appendChild(mdCell);

        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      failBanner.appendChild(table);

      const note=document.createElement('div');
      note.style.marginTop='6px';
      note.style.color='var(--er3,#82071e)';
      note.style.fontSize='12px';
      note.textContent='↳ 常见原因：输出全零（地址映射错误）、数值溢出、tiling 越界、类型转换截断。详见下方"FAIL Case 诊断"分析（需 Claude 分析阶段写入）。';
      failBanner.appendChild(note);
    } else {
      failBanner.style.display='none';
    }
  }

  // Detect active columns
  precActiveCols.length=0;
  PREC_COL_DEFS.forEach(col=>{
    if(cases.some(c=>c.precision&&c.precision[col.key]!=null)) precActiveCols.push(col);
  });

  // KPI row inspired by ascend_test_visualize summary cards
  const kpiRow=$('prec-kpi-row');
  if(kpiRow){
    const passCnt=cases.filter(c=>(c.precision||{}).passed).length;
    const allMetrics=cases.map(c=>c.precision||{});
    const aeMaxVals=allMetrics.map(p=>p.ae_max??p.max_diff).filter(v=>v!=null);
    const reMaxVals=allMetrics.map(p=>p.re_max??p.max_re).filter(v=>v!=null);
    const rmseVals=allMetrics.map(p=>p.rmse).filter(v=>v!=null);
    const maxOf=v=>v.length?Math.max(...v):null;
    kpiRow.innerHTML=`
      <div class="prec-kpi"><div class="k">Pass Ratio</div><div class="v">${passCnt}/${cases.length}</div><div class="n">${cases.length?((passCnt/cases.length)*100).toFixed(1):'0.0'}%</div></div>
        <div class="prec-kpi"><div class="k">Worst AE</div><div class="v">${maxOf(aeMaxVals)!=null?fmtErr(maxOf(aeMaxVals),5):'—'}</div><div class="n">ans_vs_golden</div></div>
      <div class="prec-kpi"><div class="k">Worst RE</div><div class="v">${maxOf(reMaxVals)!=null?fmtN(maxOf(reMaxVals),5):'—'}</div><div class="n">ans_vs_golden</div></div>
      <div class="prec-kpi"><div class="k">Worst RMSE</div><div class="v">${maxOf(rmseVals)!=null?fmtN(maxOf(rmseVals),5):'—'}</div><div class="n">cross-case</div></div>`;
  }

  // Heatmap selector bar
  const heatBar=$('prec-heat-bar');
  if(heatBar){
    const numCols=precActiveCols.filter(c=>!c.isStr&&!c.isAE);
    const opts=numCols.map(c=>`<option value="${c.key}">${c.label}</option>`).join('')+'<option value="">Off</option>';
    heatBar.innerHTML=`<label>Heatmap:</label>
      <select id="prec-heat-sel" onchange="applyPrecHeat(this.value)">${opts}</select>
      <div class="heat-legend-wrap" id="prec-heat-legend" style="display:none">
        <span class="heat-lbl" id="prec-hmin"></span>
        <div style="position:relative">
          <div class="heat-grad-bar" id="prec-hgrad"></div>
          <div class="heat-grad-ticks" id="prec-hticks"></div>
        </div>
        <span class="heat-lbl" id="prec-hmax"></span>
      </div>`;
  }

  // Build table
  const pt=$('prec-table');
  const thCols=precActiveCols.map(c=>`<th>${c.label}</th>`).join('');
  pt.innerHTML=`<thead><tr><th style="text-align:left">Case</th><th>精度</th>${thCols}</tr></thead>`;
  const tbody=document.createElement('tbody');

  cases.forEach((c,idx)=>{
    const p=c.precision||{};
    const pass=p.passed;
    const badge=pass
      ?'<span class="badge bp" style="font-size:10px">✓ PASS</span>'
      :'<span class="badge bf" style="font-size:10px">✗ FAIL</span>';

    const caseRow=document.createElement('tr');
    caseRow.className='pst-case'; caseRow.id=`pcr-${idx}`;
    caseRow.onclick=()=>togglePrecDetail(idx);

    const tdCols=precActiveCols.map(col=>{
      const val=p[col.key];
      return `<td class="pst-metric-val" data-val="${val!=null?val:''}" data-col="${col.key}">${col.fmt(val)}</td>`;
    }).join('');

    caseRow.innerHTML=`<td>
        <div class="pst-name">${c.name||'Case '+c.id}</div>
        <div class="pst-shape">${c.shape||c.shape_compact||''}</div>
      </td><td>${badge}</td>${tdCols}`;
    tbody.appendChild(caseRow);

    // Register heat cells + tooltips
    caseRow.querySelectorAll('td[data-col]').forEach(td=>{
      const v=parseFloat(td.getAttribute('data-val'));
      precHeatCells.push({td,key:td.getAttribute('data-col'),val:isNaN(v)?0:v});
      td.addEventListener('mouseenter',e=>showPrecTip(e,idx));
      td.addEventListener('mouseleave',hidePrecTip);
    });
    caseRow.querySelector('td').addEventListener('mouseenter',e=>showPrecTip(e,idx));
    caseRow.querySelector('td').addEventListener('mouseleave',hidePrecTip);

    // Detail row
    const dtr=document.createElement('tr');
    dtr.className='pst-detail'; dtr.id=`pdr-${idx}`;
    const dtd=document.createElement('td');
    dtd.colSpan=precActiveCols.length+2; dtd.style.padding='0';
    dtd.innerHTML=`<div class="pst-dpanel" id="pdp-${idx}"></div>`;
    dtr.appendChild(dtd); tbody.appendChild(dtr);
  });

  pt.appendChild(tbody);
  // Apply initial heatmap
  const firstNum=precActiveCols.find(c=>!c.isStr&&!c.isAE);
  if(firstNum) applyPrecHeat(firstNum.key);
}

function applyPrecHeat(metricKey){
  const isDark=window.matchMedia('(prefers-color-scheme:dark)').matches;
  const alpha=isDark?0.2:0.13;
  const legend=$('prec-heat-legend');
  if(!metricKey){
    precHeatCells.forEach(c=>{c.td.style.backgroundColor='';});
    if(legend) legend.style.display='none'; return;
  }
  const rel=precHeatCells.filter(c=>c.key===metricKey);
  const vals=rel.map(c=>c.val).filter(v=>v>0);
  if(!vals.length){rel.forEach(c=>{c.td.style.backgroundColor='';});return;}
  const logMin=Math.log10(Math.min(...vals));
  const logMax=Math.log10(Math.max(...vals));
  const logRange=logMax-logMin||1;
  rel.forEach(c=>{
    if(c.val<=0){c.td.style.backgroundColor='';return;}
    const t=Math.max(0,Math.min(1,(Math.log10(c.val)-logMin)/logRange));
    const r=t<0.5?Math.round(255*t*2):255;
    const g=t<0.5?255:Math.round(255*(1-(t-0.5)*2));
    c.td.style.backgroundColor=`rgba(${r},${g},0,${alpha})`;
  });
  // Legend
  if(legend){
    legend.style.display='flex';
    const la=isDark?0.3:0.2;
    const grad=$('prec-hgrad');
    if(grad) grad.style.background=`linear-gradient(to right,rgba(0,255,0,${la}),rgba(255,255,0,${la}),rgba(255,0,0,${la}))`;
    const minEl=$('prec-hmin'); if(minEl) minEl.textContent=Math.min(...vals).toExponential(1);
    const maxEl=$('prec-hmax'); if(maxEl) maxEl.textContent=Math.max(...vals).toExponential(1);
    const ticks=$('prec-hticks'); if(!ticks) return;
    ticks.innerHTML='';
    const eMin=Math.floor(logMin),eMax=Math.ceil(logMax);
    for(let e=eMin;e<=eMax;e++){
      const pct=(e-logMin)/logRange*100;
      if(pct<-1||pct>101) continue;
      const tk=document.createElement('span');
      tk.className='heat-tick'; tk.style.left=Math.max(0,Math.min(100,pct))+'%';
      tk.textContent='1e'+e; ticks.appendChild(tk);
    }
  }
}

function showPrecTip(e,idx){
  const c=(D.cases||[])[idx]; if(!c) return;
  const p=c.precision||{};
  let h=`<div class="prec-tip-title">${c.name||'Case '+c.id}</div>`;
  h+=`<div class="prec-tip-row"><span class="prec-tip-lbl">Shape</span><span class="prec-tip-val" style="font-size:10px">${c.shape||c.shape_compact||''}</span></div>`;
  PREC_COL_DEFS.forEach(col=>{
    const v=p[col.key]; if(v==null) return;
    h+=`<div class="prec-tip-row"><span class="prec-tip-lbl">${col.label}</span><span class="prec-tip-val">${col.fmt(v)}</span></div>`;
  });
  _precTip.innerHTML=h; _precTip.classList.add('vis');
  const r=_precTip.getBoundingClientRect();
  let x=e.clientX+14,y=e.clientY-10;
  if(x+r.width>window.innerWidth-20) x=e.clientX-r.width-14;
  if(y+r.height>window.innerHeight-20) y=window.innerHeight-r.height-20;
  _precTip.style.left=x+'px'; _precTip.style.top=y+'px';
}
function hidePrecTip(){_precTip.classList.remove('vis');}
document.addEventListener('mousemove',e=>{
  if(_precTip.classList.contains('vis')){
    const r=_precTip.getBoundingClientRect();
    let x=e.clientX+14,y=e.clientY-10;
    if(x+r.width>window.innerWidth-20) x=e.clientX-r.width-14;
    if(y+r.height>window.innerHeight-20) y=window.innerHeight-r.height-20;
    _precTip.style.left=x+'px'; _precTip.style.top=y+'px';
  }
});

function togglePrecDetail(idx){
  const drow=$(`pdr-${idx}`), crow=$(`pcr-${idx}`); if(!drow||!crow) return;
  if(precOpenRows.has(idx)){
    drow.classList.remove('pst-open'); crow.classList.remove('pst-open');
    precOpenRows.delete(idx);
    if(precCharts[idx]){precCharts[idx].forEach(c=>c.destroy());delete precCharts[idx];}
  } else {
    // Single-open behavior to keep the precision panel compact
    Array.from(precOpenRows).forEach(i=>{
      const od=$(`pdr-${i}`), oc=$(`pcr-${i}`);
      if(od) od.classList.remove('pst-open');
      if(oc) oc.classList.remove('pst-open');
      if(precCharts[i]){precCharts[i].forEach(c=>c.destroy());delete precCharts[i];}
      precOpenRows.delete(i);
    });
    drow.classList.add('pst-open'); crow.classList.add('pst-open');
    precOpenRows.add(idx); renderPrecDetail(idx);
  }
}

function renderPrecDetail(idx){
  const cases=D.cases||[]; const c=cases[idx]; if(!c) return;
  const p=c.precision||{};
  const panel=$(`pdp-${idx}`); if(!panel) return;
  const isDark=window.matchMedia('(prefers-color-scheme:dark)').matches;
  const CG=isDark?'rgba(255,255,255,.06)':'rgba(0,0,0,.06)';
  const CT=isDark?'#8b949e':'#57606a';
  const numCols=precActiveCols.filter(col=>!col.isStr&&p[col.key]!=null);

  let html=`<div style="font-size:11px;color:var(--tx2);margin-bottom:10px;font-weight:600">
    Case ${c.id} — ${c.name||''} <span style="color:var(--tx3);font-family:var(--mono)">${c.shape||c.shape_compact||''}</span></div>`;
  html+='<div class="pst-charts">';
  html+=`<div class="pst-chart-box"><h5>精度指标（对数轴）</h5><canvas id="pc-bar-${idx}"></canvas></div>`;
  html+=`<div class="pst-chart-box"><h5>跨 Case 对比 — ${numCols[0]?.label||''}</h5><canvas id="pc-cross-${idx}"></canvas></div>`;
  html+='</div>';
  // Threshold table
  html+='<div style="overflow-x:auto"><table class="pst-thr"><thead><tr><th>指标</th><th>值</th><th>阈值</th><th>状态</th></tr></thead><tbody>';
  precActiveCols.forEach(col=>{
    const v=p[col.key]; if(v==null) return;
    const thresh=col.thresh;
    let status='—',cls='';
    if(thresh!=null){
      if(v<=thresh*0.5){status='✓ 优秀';cls='thr-ok';}
      else if(v<=thresh){status='△ 通过';cls='thr-warn';}
      else{status='✗ 超限';cls='thr-fail';}
    } else if(col.key==='match_rate'){
      cls=v>=99.9?'thr-ok':'thr-warn'; status=v>=99.9?'✓ 100%':`△ ${v.toFixed(1)}%`;
    }
    html+=`<tr><td>${col.label}</td><td class="val">${col.fmt(v)}</td><td>${thresh!=null?'≤'+thresh:'—'}</td><td class="${cls}">${status}</td></tr>`;
  });
  html+='</tbody></table></div>';
  panel.innerHTML=html;
  if(typeof Chart==='undefined'){return;}
  precCharts[idx]=[];
  // Chart 1: metric bars for this case
  const c1=document.getElementById(`pc-bar-${idx}`);
  if(c1&&numCols.length){
    const labels=numCols.map(c=>c.label), vals=numCols.map(c=>p[c.key]||0);
    const bgColors=vals.map((v,i)=>{
      const t=numCols[i].thresh;
      if(!t) return isDark?'rgba(41,151,255,.55)':'rgba(9,105,218,.5)';
      return v<=t*0.5?'rgba(26,127,55,.55)':v<=t?'rgba(191,135,0,.55)':'rgba(207,34,46,.55)';
    });
    const bdColors=vals.map((v,i)=>{
      const t=numCols[i].thresh;
      if(!t) return isDark?'#2997ff':'#0969da';
      return v<=t*0.5?'#1a7f37':v<=t?'#bf8700':'#cf222e';
    });
    precCharts[idx].push(new Chart(c1,{
      type:'bar', data:{labels,datasets:[{label:'当前值',data:vals,backgroundColor:bgColors,borderColor:bdColors,borderWidth:1,barPercentage:.65,minBarLength:4}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{y:{type:'logarithmic',grid:{color:CG},ticks:{color:CT,font:{size:9}}},x:{grid:{display:false},ticks:{color:CT,font:{size:9},maxRotation:30}}},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>`${ctx.dataset.label}: ${ctx.raw}`}}}}
    }));
  }
  // Chart 2: cross-case for first metric
  const c2=document.getElementById(`pc-cross-${idx}`);
  if(c2&&numCols.length){
    const metric=numCols[0];
    const allC=D.cases||[];
    const labels=allC.map(ca=>ca.name||'Case '+ca.id);
    const vals=allC.map(ca=>ca.precision&&ca.precision[metric.key]!=null?ca.precision[metric.key]:0);
    const bgColors=vals.map((_,i)=>i===idx?(isDark?'rgba(41,151,255,.8)':'rgba(9,105,218,.7)'):(isDark?'rgba(139,148,158,.3)':'rgba(142,142,147,.3)'));
    const bdColors=vals.map((_,i)=>i===idx?(isDark?'#2997ff':'#0969da'):(isDark?'#8b949e':'#8e8e93'));
    precCharts[idx].push(new Chart(c2,{
      type:'bar', data:{labels,datasets:[{label:metric.label,data:vals,backgroundColor:bgColors,borderColor:bdColors,borderWidth:1,barPercentage:.7,minBarLength:4}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{y:{type:vals.some(v=>v>0)?'logarithmic':'linear',grid:{color:CG},ticks:{color:CT,font:{size:9}}},x:{grid:{display:false},ticks:{color:CT,font:{size:9},maxRotation:30}}},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>`${metric.label}: ${ctx.raw}`}}}}
    }));
  }
}
// Legacy stubs (tab switch still calls buildPrecChart which was removed)
function buildPrecChart(){}
function updateTableSel(){}
function refreshPrecDetail(){}

// ═══════════════════════════════════════════════════
// TAB 4: 性能 v2 — Chart.js + op_summary 深度解析
// ═══════════════════════════════════════════════════
const AIV_SEGS = [
  {key:'aiv_vec_time(us)',    ratioKey:'aiv_vec_ratio',    label:'Vec (向量计算)',  color:'#0969da'},
  {key:'aiv_mte2_time(us)',   ratioKey:'aiv_mte2_ratio',   label:'MTE2 (GM→UB)',   color:'#1a7f37'},
  {key:'aiv_mte3_time(us)',   ratioKey:'aiv_mte3_ratio',   label:'MTE3 (UB→GM)',   color:'#bf8700'},
  {key:'aiv_scalar_time(us)', ratioKey:'aiv_scalar_ratio', label:'Scalar (标量)',   color:'#8250df'},
];
const AIC_SEGS = [
  {key:'aic_mac_time(us)',     ratioKey:'aic_mac_ratio',     label:'MAC (矩阵计算)',     color:'#0969da'},
  {key:'aic_mte1_time(us)',    ratioKey:'aic_mte1_ratio',    label:'MTE1 (GM→L0)',     color:'#bf8700'},
  {key:'aic_mte2_time(us)',    ratioKey:'aic_mte2_ratio',    label:'MTE2 (GM→L1)',     color:'#1a7f37'},
  {key:'aic_fixpipe_time(us)', ratioKey:'aic_fixpipe_ratio', label:'FixPipe (定长算)',  color:'#cf222e'},
  {key:'aic_scalar_time(us)',  ratioKey:'aic_scalar_ratio',  label:'Scalar (标量)',     color:'#8250df'},
];
let _perfHistChart=null, _perfDonutChartAIC=null, _perfDonutChartAIV=null, _perfTimingChart=null;

function buildPerf(){
  const cases=D.cases||[];
  const perfCases=cases.filter(c=>c.performance&&c.performance.speedup);
  if(!perfCases.length){
    $('perf-cards').innerHTML='<div style="color:var(--tx3);padding:12px">（无性能数据）</div>';
    $('perf-note').innerHTML='无 msprof 数据。请先运行评测生成 op_summary*.csv。';
    const cd=$('perf-case-detail-card'); if(cd) cd.style.display='none';
    return;
  }

  // ── Speedup overview histogram (Chart.js) ──
  const isDark=window.matchMedia('(prefers-color-scheme:dark)').matches;
  const CG=isDark?'rgba(255,255,255,.06)':'rgba(0,0,0,.06)';
  const CT=isDark?'#8b949e':'#57606a';
  const canvas=$('perf-hist-canvas');
  if(canvas&&typeof Chart!=='undefined'){
    if(_perfHistChart){_perfHistChart.destroy();_perfHistChart=null;}
    const labels=perfCases.map(c=>c.name||'Case '+c.id);
    const speedups=perfCases.map(c=>c.performance.speedup);
    const bgColors=speedups.map(s=>s>=2?'rgba(26,127,55,.7)':s>=1?'rgba(191,135,0,.7)':'rgba(207,34,46,.7)');
    const bdColors=speedups.map(s=>s>=2?'#1a7f37':s>=1?'#bf8700':'#cf222e');
    _perfHistChart=new Chart(canvas,{
      type:'bar',
      data:{labels,datasets:[{
        label:'Speedup',data:speedups,backgroundColor:bgColors,borderColor:bdColors,
        borderWidth:1.5,barPercentage:.65,minBarLength:4,
      }]},
      options:{
        responsive:true,maintainAspectRatio:false,
        scales:{
          y:{beginAtZero:true,grid:{color:CG},ticks:{color:CT,font:{size:10},callback:v=>v+'x'},
             title:{display:true,text:'Speedup (x)',color:CT,font:{size:10}}},
          x:{grid:{display:false},ticks:{color:CT,font:{size:10},maxRotation:30}},
        },
        plugins:{
          legend:{display:false},
          annotation:{annotations:{line1:{type:'line',yMin:1,yMax:1,borderColor:isDark?'rgba(255,255,255,.3)':'rgba(0,0,0,.2)',borderWidth:1,borderDash:[4,3]}}},
          tooltip:{callbacks:{label:ctx=>`Speedup: ${ctx.raw.toFixed(2)}x`}},
        },
      },
    });
  }

  // Precision-failed warning banner (shown before note when precision not all-pass)
  const precWarn=$('perf-prec-warn');
  if(precWarn){
    if(D.n_total>0 && D.n_pass<D.n_total){
      precWarn.style.display='';
      precWarn.innerHTML=`⚠ <b>当前精度未通过（${D.n_pass}/${D.n_total} PASS）</b>，以下性能数据仅供调试参考，建议先修复精度再优化性能。`;
    } else {
      precWarn.style.display='none';
    }
  }

  // Summary note
  const avgSp=D.avg_speedup;
  const maxSp=Math.max(...perfCases.map(c=>c.performance.speedup));
  const minSp=Math.min(...perfCases.map(c=>c.performance.speedup));
  let note=`${perfCases.length} 个 Shape 评测完成。加速比 <b>${minSp.toFixed(2)}x — ${maxSp.toFixed(2)}x</b>，均值 <b>${avgSp?avgSp.toFixed(2)+'x':'N/A'}</b>。<br>`;
  const src=perfCases[0].performance.source;
  if(src==='msprof'||src==='msprof_csv') note+='Custom 算子计时：<b>msprof 硬件级</b>（op_summary 纯 kernel 执行时间，不含 dispatch 开销）。参考实现计时：<b>torch.npu.Event</b>（含 PyTorch dispatch 及 inter-kernel gap，偏保守）。<br>';
  else if(src==='cann_standalone') note+='计时：<b>CANN standalone .so</b>（tilelang_eval_adapter + combined_kernel_loader）。NPU kernel 真实耗时，不含 Python 开销。<br>';
  else note+='计时：<b>torch.npu.Event</b>（参考实现与 custom 算子均使用相同计时方式）。<br>';
  if(D.n_total>0 && D.n_pass<D.n_total) note+='⚠ 精度未通过，性能结论仅供参考。';
  else if(avgSp>=2) note+='✓ 平均加速 <b>2x+</b>，达到优秀目标。';
  else if(avgSp>=1.2) note+='△ 加速有效，未达 2x，可进一步优化双缓冲/向量化。';
  else note+='✗ 加速偏低，建议排查 GM-UB 搬运瓶颈或 Scalar 指令占比。';
  $('perf-note').innerHTML=note;
  // avg badge
  const avgBadge=$('perf-avg-badge');
  if(avgBadge&&avgSp) avgBadge.textContent=`平均 ${avgSp.toFixed(2)}x`;

  // ── Case selector ──
  const sel=$('perf-case-sel');
  if(sel){
    sel.innerHTML=perfCases.map((c,i)=>`<option value="${i}">${c.name||'Case '+c.id}</option>`).join('');
    showCaseDetail(0);
  }
}

function showCaseDetail(selIdx){
  const cases=D.cases||[];
  const perfCases=cases.filter(c=>c.performance&&c.performance.speedup);
  const c=perfCases[selIdx]; if(!c) return;
  const osa=c.op_summary_avg||{};
  const perf=c.performance||{};
  const isDark=window.matchMedia('(prefers-color-scheme:dark)').matches;
  const CG=isDark?'rgba(255,255,255,.06)':'rgba(0,0,0,.06)';
  const CT=isDark?'#8b949e':'#57606a';

  // 算子类型检测（需要在 KPI row 之前定义）
  const aivTotal=osa['aiv_time(us)']||0;
  const aicTotal=osa['aicore_time(us)']||0;
  const taskType = osa['Task Type'] || '';
  const isAIC = taskType.includes('AIC') || taskType.includes('AI_CORE');
  const isAIV = taskType.includes('AIV') || taskType.includes('AI_VECTOR');

  // ── KPI row (根据算子类型动态显示) ──
  const kpiRow=$('perf-kpi-row');
  const kpis=[
    {label:'Task Type',     val:osa['Task Type']||'—'},
    {label:'Task Duration', val:osa['Task Duration(us)']!=null?osa['Task Duration(us)'].toFixed(2)+'μs':'—'},
    {label:'Block Dim',     val:osa['Block Dim']||(osa['Mix Block Dim']||'—')},
  ];
  // 根据算子类型添加时间指标
  if(isAIC && aicTotal>0){
    kpis.push({label:'AIC Time', val:osa['aicore_time(us)']!=null?osa['aicore_time(us)'].toFixed(2)+'μs':'—'});
    if(osa['cube_utilization(%)']!=null)
      kpis.push({label:'Cube Util', val:osa['cube_utilization(%)'].toFixed(1)+'%'});
  }
  if(isAIV || (isAIC && aivTotal>0)){
    kpis.push({label:'AIV Time', val:osa['aiv_time(us)']!=null?osa['aiv_time(us)'].toFixed(2)+'μs':'—'});
  }
  kpis.push({label:'Speedup', val:perf.speedup?perf.speedup.toFixed(2)+'x':'—'});
  kpiRow.innerHTML=kpis.map(k=>`
    <div class="kpi-card">
      <div class="kpi-lbl">${k.label}</div>
      <div class="kpi-val">${k.val}</div>
    </div>`).join('');

  // ── AIV/AIC Breakdown stacked bar (根据算子类型自适应) ──
  const aivSec=$('perf-aiv-section');
  if(aivSec){
    let html='';

    // AIC breakdown (Cube 算子或混合算子)
    if(isAIC && aicTotal>0 && osa['aic_mac_time(us)']!=null){
      const aicSegs=AIC_SEGS.map(s=>({...s,us:osa[s.key]||0,ratio:osa[s.ratioKey]||0}));
      const aicRatioTotal=aicSegs.reduce((a,b)=>a+b.ratio,0);
      const aicRemain=Math.max(0,1-aicRatioTotal);
      const cubeUtil=osa['cube_utilization(%)'];
      html+=`<div class="breakdown-title">Cube (AIC) 时间分解 <span style="color:var(--tx3);font-size:10px;font-weight:400">(${aicTotal.toFixed(2)}μs${cubeUtil!=null?` | Cube利用率 ${cubeUtil.toFixed(1)}%`:''})</span></div>`;
      html+='<div class="breakdown-stack">';
      aicSegs.forEach(s=>{
        if(s.ratio<=0) return;
        const pct=(s.ratio*100).toFixed(1);
        html+=`<div class="breakdown-seg" style="width:${pct}%;background:${s.color}" title="${s.label}: ${s.us.toFixed(2)}μs (${pct}%)">${s.ratio>0.08?pct+'%':''}</div>`;
      });
      if(aicRemain>0.01) html+=`<div class="breakdown-seg" style="width:${(aicRemain*100).toFixed(1)}%;background:var(--sf3)"></div>`;
      html+='</div>';
      html+='<div class="breakdown-legend">';
      aicSegs.forEach(s=>{
        if(s.ratio<=0) return;
        html+=`<div class="breakdown-legend-item"><div class="breakdown-legend-dot" style="background:${s.color}"></div>${s.label} <b style="color:var(--tx);font-family:var(--mono)">${(s.ratio*100).toFixed(1)}%</b></div>`;
      });
      html+='</div>';
    }

    // AIV breakdown (Vector 算子或混合算子)
    if((isAIV || isAIC) && aivTotal>0){
      if(isAIC) html+='<div style="height:12px"></div>';  // AIC+AIV 时添加间距
      const segsData=AIV_SEGS.map(s=>({...s,us:osa[s.key]||0,ratio:osa[s.ratioKey]||0}));
      const totalRatio=segsData.reduce((a,b)=>a+b.ratio,0);
      const remainRatio=Math.max(0,1-totalRatio);
      const typeLabel = isAIC?'Vector (AIV)':'Vector';
      html+=`<div class="breakdown-title">${typeLabel} 时间分解 <span style="color:var(--tx3);font-size:10px;font-weight:400">(总计 ${aivTotal.toFixed(2)}μs)</span></div>`;
      html+='<div class="breakdown-stack">';
      segsData.forEach(s=>{
        if(s.ratio<=0) return;
        const pct=(s.ratio*100).toFixed(1);
        const title=`${s.label}: ${s.us.toFixed(2)}μs (${pct}%)`;
        html+=`<div class="breakdown-seg" style="width:${pct}%;background:${s.color}" title="${title}">`;
        if(s.ratio>0.08) html+=pct+'%';
        html+='</div>';
      });
      if(remainRatio>0.01) html+=`<div class="breakdown-seg" style="width:${(remainRatio*100).toFixed(1)}%;background:var(--sf3);color:var(--tx3)"></div>`;
      html+='</div>';
      html+='<div class="breakdown-legend">';
      segsData.forEach(s=>{
        if(s.ratio<=0) return;
        html+=`<div class="breakdown-legend-item"><div class="breakdown-legend-dot" style="background:${s.color}"></div>${s.label} <b style="color:var(--tx);font-family:var(--mono)">${(s.ratio*100).toFixed(1)}%</b></div>`;
      });
      html+='</div>';
    }
    aivSec.innerHTML=html;
  }

  // ── Chart.js charts: 根据算子类型显示不同的图表组合 ──
  const grid=$('perf-charts-grid');
  if(grid&&typeof Chart!=='undefined'&&(aicTotal>0||aivTotal>0)){
    // 根据算子类型决定图表布局
    const isMix = isAIC && isAIV && aicTotal>0 && aivTotal>0;

    // 生成图表 HTML
    let chartsHTML = '';
    if(isMix){
      // MIX_AIC: 显示 3 个图表（AIC donut + AIV donut + timing bar with 4 columns）
      grid.className = "perf-detail-grid three-cols";
      chartsHTML += `<div class="perf-chart-card"><h5>AIC 执行类型占比</h5><canvas id="pc-donut-aic"></canvas></div>`;
      chartsHTML += `<div class="perf-chart-card"><h5>AIV 执行类型占比</h5><canvas id="pc-donut-aiv"></canvas></div>`;
      chartsHTML += `<div class="perf-chart-card" style="grid-column:1/-1"><h5>时延对比 (μs)</h5><canvas id="pc-timing"></canvas></div>`;
    } else if(isAIC && aicTotal>0){
      // 纯 AIC: 显示 2 个图表（AIC donut + timing bar with 3 columns）
      chartsHTML += `<div class="perf-chart-card"><h5>AIC 执行类型占比</h5><canvas id="pc-donut-aic"></canvas></div>`;
      chartsHTML += `<div class="perf-chart-card"><h5>时延对比 (μs)</h5><canvas id="pc-timing"></canvas></div>`;
    } else if(aivTotal>0){
      // 纯 AIV: 显示 2 个图表（AIV donut + timing bar with 3 columns）
      chartsHTML += `<div class="perf-chart-card"><h5>AIV 执行类型占比</h5><canvas id="pc-donut-aiv"></canvas></div>`;
      chartsHTML += `<div class="perf-chart-card"><h5>时延对比 (μs)</h5><canvas id="pc-timing"></canvas></div>`;
    }
    grid.innerHTML = chartsHTML;

    // Destroy old charts
    if(_perfDonutChartAIC){_perfDonutChartAIC.destroy();_perfDonutChartAIC=null;}
    if(_perfDonutChartAIV){_perfDonutChartAIV.destroy();_perfDonutChartAIV=null;}
    if(_perfTimingChart){_perfTimingChart.destroy();_perfTimingChart=null;}

    // 渲染 AIC donut chart
    if(isAIC && aicTotal>0){
      const aicDonutData=AIC_SEGS.map(s=>Math.round((osa[s.ratioKey]||0)*1000)/10);
      const aicDonutLabels=AIC_SEGS.map(s=>s.label.split(' ')[0]);
      const aicDonutColors=AIC_SEGS.map(s=>s.color);
      const aicDonutCanvas=document.getElementById('pc-donut-aic');
      if(aicDonutCanvas) _perfDonutChartAIC=new Chart(aicDonutCanvas,{
        type:'doughnut',
        data:{labels:aicDonutLabels,datasets:[{data:aicDonutData,backgroundColor:aicDonutColors.map(c=>c+'cc'),borderColor:aicDonutColors,borderWidth:1.5,hoverOffset:4}]},
        options:{responsive:true,maintainAspectRatio:false,cutout:'62%',
          plugins:{legend:{position:'bottom',labels:{color:CT,font:{size:10},boxWidth:10,padding:8}},
            tooltip:{callbacks:{label:ctx=>`${ctx.label}: ${ctx.raw.toFixed(1)}%`}}}}
      });
    }

    // 渲染 AIV donut chart
    if(aivTotal>0){
      const aivDonutData=AIV_SEGS.map(s=>Math.round((osa[s.ratioKey]||0)*1000)/10);
      const aivDonutLabels=AIV_SEGS.map(s=>s.label.split(' ')[0]);
      const aivDonutColors=AIV_SEGS.map(s=>s.color);
      const aivDonutCanvas=document.getElementById('pc-donut-aiv');
      if(aivDonutCanvas) _perfDonutChartAIV=new Chart(aivDonutCanvas,{
        type:'doughnut',
        data:{labels:aivDonutLabels,datasets:[{data:aivDonutData,backgroundColor:aivDonutColors.map(c=>c+'cc'),borderColor:aivDonutColors,borderWidth:1.5,hoverOffset:4}]},
        options:{responsive:true,maintainAspectRatio:false,cutout:'62%',
          plugins:{legend:{position:'bottom',labels:{color:CT,font:{size:10},boxWidth:10,padding:8}},
            tooltip:{callbacks:{label:ctx=>`${ctx.label}: ${ctx.raw.toFixed(1)}%`}}}}
      });
    }

    // Timing comparison (根据算子类型显示 3 或 4 个柱子)
    const tCanvas=document.getElementById('pc-timing');
    if(tCanvas){
      let timingLabels, timingVals, timingBg;
      if(isMix){
        // MIX_AIC: 显示 4 个柱子
        timingLabels=['Ref','Custom','AIC','AIV'];
        timingVals=[perf.ref_time_us||0, perf.custom_time_us||0, aicTotal, aivTotal];
        timingBg=[isDark?'rgba(139,148,158,.5)':'rgba(142,142,147,.5)',isDark?'rgba(26,127,55,.6)':'rgba(26,127,55,.5)',isDark?'rgba(9,105,218,.6)':'rgba(9,105,218,.5)',isDark?'rgba(191,135,0,.6)':'rgba(191,135,0,.5)'];
      } else if(isAIC){
        // 纯 AIC: 显示 3 个柱子
        timingLabels=['Ref','Custom','AIC'];
        timingVals=[perf.ref_time_us||0, perf.custom_time_us||0, aicTotal];
        timingBg=[isDark?'rgba(139,148,158,.5)':'rgba(142,142,147,.5)',isDark?'rgba(26,127,55,.6)':'rgba(26,127,55,.5)',isDark?'rgba(9,105,218,.6)':'rgba(9,105,218,.5)'];
      } else{
        // 纯 AIV: 显示 3 个柱子
        timingLabels=['Ref','Custom','AIV'];
        timingVals=[perf.ref_time_us||0, perf.custom_time_us||0, aivTotal];
        timingBg=[isDark?'rgba(139,148,158,.5)':'rgba(142,142,147,.5)',isDark?'rgba(26,127,55,.6)':'rgba(26,127,55,.5)',isDark?'rgba(9,105,218,.6)':'rgba(9,105,218,.5)'];
      }
      _perfTimingChart=new Chart(tCanvas,{
        type:'bar',
        data:{labels:timingLabels,datasets:[{label:'时延(μs)',data:timingVals,backgroundColor:timingBg,borderWidth:1,barPercentage:.6,minBarLength:4}]},
        options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',
          scales:{x:{grid:{color:CG},ticks:{color:CT,font:{size:10},callback:v=>v+'μs'}},y:{grid:{display:false},ticks:{color:CT,font:{size:11,weight:'600'}}}},
          plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>`${ctx.raw.toFixed(2)}μs`}}}}
      });
    }
  } else if(grid){
    grid.innerHTML='';
  }

  // ── Op summary detail table ──
  const opsDiv=$('perf-ops-detail');
  if(opsDiv){
    const dispFields=D.op_summary_fields||[];
    const rows=dispFields.filter(f=>osa[f]!=null);
    if(rows.length){
      let h=`<div style="font-size:11px;font-weight:700;color:var(--tx3);text-transform:uppercase;letter-spacing:.05em;margin:14px 0 6px">op_summary 原始数据（平均值）</div>`;
      h+='<table class="ops-tbl"><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>';
      rows.forEach(f=>{
        const v=osa[f];
        const formatted=typeof v==='number'?v.toFixed(4):String(v);
        h+=`<tr><td class="ops-key">${f}</td><td class="ops-val">${formatted}</td></tr>`;
      });
      h+='</tbody></table>';
      opsDiv.innerHTML=h;
    } else {
      opsDiv.innerHTML=`<div style="font-size:12px;color:var(--tx3);margin-top:12px;padding:10px;background:var(--sf2);border-radius:var(--r)">op_summary 详细字段（aiv_vec_ratio 等）暂无。<br>如需 op_summary 分析，提供 op_summary_custom_fn_*.csv 文件后重新生成。<br><span style="font-size:11px;opacity:.7">TileLang 场景：speedup 来自 cann_result.json（CANN standalone .so），无需 op_summary CSV。</span></div>`;
    }
  }
}

// ═══════════════════════════════════════════════════
// DATA HEALTH & ANALYSIS INJECTION
// ═══════════════════════════════════════════════════
function toggleDH(barId){
  const body=document.getElementById(barId+'-body');
  if(body) body.classList.toggle('open');
}

function renderDH(tabKey, barId){
  const bar=$(barId); if(!bar) return;
  const diags=(D.diagnostics||[]).filter(d=>d.tab===tabKey);
  if(!diags.length) return;
  const counts={FOUND:0,DERIVED:0,MISSING:0};
  diags.forEach(d=>{if(counts[d.level]!==undefined)counts[d.level]++;});
  const any_issue=counts.DERIVED+counts.MISSING>0;
  bar.style.display='block';
  const countsEl=document.getElementById(barId+'-counts');
  if(countsEl) countsEl.innerHTML=
    `<span class="dh-found-c">${counts.FOUND} FOUND</span> `+
    `<span class="dh-derived-c">${counts.DERIVED} DERIVED</span> `+
    (counts.MISSING?`<span class="dh-missing-c">${counts.MISSING} MISSING</span>`:'');
  const body=document.getElementById(barId+'-body');
  if(!body) return;
  const ICONS={FOUND:'✓',DERIVED:'△',MISSING:'✗'};
  body.innerHTML=diags.map(d=>
    `<div class="dh-item dh-${d.level.toLowerCase()}">
      <span class="dh-icon">${ICONS[d.level]||'?'}</span>
      <span class="dh-msg"><b>${d.source}</b>${d.detail?' — '+d.detail:''}</span>
      ${d.hint?`<span class="dh-hint">${d.hint}</span>`:''}
    </div>`).join('');
  // Auto-open if there are issues
  if(any_issue) body.classList.add('open');
}

function injectAnalysis(slotId, html, title){
  const slot=$(slotId); if(!slot||!html) return;
  const card=el('div','card');
  card.innerHTML=`<div class="ct"><span class="ico">🤖</span>${title||'Claude 分析'}</div>`+
    `<div class="ana-section"><div class="ana-origin">📄 由 Claude 按 panels/SPEC.md 生成</div>`+
    html+'</div>';
  slot.appendChild(card);
}

// ═══════════════════════════════════════════════════
// TAB SWITCH
// ═══════════════════════════════════════════════════
document.querySelectorAll('.tb').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tb').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tp').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-'+btn.dataset.tab).classList.add('active');
    // Re-render charts on tab show (needs layout to be visible)
    if(btn.dataset.tab==='prec') buildPrecChart();
    if(btn.dataset.tab==='perf') buildPerf();
  });
});

// ═══════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════

// 1. Data health for each tab
renderDH('algo',  'dh-algo');
renderDH('mem',   'dh-mem');
renderDH('prec',  'dh-prec');
renderDH('perf',  'dh-perf');

// 2. Inject Claude analysis panels
const P=D.panels||{};
if(P.algo&&P.algo.analysis_html)
  injectAnalysis('algo-analysis-slot', P.algo.analysis_html, '算法流图说明');
if(P.memory&&P.memory.analysis_html)
  injectAnalysis('mem-analysis-slot',  P.memory.analysis_html, 'Tiling 策略深度分析');
if(P.precision&&P.precision.analysis_html)
  injectAnalysis('prec-analysis-slot', P.precision.analysis_html, '精度诊断分析');
if(P.perf&&P.perf.analysis_html)
  injectAnalysis('perf-analysis-slot', P.perf.analysis_html, '性能瓶颈分析');

// 3. Extra custom panels
(P.extra||[]).forEach(ep=>{
  const tabId='tab-extra-'+ep.id;
  const content=el('div');
  const html=ep.analysis_html||ep.html;
  if(ep.analysis_html){
    const wrap=el('div','card');
    wrap.innerHTML='<div class="ct"><span class="ico">📄</span>'+ep.label+'</div>'+
      '<div class="ana-section">'+ep.analysis_html+'</div>';
    content.appendChild(wrap);
  } else if(ep.html){
    content.innerHTML=ep.html;
  }
  const tabDiv=el('div','tp');
  tabDiv.id=tabId;
  tabDiv.appendChild(content);
  document.querySelector('.content').appendChild(tabDiv);
  // Add tab button
  const btn=el('button','tb',ep.label);
  btn.dataset.tab='extra-'+ep.id;
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tb').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.tp').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    tabDiv.classList.add('active');
  });
  document.getElementById('main-tab-bar').appendChild(btn);
});

// 4. Main renders
buildHeader();
buildAlgo();
buildMemory();
buildPrecision();
buildPerf();
</script>
</body>
</html>
"""
