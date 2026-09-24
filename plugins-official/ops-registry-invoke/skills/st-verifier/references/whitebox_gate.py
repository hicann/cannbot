#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""Shared loading helpers for whitebox-derived ST gates."""

import importlib.util
import json
import os

# 单一真源：白盒统一入口（sibling skill）。
_WHITEBOX = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "ascendc-whitebox-design", "references", "whitebox_designer.py",
)


def load_whitebox():
    path = os.path.abspath(_WHITEBOX)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"whitebox entry not found: {path}")
    spec = importlib.util.spec_from_file_location("whitebox_designer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 白盒入口只提供私有实现名；这里为其建立公开别名，避免调用方直接访问受保护成员。
    module.dims_from_opspec = getattr(module, "_dims_from_opspec")
    return module


def load_gate_inputs(argv):
    with open(argv[0], encoding="utf-8") as handle:
        document = json.load(handle)
    with open(argv[1], encoding="utf-8") as handle:
        facts = json.load(handle)
    with open(argv[2], encoding="utf-8") as handle:
        opspec = json.load(handle)
    cases = document.get("cases", document) if isinstance(document, dict) else document
    return cases, facts, opspec
