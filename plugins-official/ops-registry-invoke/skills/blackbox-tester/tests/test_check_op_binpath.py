#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""check_op_binpath.py 回归测试。"""

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIX = os.path.join(_HERE, "fixtures")
_SPEC = importlib.util.spec_from_file_location(
    "check_op_binpath", os.path.join(_HERE, "..", "check_op_binpath.py"))
cob = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cob)

# canonical CANN 安装路径（脱敏，非个人目录）；用例只比对路径前缀，目录无需真实存在。
CANN = "/home/developer/Ascend/cann-9.1.0/opp"
VENDOR_ADD = f"{CANN}/vendors/AddCustom"
VENDOR_SS = f"{CANN}/vendors/SoftShrink"
VENDOR_SOFTMAX = f"{CANN}/vendors/SoftmaxV2"


def test_pass_on_real_device_log():
    assert cob.main([os.path.join(_FIX, "aclnn_smoke_ok.log"),
                     "--optype", "AddCustom", "--expect-dir", VENDOR_ADD]) == 0


def test_fail_when_bin_from_builtin():
    assert cob.main([os.path.join(_FIX, "aclnn_smoke_builtin.log"),
                     "--optype", "AddCustom", "--expect-dir", VENDOR_ADD]) == 1


def test_fail_on_real_builtin_softshrink():
    assert cob.main([os.path.join(_FIX, "aclnn_smoke_builtin_softshrink.log"),
                     "--optype", "SoftShrink", "--expect-dir", VENDOR_SS]) == 1


def test_pass_on_available_bin_format():
    assert cob.main([os.path.join(_FIX, "aclnn_smoke_available_bin.log"),
                     "--optype", "SoftmaxV2", "--expect-dir", VENDOR_SOFTMAX]) == 0


def test_warn_when_op_absent():
    ok = os.path.join(_FIX, "aclnn_smoke_ok.log")
    assert cob.main([ok, "--optype", "NotThisOp", "--expect-dir", VENDOR_ADD]) == 2
    assert cob.main([ok, "--optype", "NotThisOp", "--expect-dir", VENDOR_ADD, "--require"]) == 1


def test_only_matches_requested_optype(tmp_path):
    path = tmp_path / "other.log"
    path.write_text("... Op[SomeOther] xxx bin path is /opp/vendors/SomeOther/k/SomeOther_1.o\n")
    assert cob.main([str(path), "--optype", "AddCustom", "--expect-dir", VENDOR_ADD]) == 2
