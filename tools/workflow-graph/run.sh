#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------
# 启动工作流图实时解析服务；自动挑选带 PyYAML 的 Python 解释器。
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for py in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import yaml' >/dev/null 2>&1; then
    exec "$py" "$here/server.py" "$@"
  fi
done
echo "未找到带 PyYAML 的 Python 解释器（试过 python3.14/3.13/3.12/3.11/3.10/3）。" >&2
exit 1
