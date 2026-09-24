#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""Run the whitebox coverage gate from the unified whitebox designer entry point.

用法:
    python3 coverage_audit.py <design_doc_cases.json> <design_facts.json> <opspec.json>
退出码 0 表示覆盖达标；1 表示覆盖不足；2 表示参数或必需输入错误。
"""

import json
import logging
import os
import sys

from whitebox_gate import load_gate_inputs, load_whitebox

LOG = logging.getLogger(__name__)


def _required_inputs_missing(argv):
    tags = (
        (argv[0], "design_doc_cases.json"),
        (argv[1], "design_facts.json"),
        (argv[2], "opspec.json"),
    )
    for path, tag in tags:
        if not os.path.isfile(path):
            LOG.error("缺少必需输入 %s: %s", tag, path)
            return True
    return False


def main(argv):
    if len(argv) != 3:
        LOG.error("用法: coverage_audit.py <design_doc_cases.json> <design_facts.json> <opspec.json>")
        return 2
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    if _required_inputs_missing(argv):
        return 1

    try:
        whitebox = load_whitebox()
    except FileNotFoundError as exc:
        LOG.error("%s", exc)
        return 2
    whitebox.coverage_audit_cases = getattr(whitebox, "_coverage_audit_cases")

    cases, facts, opspec = load_gate_inputs(argv)
    dims = whitebox.dims_from_opspec(facts, opspec)
    ok, report = whitebox.coverage_audit_cases(cases, dims)
    LOG.info(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
