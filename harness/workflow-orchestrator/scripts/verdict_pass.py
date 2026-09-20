#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""verifier 裁决回传（通过）：写 verdict=pass 裁决文件，供 orchestrator 收割。

python3 verdict_pass.py --work-dir <dir> --task-id <id>

仅当任务处于 verify 阶段（status.json 中为 verifying）时接受，否则 exit 2。
"""
import sys

from verdict_common import main

if __name__ == "__main__":
    sys.exit(main("pass", need_reason=False))
