#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""裁决文件公共逻辑：verdict_pass.py / verdict_fail.py 两个薄入口共用。

裁决文件 = $WORK_DIR/.workflow/verdicts/<百分号编码后的 task_id>.json，JSON 内容
{"verdict": "pass"|"fail", "reason"?}。
脚本只写裁决文件不碰 status.json——orchestrator 主线程是 status.json 的唯一写入者。
"""
import argparse
import json
import logging
import os
import sys
from urllib.parse import quote

REASON_MAX = 500
VALID_VERDICTS = ("pass", "fail")


def verdict_file_path(work_dir, task_id):
    """裁决文件路径。

    Percent-encode the complete task id. This keeps ordinary IDs readable while
    escaping separators and percent signs without collisions.
    """
    return os.path.join(work_dir, ".workflow", "verdicts",
                        quote(task_id, safe="") + ".json")


def write_verdict_file(work_dir, task_id, verdict, reason=None):
    """原子写裁决文件（tmp + rename）。verdict 非法属调用方 bug，fail fast。"""
    if verdict not in VALID_VERDICTS:
        raise ValueError("非法 verdict: %r" % verdict)
    data = {"verdict": verdict}
    if reason:
        data["reason"] = reason[:REASON_MAX]
    path = verdict_file_path(work_dir, task_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def main(verdict, need_reason, argv=None):
    """脚本入口：校验 verify 阶段 → 写裁决文件 → 记录确认；任何失败 exit 2。"""
    parser = argparse.ArgumentParser(
        prog="verdict_%s.py" % verdict,
        description="记录 verify 裁决到裁决文件（供 orchestrator 收割；仅 verify 阶段可用）")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--task-id", required=True)
    if need_reason:
        parser.add_argument("--reason", required=True,
                            help="失败原因（必填非空，截断至 %d 字符）" % REASON_MAX)
    args = parser.parse_args(argv)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    logging.basicConfig(
        level=logging.INFO,
        format="[verdict] %(message)s",
        handlers=[stdout_handler, stderr_handler],
    )

    reason = getattr(args, "reason", None)
    if reason is not None and not reason.strip():
        logging.error("错误: --reason 不能为空")
        return 2

    status_path = os.path.join(args.work_dir, ".workflow", "status.json")
    try:
        with open(status_path, encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.error("错误: status.json 读取失败: %s", e)
        return 2
    entry = (status.get("tasks") or {}).get(args.task_id)
    if not isinstance(entry, dict):
        logging.error("错误: 未知任务 id: %s", args.task_id)
        return 2
    cur = entry.get("status")
    if cur != "verifying":
        logging.error("错误: 任务 %s 当前状态 %r，不在 verify 阶段；"
                      "本脚本仅由 verifier 在验证完成后调用", args.task_id, cur)
        return 2

    try:
        write_verdict_file(args.work_dir, args.task_id, verdict,
                      reason.strip() if reason else None)
    except OSError as e:
        logging.error("错误: 裁决文件写入失败: %s", e)
        return 2
    logging.info("%s: verdict=%s 已记录", args.task_id, verdict)
    return 0
