#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
"""merge_cases CSV 合并回归测试。"""

import csv

import pytest

from merge_cases import merge


def _write(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_merge_uses_canonical_names_and_unions_headers(tmp_path):
    cases = tmp_path / "testcases"
    cases.mkdir()
    _write(cases / "aclnnOp_l0_functional.csv", ["testcase_name", "tensor_view_shapes"], [["l0", "((2,),)"]])
    _write(
        cases / "aclnnOp_l1_functional.csv",
        ["testcase_name", "tensor_view_shapes", "tensor_storage_shapes"],
        [["l1", "((2,),)", "((4,),)"]],
    )
    _write(cases / "aclnnOp_l1_functional_oversized.csv", ["testcase_name"], [["huge"]])
    _write(cases / "aclnnOp_l2_exception.csv", ["testcase_name", "remark"], [["l2", "expect_error"]])
    positive, negative = merge(cases, tmp_path / "positive.csv", tmp_path / "negative.csv")

    assert (positive, negative) == (2, 1)
    with (tmp_path / "positive.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["testcase_name"] for row in rows] == ["l0", "l1"]
    assert rows[0]["tensor_storage_shapes"] == ""
    assert rows[1]["tensor_storage_shapes"] == "((4,),)"


def test_merge_rejects_duplicate_case_names(tmp_path):
    cases = tmp_path / "testcases"
    cases.mkdir()
    _write(cases / "aclnnOp_l0_functional.csv", ["testcase_name"], [["same"]])
    _write(cases / "aclnnOp_l1_functional.csv", ["testcase_name"], [["same"]])
    try:
        merge(cases, tmp_path / "positive.csv", tmp_path / "negative.csv")
    except ValueError as exc:
        assert "duplicate testcase_name" in str(exc)
    else:
        raise AssertionError("duplicate testcase_name must fail")


def test_merge_normalizes_public_skill_non_contiguous_offsets(tmp_path):
    cases = tmp_path / "testcases"
    cases.mkdir()
    header = ["testcase_name", "tensor_view_shapes", "tensor_view_offsets"]
    _write(cases / "aclnnOp_l0_functional.csv", header, [["l0", "((2,),)", ""]])
    _write(
        cases / "aclnnOp_l1_functional.csv",
        header,
        [
            ["plain", "((2, 3), (2, 3))", "((5,), (0,))"],
            ["tensor_list", "(((2,), (3,)), (4,))", "(((1,), (2,)), (0,))"],
        ],
    )

    merge(cases, tmp_path / "positive.csv", tmp_path / "negative.csv")
    with (tmp_path / "positive.csv").open(newline="", encoding="utf-8") as handle:
        rows = {row["testcase_name"]: row for row in csv.DictReader(handle)}
    assert rows["plain"]["tensor_view_offsets"] == "(5, 0)"
    assert rows["tensor_list"]["tensor_view_offsets"] == "((1, 2), 0)"


def test_merge_rejects_ambiguous_non_contiguous_offsets(tmp_path):
    cases = tmp_path / "testcases"
    cases.mkdir()
    header = ["testcase_name", "tensor_view_shapes", "tensor_view_offsets"]
    _write(cases / "aclnnOp_l0_functional.csv", header, [["bad", "((2,), (2,))", "((0,),)"]])

    with pytest.raises(ValueError, match="offsets count"):
        merge(cases, tmp_path / "positive.csv", tmp_path / "negative.csv")
