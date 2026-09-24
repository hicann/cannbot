#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""Run the whitebox shape gate from the unified whitebox designer entry point.

用法:
    python3 shape_audit.py <design_doc_cases.json> <design_facts.json> <opspec.json>
退出码 0 表示合法；1 表示有用例违反；2 表示参数或必需输入错误。
"""

import json
import logging
import os
import sys

from whitebox_gate import load_gate_inputs, load_whitebox

LOG = logging.getLogger(__name__)


def main(argv):
    if len(argv) != 3:
        LOG.error("用法: shape_audit.py <design_doc_cases.json> <design_facts.json> <opspec.json>")
        return 2
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    for path in argv:
        if not os.path.isfile(path):
            LOG.error("缺少必需输入: %s", path)
            return 1

    try:
        whitebox = load_whitebox()
    except FileNotFoundError as exc:
        LOG.error("%s", exc)
        return 2

    cases, facts, opspec = load_gate_inputs(argv)
    dims = whitebox.dims_from_opspec(facts, opspec)
    ok, report = whitebox.validate_shapes(cases, dims)
    LOG.info(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
