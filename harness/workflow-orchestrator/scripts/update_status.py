#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""任务状态更新器。

python3 update_status.py <task_id> <work_dir> <agent_reply>   （agent_reply = agent 最后一条消息）

读 $WORK_DIR/.workflow/status.json，打印任务当前状态并按回复分类迁移：

回复分类（pass/fail/executed/others）：取最后一条非空行，忽略大小写与结尾
标点后须恰好等于关键词——协议要求整条回复只有关键词，宽松包含匹配会把
"the fix did not pass" 误判成 pass，宁误判 others（可重试）不误判 pass。

状态机：
- pending   + 任意回复   → running
- executed  + 任意回复   → verifying
- running   + 任意回复   → executed（不校验回复关键词，由 verifier 把关）
- verifying + pass       → pass
- verifying + fail       → fail 且 retries+1（是否重试由调度方按 max_retries/on_exhaust 决定）
- verifying + 其他       → verifying（不动，不写回）

pass/fail 为终态，拒绝更新。有变化时写回 status.json 并追加 log.jsonl。
stdout: "[update_status] <task_id>: <旧> → <新> (reply=<class>)"
未知任务/终态/非法状态/读写失败 → stderr 报错并 exit 2。
"""
import argparse
import json
import os
import sys
from datetime import datetime

KEYWORDS = ("pass", "fail", "executed")


def fail(msg):
    print("[update_status] 错误: %s" % msg, file=sys.stderr)
    return 2


def classify(reply):
    r = reply.strip()
    if not r:
        return "others"
    # 优先末行；否则从后向前找恰好等于关键词的行（agent 偶发在协议词后追加总结）。
    # 仍要求整行精确匹配："the fix did not pass" 不会误判为 pass（宁误判 others）。
    lines = [l.strip().lower().rstrip("。.!！?？;；,，") for l in r.splitlines() if l.strip()]
    for line in reversed(lines):
        if line in KEYWORDS:
            return line
    return "others"


def transition(cur, cls):
    """返回新状态；无规则（终态/非法）返回 None。"""
    if cur == "pending":
        return "running"
    if cur == "executed":
        return "verifying"
    if cur == "running":
        return "executed"
    if cur == "verifying":
        return cls if cls in ("pass", "fail") else "verifying"
    return None


def main():
    parser = argparse.ArgumentParser(description="Update task status from agent reply")
    parser.add_argument("task_id", help="task id in status.json")
    parser.add_argument("work_dir", help="working directory (must contain .workflow/status.json)")
    parser.add_argument("reply", help="agent's last message")
    args = parser.parse_args()

    wf_dir = os.path.join(args.work_dir, ".workflow")
    status_path = os.path.join(wf_dir, "status.json")
    if not os.path.isfile(status_path):
        return fail("工作流未初始化(%s 不存在)" % status_path)
    try:
        with open(status_path, encoding="utf-8") as f:
            status = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return fail("status.json 读取失败: %s" % e)

    entry = (status.get("tasks") or {}).get(args.task_id)
    if not isinstance(entry, dict):
        return fail("未知任务 id: %s" % args.task_id)
    cur = entry.get("status")
    cls = classify(args.reply)
    new = transition(cur, cls)
    if new is None:
        return fail("任务 %s 状态 %r 无迁移规则（pass/fail 为终态，非法状态拒绝更新）"
                    % (args.task_id, cur))

    retry = cur == "verifying" and cls == "fail"
    print("[update_status] %s: %s → %s (reply=%s)" % (args.task_id, cur, new, cls))
    if new == cur and not retry:  # verifying + others：无变化，不写回
        return 0

    entry["status"] = new
    if retry:
        entry["retries"] = int(entry.get("retries", 0)) + 1
    try:
        tmp = status_path + ".tmp"  # 原子写：写半截崩溃不损坏旧文件
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, status_path)
        with open(os.path.join(wf_dir, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "update",
                "task_id": args.task_id,
                "reply": cls,
                "from": cur,
                "to": new,
                "retries": entry.get("retries", 0),
            }, ensure_ascii=False) + "\n")
    except OSError as e:
        return fail("status.json/log.jsonl 写回失败: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
