#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""Shared helpers and dtype mappings for Ascend C build inspection scripts."""

import glob
import json
import os
from pathlib import Path

# dtype -> injected -DDTYPE_X macro value.  Keep in sync with references/build-pipeline.md.
DTYPE_TO_MACRO = {
    "float32": "float", "float16": "half", "bfloat16": "bfloat16_t",
    "int8": "int8_t", "int16": "int16_t", "int32": "int32_t", "int64": "int64_t",
    "uint8": "uint8_t", "uint16": "uint16_t", "uint32": "uint32_t", "uint64": "uint64_t",
    "bool": "bool", "double": "double",
}

# dtype -> injected -DORIG_DTYPE_X macro value.
DTYPE_TO_ORIG = {
    "float32": "DT_FLOAT", "float16": "DT_FLOAT16", "bfloat16": "DT_BF16",
    "int8": "DT_INT8", "int16": "DT_INT16", "int32": "DT_INT32", "int64": "DT_INT64",
    "uint8": "DT_UINT8", "uint16": "DT_UINT16", "uint32": "DT_UINT32", "uint64": "DT_UINT64",
    "bool": "DT_BOOL", "double": "DT_DOUBLE",
}

# ge::DataType enum -> name, used to decode simplifiedKey.
GE_DTYPE_ENUM = {
    0: "float32", 1: "float16", 27: "bfloat16",
    2: "int8", 3: "uint8", 9: "int16", 10: "uint16",
    11: "int32", 12: "uint32", 13: "int64", 14: "uint64",
    17: "bool", 18: "double",
}

# ge::Format enum -> name.  Adjust this table if a CANN release changes enum values.
GE_FORMAT_ENUM = {
    0: "NCHW", 1: "NHWC", 2: "ND", 3: "NC1HWC0", 4: "FRACTAL_Z",
}


def find_build_dir(arg):
    """Locate an explicit build directory."""
    if not arg:
        return None
    path = Path(arg)
    return path if path.is_dir() else None


def load_json(path):
    """Read JSON and return None for missing, unreadable, or truncated files."""
    try:
        with open(path) as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return None
    except OSError:
        return None


def find_work_dirs(build_dir, op_type=None):
    """Locate codegen working directories that contain bin_param/."""
    dirs = set()
    pattern = str(Path(build_dir) / "**" / "bin_param")
    for path in glob.glob(pattern, recursive=True):
        if os.path.isdir(path):
            dirs.add(os.path.dirname(path))

    output = sorted(path for path in dirs if "_CPack_Packages" not in path)
    if op_type:
        output = [path for path in output if Path(path).name.startswith(op_type + "_")]
    return output
