#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""人工审批写入器（文件信箱）。

python3 approve_task.py --work-dir <dir> --task-id <id> --decision approve
python3 approve_task.py --work-dir <dir> --task-id <id> --decision redo --comment "<重做意见>"
python3 approve_task.py --work-dir <dir> --task-id <id> --decision fail [--comment "<终裁原因>"]

仅当任务处于 awaiting_approval 时接受：原子写 .workflow/approvals/<百分号编码 task_id>.json，
由 get_task.py 每轮收割（approve→pass / redo→pending 注入 feedback / fail→终裁走 on_exhaust）。
同名文件已存在则覆盖（收割前可改主意）。
脚本只写审批文件不碰 status.json——orchestrator 主线程是 status.json 的唯一写入者。
"""
import argparse
import json
import logging
import os
import sys
from urllib.parse import quote

DECISIONS = ("approve", "redo", "fail")
COMMENT_MAX = 500


def approval_file_path(work_dir, task_id):
    """审批文件路径：与 verdict 文件同款百分号编码（分隔符/% 转义无碰撞）。"""
    return os.path.join(work_dir, ".workflow", "approvals",
                        quote(task_id, safe="") + ".json")


def _atomic_write_json(path, data):
    """tmp + rename 原子写：写半截崩溃不损坏旧文件；失败抛 OSError。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="写入人工审批决定（供 get_task.py 收割；仅 awaiting_approval 状态可用）")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--decision", required=True, choices=DECISIONS)
    parser.add_argument("--comment", default=None,
                        help="redo 必填非空；fail 可选；截断至 %d 字符" % COMMENT_MAX)
    args = parser.parse_args(argv)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, format="[approve_task] %(message)s",
                        handlers=[stdout_handler, stderr_handler])

    comment = (args.comment or "").strip()
    if args.decision == "redo" and not comment:
        logging.error("错误: decision=redo 时 --comment 不能为空")
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
    if entry.get("status") != "awaiting_approval":
        logging.error("错误: 任务 %s 当前状态 %r，不在待审批状态",
                      args.task_id, entry.get("status"))
        return 2

    data = {"decision": args.decision}
    if comment:
        data["comment"] = comment[:COMMENT_MAX]
    try:
        _atomic_write_json(approval_file_path(args.work_dir, args.task_id), data)
    except OSError as e:
        logging.error("错误: 审批文件写入失败: %s", e)
        return 2
    logging.info("%s: decision=%s 已记录", args.task_id, args.decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
