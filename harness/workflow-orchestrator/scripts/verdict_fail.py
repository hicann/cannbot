#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""verifier 裁决回传（失败）：写 verdict=fail + reason 裁决文件，供 orchestrator 收割。

python3 verdict_fail.py --work-dir <dir> --task-id <id> --reason "<失败原因>"

--reason 必填非空（fail 不带原因不可行动），截断至 500 字符。
仅当任务处于 verify 阶段（status.json 中为 verifying）时接受，否则 exit 2。
"""
import sys

from verdict_common import main

if __name__ == "__main__":
    sys.exit(main("fail", need_reason=True))
