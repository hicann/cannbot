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
dashboard_config.py  —  op-dashboard 的共享配置层

集中存放 design_tokens.json 的读取（_tok）、外部可执行程序的绝对路径，
以及芯片运行时探测（detect_chip_runtime）。被 dashboard_parsers.py 与
gen_dashboard.py 共同依赖，自身不依赖本目录下其它模块。
"""

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── 外部可执行程序绝对路径（安全：避免按名称在 PATH 中查找）─────────────────────
# 通过 shutil.which 解析为绝对路径，找不到时回退原名（行为不变）。
_NPU_SMI = shutil.which("npu-smi") or "npu-smi"

# ─── DESIGN TOKENS（单一真源）─────────────────────────────────────────────────
_SKILL_DIR = Path(__file__).parent.parent
_tok_path = _SKILL_DIR / "design_tokens.json"


def _load_tokens(path: Path) -> dict:
    """加载 design_tokens.json；放在函数内避免异常变量泄漏到模块作用域（G.VAR.03）。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("读取 design_tokens.json 失败，使用空 tokens: %s", e)
        return {}


_TOKENS = _load_tokens(_tok_path)


def _tok(path: str, default=None):
    """读取 design_tokens 中的嵌套键，如 'colors.pos_vecin'"""
    parts, v = path.split("."), _TOKENS
    for p in parts:
        if not isinstance(v, dict):
            return default
        v = v.get(p, default)
    return v if v is not None else default


def detect_chip_runtime(default_name: str, default_ub_kb: int, default_aic: int,
                        default_aiv: Optional[int] = None) -> dict:
    """
    通过 npu-smi 探测真实芯片型号、NPU 数量和 AICore 核数。

    - 芯片名、NPU 总数：来自 `npu-smi info`
    - AICore Count：来自 `npu-smi info -t common -i 0`（真实硬件值）
    - UB 大小：npu-smi 不暴露，仍从已知芯片映射取
    - aiv：AIV/vector_core 数量，910B 上每个 ai_core 含 2 个 vector_core，
           若未提供则默认为 aic * 2
    """
    info = {
        "name": default_name,
        "ub_kb": int(default_ub_kb),
        "aic": int(default_aic),
        "aiv": int(default_aiv) if default_aiv is not None else int(default_aic) * 2,
        "npu_count": 1,
        "source": "design_tokens",
    }

    # Step 1: npu-smi info — 获取芯片名 + NPU 总数
    try:
        out = subprocess.check_output(
            [_NPU_SMI, "info"], stderr=subprocess.STDOUT, text=True, timeout=3
        )
        m = re.search(r"\|\s*(\d+)\s+(910\w+|310\w*)\s+\|", out)
        if m:
            info["name"] = f"Ascend {m.group(2)}"
            info["source"] = "npu-smi info"
        # NPU 总数：统计 "| <id>  910..." 行数
        npu_ids = re.findall(r"^\|\s*(\d+)\s+(?:910|310)", out, re.MULTILINE)
        if npu_ids:
            info["npu_count"] = len(set(npu_ids))
    except Exception as e:
        logger.debug("npu-smi info 探测失败，回退默认芯片信息: %s", e)

    # UB 大小映射（npu-smi 不暴露，按架构族取）
    ub_map = {
        "910B": 192,   # 910B2/B3/B4: UB 192 KB
        "910": 256,   # 910 Pro/A: UB 256 KB
        "310B": 192,
        "310": 192,
    }
    for k, ub in ub_map.items():
        if k in info["name"]:
            info["ub_kb"] = ub
            break

    # Step 2: npu-smi info -t common -i 0 — 获取真实 AICore Count
    try:
        out2 = subprocess.check_output(
            [_NPU_SMI, "info", "-t", "common", "-i", "0"],
            stderr=subprocess.STDOUT, text=True, timeout=3
        )
        m2 = re.search(r"Aicore Count\s*:\s*(\d+)", out2)
        if m2:
            info["aic"] = int(m2.group(1))
            info["source"] = "npu-smi info -t common"
    except Exception as e:
        logger.debug("npu-smi 探测 AICore Count 失败，保留默认 aic: %s", e)

    return info
