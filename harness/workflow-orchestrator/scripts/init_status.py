#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""初始化工作流状态。

python3 init_status.py --yaml <workflow.yaml> --work-dir <work directory> --prompt <prompt>

在 $WORK_DIR/.workflow/ 下创建：
- status.json    任务状态表（契约：workflow/work_dir/user_prompt/tasks；
                  只记 normal 任务 id，subgraph 容器不注册——分组不是任务，
                  状态由调度脚本从子任务实时聚合；任务定义由调度脚本从 yaml 读取；
                  user_prompt 指向 user_prompt.md 的绝对路径）
- user_prompt.md 本次开发任务的 prompt 原文
- log.jsonl      事件日志（首条 init 记录）
"""
import argparse
import json
import os
import sys
from datetime import datetime

import yaml


def main():
    p = argparse.ArgumentParser(description="Initialize workflow status")
    p.add_argument("--yaml", required=True, help="path to the workflow definition file")
    p.add_argument("--work-dir", required=True, help="work directory")
    p.add_argument("--prompt", required=True, help="development task prompt")
    args = p.parse_args()

    wf_dir = os.path.join(args.work_dir, ".workflow")
    status_path = os.path.join(wf_dir, "status.json")

    if not os.path.isfile(args.yaml):
        print("[init_status] 错误: workflow yaml 不存在: %s" % args.yaml, file=sys.stderr)
        return 1
    if os.path.exists(status_path):
        print("[init_status] 错误: 工作流已初始化(%s 存在)，拒绝覆盖" % status_path, file=sys.stderr)
        return 1

    try:
        with open(args.yaml, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print("[init_status] 错误: workflow yaml 解析失败: %s" % e, file=sys.stderr)
        return 1

    task_ids = [n["id"] for n in (config.get("nodes") or [])
                if isinstance(n, dict) and n.get("id") and n.get("task_type") != "subgraph"]
    if not task_ids:
        print("[init_status] 错误: workflow yaml 中没有任务节点(nodes 为空)", file=sys.stderr)
        return 1

    os.makedirs(wf_dir, exist_ok=True)
    status = {
        "workflow": os.path.abspath(args.yaml),
        "work_dir": os.path.abspath(args.work_dir),
        "user_prompt": os.path.abspath(os.path.join(wf_dir, "user_prompt.md")),
        "tasks": {tid: {"status": "pending", "retries": 0} for tid in task_ids},
    }
    tmp = status_path + ".tmp"  # 原子写：写半截崩溃不会留下半截 status.json
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, status_path)
    with open(os.path.join(wf_dir, "user_prompt.md"), "w", encoding="utf-8") as f:
        f.write(args.prompt + "\n")
    with open(os.path.join(wf_dir, "log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": "init",
            "workflow": config.get("workflow", ""),
            "tasks": len(task_ids),
        }, ensure_ascii=False) + "\n")

    print("[init_status] 已初始化 %d 个任务 → %s" % (len(task_ids), status_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
