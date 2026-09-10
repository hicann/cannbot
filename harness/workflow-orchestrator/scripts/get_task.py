#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""任务派发器。

python3 get_task.py <work_dir>          （唯一输入）

按 $WORK_DIR/.workflow/status.json 的 workflow 字段定位 yaml，对照契约全量校验
（顶层恰好 workflow/max_parallel/nodes；normal 12 键 / subgraph 4 键，恰好无多余；
depends_on 引用存在且无环），物化子图，再选取派发批次：

- pending（依赖全 pass）→ agent=executor（execute 阶段）
- executed             → agent=verifier（verify 阶段，不受依赖回归影响）
- subgraph 依赖全 pass 时物化：读 file（相对 work_dir，顶层恰好 nodes 键、节点均
  normal），子任务以 父id/子id 注册进 status.json（幂等、只增），子任务同规则派发；
  子任务全 pass → subgraph 聚合为 pass，解锁下游。不支持嵌套 subgraph。
  subgraph 容器本身不注册状态（分组不是任务，状态由 eff() 实时聚合，不占 max_parallel）。
- 批次 ≤ max_parallel − 在飞（running/verifying）数
- 重试策略：fail 且 retries ≤ max_retries → 写回 pending 自动重试（含子图子任务）；
  超预算 → 打 exhausted 标记，按 on_exhaust 分流：exit → [STUCK]（短路，本轮不派发
  任何任务）；continue → 耗尽节点及其全部（传递）下游构成跳过任务集合（含子图容器
  聚合规则：全部子任务 ∈ {pass}∪跳过集合 且至少一个 ∈ 跳过集合 → 容器加入），
  不再派发，其余分支照常执行

stdout（唯一输出）：
- 有派发 → [{"task_id","agent","prompt"}, ...]                     exit 0
- 全部 pass/skipped → {"result": "[ALL TASK FINISHED]",
  "skipped": [...]}（skipped 仅存在跳过任务时出现，为全量清单）      exit 0
- 有在飞 → []                                                       exit 0
- 其余（依赖不满足 / fail 未决）→ {"result": "[STUCK]", "reason": …} exit 1
校验/读写失败 → stderr 报错并 exit 2。
"""
import argparse
import json
import os
import sys

import yaml

TOP_KEYS = ("workflow", "max_parallel", "nodes")
TASK_TYPES = ("normal", "subgraph")
NORMAL_KEYS = ("id", "task_type", "title", "goal", "approach", "acceptance",
               "out_of_scope", "depends_on", "executor", "verifier", "max_retries", "on_exhaust")
SUBGRAPH_KEYS = ("id", "task_type", "file", "depends_on")
STR_KEYS = ("id", "title", "executor", "verifier")  # 非空 str
LIST_KEYS = ("goal", "approach", "acceptance", "out_of_scope")  # 非空 list[非空 str]
STATUSES = ("pending", "running", "executed", "verifying", "pass", "fail")
SETTLED = ("pass",)
IN_FLIGHT = ("running", "verifying")


def fail(msg):
    print("[get_task] 错误: %s" % msg, file=sys.stderr)
    return 2


def is_str(v):
    return isinstance(v, str) and v.strip()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_node_set(nodes, allow_subgraph):
    """校验节点列表（键集/类型/id 唯一/依赖存在/无环）；通过返回 None，否则首个错误。"""
    if not isinstance(nodes, list) or not nodes:
        return "nodes 必须是非空 list"
    ids, deps = [], {}
    for i, node in enumerate(nodes):
        where = "nodes[%d]" % i
        if not isinstance(node, dict):
            return where + " 必须是 mapping"
        tt = node.get("task_type")
        if tt not in TASK_TYPES:
            return "%s.task_type 必须是 %s 之一" % (where, "/".join(TASK_TYPES))
        if not allow_subgraph and tt != "normal":
            return "%s 子图内只允许 normal 节点（不支持嵌套 subgraph）" % where
        keys = NORMAL_KEYS if tt == "normal" else SUBGRAPH_KEYS
        missing = set(keys) - set(node)
        extra = set(node) - set(keys)
        if missing or extra:
            return "%s(%s) 键不符: 缺 %s 多 %s" % (where, tt, sorted(missing), sorted(extra))
        for k in ("id", "file") if tt == "subgraph" else STR_KEYS:
            if not is_str(node[k]):
                return "%s.%s 必须是非空 str" % (where, k)
        if tt == "normal":
            for k in LIST_KEYS:
                v = node[k]
                if not isinstance(v, list) or not v or not all(is_str(s) for s in v):
                    return "%s.%s 必须是非空 list[非空 str]" % (where, k)
            if not is_int(node["max_retries"]) or node["max_retries"] < 0:
                return "%s.max_retries 必须是 >= 0 的 int" % where
            if node["on_exhaust"] not in ("continue", "exit"):
                return "%s.on_exhaust 必须是 continue/exit 之一" % where
        d = node["depends_on"]
        if not isinstance(d, list) or not all(is_str(s) for s in d):
            return "%s.depends_on 必须是 list[str]（无依赖用 []）" % where
        if node["id"] in ids:
            return "节点 id 重复: %s" % node["id"]
        ids.append(node["id"])
        deps[node["id"]] = d

    for tid, d in deps.items():
        unknown = [x for x in d if x not in deps]
        if unknown:
            return "%s.depends_on 引用不存在的节点: %s" % (tid, unknown)

    state, stack = [], []  # state: 1=访问中 2=完成; stack: 当前 DFS 路径
    def visit(tid):
        state.append(tid)
        stack.append(tid)
        for dep in deps[tid]:
            if dep in stack:
                return stack[stack.index(dep):] + [dep]
            if dep not in state:
                c = visit(dep)
                if c:
                    return c
        stack.pop()
        return None
    for tid in deps:  # ponytail: 递归 DFS，超深依赖链（>1000 层）时再改迭代
        if tid not in state:
            cyc = visit(tid)
            if cyc:
                return "依赖成环: %s" % " -> ".join(cyc)
    return None


def validate_workflow(config):
    """校验 workflow yaml 契约；通过返回 None，否则返回错误信息（首个错误即失败）。"""
    if not isinstance(config, dict):
        return "workflow yaml 顶层必须是 mapping"
    missing = set(TOP_KEYS) - set(config)
    extra = set(config) - set(TOP_KEYS)
    if missing or extra:
        return "顶层键不符: 缺 %s 多 %s（应恰好 %s）" % (
            sorted(missing), sorted(extra), "/".join(TOP_KEYS))
    if not is_str(config["workflow"]):
        return "workflow 必须是非空 str"
    if not is_int(config["max_parallel"]) or config["max_parallel"] < 1:
        return "max_parallel 必须是 >= 1 的 int"
    return validate_node_set(config["nodes"], allow_subgraph=True)


def load_subgraph(path):
    """加载子图 yaml（顶层恰好 nodes 键，节点均 normal）；返回 (nodes, err)。"""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        return None, "读取失败: %s" % e
    if not isinstance(cfg, dict) or set(cfg) != {"nodes"}:
        return None, "顶层必须恰好一个 nodes 键"
    err = validate_node_set(cfg["nodes"], allow_subgraph=False)
    if err:
        return None, err
    return cfg["nodes"], None


def compute_skipped_tasks(stream, tasks, node_by_id, sub_ids):
    """跳过任务集合：fail+exhausted+on_exhaust=continue 为种子，沿依赖边传递到全部下游。

    种子永远不会 pass，其（传递）依赖者也就永远不会被派发，一并跳过。
    子图容器两条互斥的加入途径（已物化容器的依赖必全 pass，pass 终态不会成种子）：
    - 未物化：容器自身 depends_on 命中跳过集合；
    - 已物化：全部子任务 ∈ {pass}∪跳过集合 且至少一个 ∈ 跳过集合。
    """
    node_of = {tid: node for node, tid, _ in stream}
    dep_of = {tid: deps for _, tid, deps in stream}
    skipped = set()
    for tid, entry in tasks.items():
        if entry.get("status") == "fail" and entry.get("exhausted"):
            node = node_of.get(tid)
            if node is not None and node["on_exhaust"] == "continue":
                skipped.add(tid)
    growing = True
    while growing:
        growing = False
        for tid, deps in dep_of.items():
            if tid not in skipped and any(d in skipped for d in deps):
                skipped.add(tid)
                growing = True
        for sg in sub_ids:
            if sg in skipped:
                continue
            if any(d in skipped for d in node_by_id[sg]["depends_on"]):
                skipped.add(sg)
                growing = True
                continue
            kids = [k for k in dep_of if k.startswith(sg + "/")]
            if kids and any(k in skipped for k in kids) and all(
                    k in skipped or tasks[k]["status"] == "pass" for k in kids):
                skipped.add(sg)
                growing = True
    return skipped


def build_prompt(node, phase, work_dir, user_prompt):
    """execute 阶段含 Approach 与 executed 协议句；verify 阶段无 Approach，要求 pass/fail。"""
    def block(name, items):
        return "%s:\n%s" % (name, "\n".join("- " + s for s in items))
    parts = ["$WORK_DIR=%s" % work_dir, "$USER_PROMPT=%s" % user_prompt,
             "[%s] %s" % (node["id"], node["title"]), block("Goal", node["goal"])]
    if phase == "execute":
        parts.append(block("Approach", node["approach"]))
    parts += [block("Acceptance", node["acceptance"]), block("Out-of-Scope", node["out_of_scope"])]
    parts.append("After finishing, reply with only: executed" if phase == "execute"
                 else "After verifying, reply with only: pass or fail")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Workflow task dispatcher")
    parser.add_argument("work_dir", help="working directory (must contain .workflow/status.json)")
    args = parser.parse_args()

    status_path = os.path.join(args.work_dir, ".workflow", "status.json")
    if not os.path.isfile(status_path):
        return fail("工作流未初始化(%s 不存在)，请先运行 orchestrator.py" % status_path)
    try:
        with open(status_path, encoding="utf-8") as f:
            status = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return fail("status.json 读取失败: %s" % e)
    if not is_str(status.get("workflow")) or not os.path.isfile(status["workflow"]):
        return fail("status.json 的 workflow 指向不存在的 yaml: %r" % status.get("workflow"))
    try:
        with open(status["workflow"], encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return fail("workflow yaml 解析失败: %s" % e)

    err = validate_workflow(config)
    if err:
        return fail(err)

    tasks = status.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        return fail("status.json 的 tasks 必须是非空 mapping")
    node_by_id = {n["id"]: n for n in config["nodes"]}
    sub_ids = {i for i, n in node_by_id.items() if n["task_type"] == "subgraph"}
    # subgraph 是分组不是任务，不落状态；旧账本遗留的容器条目在此剔除
    stale = sub_ids & set(tasks)
    for tid in stale:
        del tasks[tid]
    missing = set(node_by_id) - sub_ids - set(tasks)
    if missing:
        return fail("status.json 缺少任务状态: %s（yaml 与 status 不一致，请重新初始化）" % sorted(missing))
    for tid, entry in tasks.items():
        top = tid.split("/", 1)[0]
        known = tid in node_by_id or ("/" in tid and top in sub_ids)
        ok = known and isinstance(entry, dict) and entry.get("status") in STATUSES
        if not ok:
            if not known:
                return fail("status.json 含未知任务 id: %s" % tid)
            return fail("status.json 任务 %s 状态非法: %r（应 %s 之一）" % (tid, entry, "/".join(STATUSES)))
    up_path = status.get("user_prompt")
    if not is_str(up_path) or not os.path.isfile(up_path):
        return fail("status.json 的 user_prompt 指向不存在的文件: %r" % up_path)
    work_dir = status.get("work_dir") or os.path.abspath(args.work_dir)

    def eff(tid, skipped=frozenset()):
        """有效状态：跳过集合内 → skipped；subgraph 由子任务实时聚合
        （无子任务=pending，全 pass=pass，否则 running）。容器不进 status.json。

        skipped 显式传参：materialize 阶段用默认空集（跳过集合彼时尚未计算，
        维持旧语义）；stream 构建后各调用点传 compute_skipped_tasks 的结果。
        """
        if tid in skipped:
            return "skipped"
        if tid not in sub_ids:
            return tasks[tid]["status"]
        kids = [k for k in tasks if k.startswith(tid + "/")]
        if not kids:
            return "pending"
        return "pass" if all(tasks[k]["status"] == "pass" for k in kids) else "running"

    # 物化：subgraph 依赖全 pass 时注册子任务（幂等、只增），并写回 status.json
    subs, changed = {}, bool(stale)
    for node in config["nodes"]:
        if node["task_type"] != "subgraph":
            continue
        tid = node["id"]
        if eff(tid) in SETTLED or not all(eff(d) == "pass" for d in node["depends_on"]):
            continue
        fpath = node["file"] if os.path.isabs(node["file"]) else os.path.join(work_dir, node["file"])
        if not os.path.isfile(fpath):
            return fail("subgraph %s 依赖已满足但 file 不存在: %s" % (tid, fpath))
        sub, err = load_subgraph(fpath)
        if err:
            return fail("subgraph %s 校验失败(%s): %s" % (tid, fpath, err))
        subs[tid] = sub
        for child in sub:
            kid = "%s/%s" % (tid, child["id"])
            if kid not in tasks:
                tasks[kid] = {"status": "pending", "retries": 0}
                changed = True
    # 重试策略：预算内 fail → pending 重试；超预算 → exhausted 标记，
    # on_exhaust=exit 短路 STUCK；continue 交由跳过任务集合处理
    exhausted_exit = []
    for tid, entry in tasks.items():
        if entry.get("status") != "fail":
            continue
        node = node_by_id.get(tid)
        if node is None:  # 子图子任务：从本轮加载的子图里找（fail 子任务必属活跃子图）
            top = tid.split("/", 1)[0]
            node = next((c for c in subs.get(top, []) if "%s/%s" % (top, c["id"]) == tid), None)
        if node is None:
            continue
        if entry.get("retries", 0) <= node["max_retries"]:
            entry["status"] = "pending"
            entry.pop("exhausted", None)  # 用户调大 max_retries 后重试，清除历史耗尽标记
            changed = True
        else:
            if not entry.get("exhausted"):
                entry["exhausted"] = True
                changed = True
            if node["on_exhaust"] == "exit":
                exhausted_exit.append("%s (重试预算耗尽 retries=%d > max_retries=%d)"
                                      % (tid, entry.get("retries", 0), node["max_retries"]))
    if changed:
        try:
            tmp = status_path + ".tmp"  # 原子写：写半截崩溃不损坏旧文件
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, status_path)
        except OSError as e:
            return fail("status.json 写回失败: %s" % e)
    if exhausted_exit:
        print(json.dumps({"result": "[STUCK]", "reason": "; ".join(exhausted_exit)}, ensure_ascii=False))
        return 1

    # 扁平候选流（yaml 顺序）：subgraph → 其子任务（子 yaml 顺序，依赖映射为 父/子 id）
    stream = []
    for node in config["nodes"]:
        if node["task_type"] == "subgraph":
            stream.extend((c, "%s/%s" % (node["id"], c["id"]),
                           ["%s/%s" % (node["id"], d) for d in c["depends_on"]])
                          for c in subs.get(node["id"], []))
        else:
            stream.append((node, node["id"], node["depends_on"]))

    # 跳过任务集合：以下所有 eff() 调用显式传入
    skipped_tasks = compute_skipped_tasks(stream, tasks, node_by_id, sub_ids)

    limit = config["max_parallel"] - sum(
        1 for t in tasks.values() if t.get("status") in IN_FLIGHT)
    batch = []
    for node, tid, deps in stream:
        if len(batch) >= limit:
            break
        st = tasks[tid]["status"]
        if st == "executed":
            phase = "verify"  # 验证不受依赖回归影响
        elif st == "pending" and all(eff(d, skipped_tasks) == "pass" for d in deps):
            phase = "execute"
        else:
            continue
        batch.append({
            "task_id": tid,
            "agent": node["executor"] if phase == "execute" else node["verifier"],
            "prompt": build_prompt(node, phase, work_dir, up_path),
        })

    if batch:
        print(json.dumps(batch, ensure_ascii=False, indent=2))
        return 0
    effs = {tid: eff(tid, skipped_tasks) for tid in node_by_id}
    if all(s in SETTLED or s == "skipped" for s in effs.values()):
        result = {"result": "[ALL TASK FINISHED]"}
        if skipped_tasks:
            result["skipped"] = sorted(skipped_tasks)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if any(s in IN_FLIGHT for s in effs.values()):
        print("[]")
        return 0
    reasons = []
    for tid, node in node_by_id.items():
        if effs[tid] == "skipped":
            continue
        if effs[tid] == "fail":
            reasons.append("%s (fail 未决)" % tid)
        elif effs[tid] == "pending":
            unmet = [d for d in node["depends_on"] if eff(d, skipped_tasks) != "pass"]
            if unmet:
                reasons.append("%s (依赖未满足: %s)" % (tid, ", ".join(unmet)))
    print(json.dumps({"result": "[STUCK]", "reason": "; ".join(reasons)}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
