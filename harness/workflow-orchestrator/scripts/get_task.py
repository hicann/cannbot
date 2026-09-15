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
（顶层 workflow/max_parallel/nodes + 可选 max_rollbacks（缺省 1）/system_prompt；normal 12 键 + 可选 rollback_to/procedure / subgraph 4 键；
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
  不再派发，其余分支照常执行；rollback → 置 rollback_pending 粘滞标记：有在飞则输出 []
  排干，无在飞执行回滚（归档 .workflow/history → 恢复 checkpoint(rollback_to) →
  按 pass_seq 规则重置），返回 advice 阶段任务，产物就绪后恢复正常调度；
  rollbacks_used ≥ max_rollbacks 时同 exit 进 [STUCK]

stdout（唯一输出）：
- 有派发 → [{"task_id","agent","prompt"}, ...]                     exit 0
- 全部 pass/skipped → {"result": "[ALL TASK FINISHED]",
  "skipped": [...]}（skipped 仅存在跳过任务时出现，为全量清单）      exit 0
- 有在飞 → []                                                       exit 0
- 其余（依赖不满足 / fail 未决）→ {"result": "[STUCK]", "reason": …} exit 1
校验/读写失败 → stderr 报错并 exit 2。
"""
import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass

import yaml

import orchestrator as orch  # 复用工作区快照与事件日志工具；agent 仅由 orchestrator 执行

TOP_KEYS = ("workflow", "max_parallel", "nodes")
OPTIONAL_TOP_KEYS = ("max_rollbacks", "system_prompt")  # 顶层可选键
TASK_TYPES = ("normal", "subgraph")
NORMAL_KEYS = ("id", "task_type", "title", "goal", "approach", "acceptance",
               "out_of_scope", "depends_on", "executor", "verifier", "max_retries", "on_exhaust")
OPTIONAL_NORMAL_KEYS = ("rollback_to", "procedure")
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


def _validate_node_structure(nodes, allow_subgraph):
    """校验每个节点的键集/类型/id 唯一；返回 (deps, err)，deps = {id: depends_on}。"""
    ids, deps = [], {}
    for i, node in enumerate(nodes):
        where = "nodes[%d]" % i
        if not isinstance(node, dict):
            return None, where + " 必须是 mapping"
        tt = node.get("task_type")
        if tt not in TASK_TYPES:
            return None, "%s.task_type 必须是 %s 之一" % (where, "/".join(TASK_TYPES))
        if not allow_subgraph and tt != "normal":
            return None, "%s 子图内只允许 normal 节点（不支持嵌套 subgraph）" % where
        keys = NORMAL_KEYS if tt == "normal" else SUBGRAPH_KEYS
        missing = set(keys) - set(node)
        extra = set(node) - set(keys)
        if tt == "normal":
            extra -= set(OPTIONAL_NORMAL_KEYS)
        if missing or extra:
            return None, "%s(%s) 键不符: 缺 %s 多 %s" % (where, tt, sorted(missing), sorted(extra))
        for k in ("id", "file") if tt == "subgraph" else STR_KEYS:
            if not is_str(node[k]):
                return None, "%s.%s 必须是非空 str" % (where, k)
        if tt == "normal":
            for k in LIST_KEYS + (("procedure",) if "procedure" in node else ()):
                v = node[k]
                if not isinstance(v, list) or not v or not all(is_str(s) for s in v):
                    return None, "%s.%s 必须是非空 list[非空 str]" % (where, k)
            if not is_int(node["max_retries"]) or node["max_retries"] < 0:
                return None, "%s.max_retries 必须是 >= 0 的 int" % where
            if node["on_exhaust"] not in ("continue", "exit", "rollback"):
                return None, "%s.on_exhaust 必须是 continue/exit/rollback 之一" % where
        d = node["depends_on"]
        if not isinstance(d, list) or not all(is_str(s) for s in d):
            return None, "%s.depends_on 必须是 list[str]（无依赖用 []）" % where
        if "/" in node["id"]:
            return None, "%s.id 不能包含 '/'（该字符仅用于子图命名空间分隔）" % where
        if node["id"] in ids:
            return None, "节点 id 重复: %s" % node["id"]
        ids.append(node["id"])
        deps[node["id"]] = d
    return deps, None


def _validate_dependency_edges(deps):
    """校验 depends_on 引用存在且无环；通过返回 None，否则错误信息。"""
    for tid, d in deps.items():
        unknown = [x for x in d if x not in deps]
        if unknown:
            return "%s.depends_on 引用不存在的节点: %s" % (tid, unknown)

    state, stack = [], []  # state: 访问过的节点; stack: 当前 DFS 路径

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


def _validate_rollback_targets(nodes, deps):
    """校验 rollback_to：仅 on_exhaust=rollback 时生效，须指向传递上游普通节点。"""
    types = {n["id"]: n.get("task_type") for n in nodes}
    for node in nodes:
        if node.get("task_type") != "normal" or node.get("on_exhaust") != "rollback":
            continue  # on_exhaust!=rollback 时 rollback_to 完全忽略（不校验、不生效）
        rt = node.get("rollback_to")
        if not is_str(rt):
            return "节点 %s on_exhaust=rollback 时必须配置非空 str 的 rollback_to" % node["id"]
        if rt not in deps:
            return "节点 %s rollback_to 引用不存在的节点: %s" % (node["id"], rt)
        if types.get(rt) != "normal":
            return "节点 %s rollback_to 不能指向 subgraph 容器: %s" % (node["id"], rt)
        seen, frontier = set(), list(deps[node["id"]])  # 传递上游闭包
        while frontier:
            cur = frontier.pop()
            if cur in seen:
                continue
            seen.add(cur)
            frontier.extend(deps.get(cur, []))
        if rt not in seen:
            return "节点 %s rollback_to 必须是其（传递）上游节点: %s" % (node["id"], rt)
    return None


def validate_node_set(nodes, allow_subgraph):
    """校验节点列表（键集/类型/id 唯一/依赖存在/无环/rollback_to）；通过返回 None，否则首个错误。"""
    if not isinstance(nodes, list) or not nodes:
        return "nodes 必须是非空 list"
    deps, err = _validate_node_structure(nodes, allow_subgraph)
    if err:
        return err
    err = _validate_dependency_edges(deps)
    if err:
        return err
    return _validate_rollback_targets(nodes, deps)


def validate_workflow(config):
    """校验 workflow yaml 契约；通过返回 None，否则返回错误信息（首个错误即失败）。"""
    if not isinstance(config, dict):
        return "workflow yaml 顶层必须是 mapping"
    missing = set(TOP_KEYS) - set(config)
    extra = set(config) - set(TOP_KEYS) - set(OPTIONAL_TOP_KEYS)
    if missing or extra:
        return "顶层键不符: 缺 %s 多 %s（应恰好 %s，可选 %s）" % (
            sorted(missing), sorted(extra), "/".join(TOP_KEYS), "/".join(OPTIONAL_TOP_KEYS))
    if "system_prompt" in config and not is_str(config["system_prompt"]):
        return "system_prompt 必须是非空 str"
    if not is_str(config["workflow"]):
        return "workflow 必须是非空 str"
    if not is_int(config["max_parallel"]) or config["max_parallel"] < 1:
        return "max_parallel 必须是 >= 1 的 int"
    mr = config.get("max_rollbacks", 1)
    if not is_int(mr) or mr < 0:
        return "max_rollbacks 必须是 >= 0 的 int"
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


def collect_checkpoint_targets(nodes, subs):
    """Return fully qualified normal-task ids referenced by ``rollback_to``.

    Top-level nodes already use their workflow namespace. Child nodes use a
    bare id in their subgraph yaml, so materialized child targets are prefixed
    with the containing subgraph id. The returned set is intentionally
    unordered; callers that persist or emit it should sort it for stable
    output.
    """
    targets = {
        node["rollback_to"]
        for node in nodes
        if (node.get("task_type") == "normal"
            and node.get("on_exhaust") == "rollback"
            and is_str(node.get("rollback_to")))
    }
    for subgraph_id, children in subs.items():
        targets.update(
            "%s/%s" % (subgraph_id, child["rollback_to"])
            for child in children
            if (child.get("on_exhaust") == "rollback"
                and is_str(child.get("rollback_to")))
        )
    return targets


def create_checkpoints(work_dir, status, status_path, execute_ids, checkpoint_targets):
    """Snapshot rollback targets before returning their first execute task.

    The checkpoint metadata is persisted before the batch is emitted so a
    repeated ``get_task`` call cannot replace an established baseline.
    """
    changed = False
    for tid in execute_ids:
        if tid not in checkpoint_targets:
            continue
        entry = status["tasks"].get(tid)
        if not isinstance(entry, dict) or "checkpoint_seq" in entry:
            continue
        checkpoint = os.path.join(work_dir, ".workflow", "checkpoints", tid)
        orch.copy_tree(work_dir, checkpoint)
        entry["checkpoint_seq"] = status.get("seq", 0)
        changed = True
    if changed:
        _save_status(status_path, status)


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


def _node_of(tid, node_by_id, subs):
    """任务 id → yaml 节点（顶层 normal 或本轮物化的子图子任务）；找不到返回 None。"""
    node = node_by_id.get(tid)
    if node is None and "/" in tid:
        top = tid.split("/", 1)[0]
        node = next((c for c in subs.get(top, []) if "%s/%s" % (top, c["id"]) == tid), None)
    return node


def _graph(stream, node_by_id, tasks):
    """正向(children)/反向(parents)邻接：stream 边 + 容器依赖边(dep→容器) + 容器成员边(容器→子任务)。

    subgraph 容器不在 stream 里；不补这两类边，_descendants/_ancestors 就穿不过容器
    （经容器才是下游的节点会漏判，经容器才是上游的节点 advice range 会漏收）。
    """
    children, parents = {}, {}

    def link(parent, child):
        children.setdefault(parent, []).append(child)
        parents.setdefault(child, []).append(parent)
    for _, tid, deps in stream:
        for d in deps:
            link(d, tid)
    for sg, node in node_by_id.items():
        if node.get("task_type") != "subgraph":
            continue
        for d in node["depends_on"]:
            link(d, sg)  # 容器依赖边：dep → 容器
        for tid in tasks:
            if tid.startswith(sg + "/"):
                link(sg, tid)  # 容器成员边：容器 → 已物化子任务
    return children, parents


def _descendants(children, root):
    """root 的传递下游集合（不含自身）；children 为 _graph 的正向邻接。"""
    out, stack = set(), [root]
    while stack:
        for ch in children.get(stack.pop(), []):
            if ch not in out:
                out.add(ch)
                stack.append(ch)
    return out


def _ancestors(parents, root):
    """root 的传递上游集合（含自身）；parents 为 _graph 的反向邻接。"""
    out, stack = set(), [root]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(parents.get(cur, []))
    return out


def _save_status(status_path, status):
    tmp = status_path + ".tmp"  # 原子写：写半截崩溃不损坏旧文件
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, status_path)


@dataclass
class RollbackPlan:
    """一次回滚的标识与产物路径：从 exhausted_task 回滚到 rollback_target 重做。"""
    exhausted_task: str     # 重试耗尽、触发回滚的失败任务
    rollback_target: str    # 回滚目标（要重做的上游任务）
    number: int             # 第几次回滚（从 1 起）
    history_abs: str        # 失败时间线产物归档目录（绝对路径）
    advice_abs: str         # advice 输出路径（绝对路径）
    range_ids: set          # 需分析的 session 任务范围


def build_advice_entry(work_dir, plan):
    """描述 advice 任务；不执行 agent，也不生成占位文档。"""
    sess_dir = os.path.join(work_dir, ".workflow", "sessions")
    sessions = []
    for tid in sorted(plan.range_ids):
        sessions.extend(sorted(glob.glob(os.path.join(sess_dir, tid + ".*.jsonl"))))
    prompt = "\n".join(
        ["调用 workflow-rollback-advice skill 完成回滚失败分析；若该 skill 不可用，按下列要求直接完成。",
         "背景：工作流任务 %s 重试耗尽，已回滚到上游任务 %s，等待 advice 后重做。" % (plan.exhausted_task, plan.rollback_target),
         "输入 1 — session 记录（agent stdout 的 JSONL 存档，按任务与时间顺序阅读）："]
        + ["- " + p for p in sessions]
        + ["输入 2 — 失败时间线的工作产物归档目录：%s（可查阅实际产物佐证分析）" % plan.history_abs,
           "输出：将分析总结写入 %s（覆盖写），含：失败根因、值得保留的做法、应避免的做法、"
           "对 %s 重做的具体建议，并记录上述归档目录路径。" % (plan.advice_abs, plan.rollback_target),
           "工作区已恢复到 checkpoint；仅写 advice 文件，不修改工作产物、历史归档或状态账本。",
           "完成后只回复：advice-written"])
    return {"task_id": "advice-" + os.path.splitext(os.path.basename(plan.advice_abs))[0],
            "phase": "advice", "agent": "general", "prompt": prompt,
            "advice": plan.advice_abs}


def resolve_advice(status, status_path):
    """等待外部 advice 产物；None 表示已就绪，否则输出稳定任务或 STUCK。"""
    pending = status.get("advice_pending")
    if not pending:
        return None
    if pending.get("error"):
        print(json.dumps({"result": "[STUCK]", "reason": "advice 生成失败: %s" % pending["error"]},
                         ensure_ascii=False))
        return 1
    try:
        with open(pending["advice"], encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""
    except (OSError, UnicodeError) as e:
        pending["error"] = "advice 文件读取失败: %s" % e
        _save_status(status_path, status)
        return resolve_advice(status, status_path)
    if not content.strip():
        entry = {k: pending[k] for k in ("task_id", "agent", "phase", "prompt", "advice")}
        print(json.dumps([entry], ensure_ascii=False, indent=2))
        return 0
    status["tasks"][pending["to"]]["advice"] = pending["advice"]
    del status["advice_pending"]
    _save_status(status_path, status)
    return None


def _keep_continue_exhausted(st, entry, node, tid, target_descendants):
    """continue-exhausted 且非回滚目标下游的任务在回滚后保持不动（continue 语义延续）。"""
    return (st == "fail" and entry.get("exhausted") and node is not None
            and node.get("on_exhaust") == "continue" and tid not in target_descendants)


def execute_rollback(work_dir, status, status_path, graph, tasks):
    """排干在飞后执行回滚：归档 history → 恢复 checkpoint → 重置状态并排队 advice。

    graph = (stream, node_by_id, subs)：扁平流 / id→节点映射 / subgraph 物化子任务。
    返回 0 = 成功（status 已写回，调用方继续正常批次构建）；
    返回 1 = 无法执行（已输出 [STUCK]，rollback_pending 留账供排查）。
    """
    stream, node_by_id, subs = graph
    pend = status["rollback_pending"]
    exhausted_task, rollback_target = pend["from"], pend["to"]
    target_entry = tasks.get(rollback_target)
    ckpt_seq = target_entry.get("checkpoint_seq") if isinstance(target_entry, dict) else None
    ckpt_dir = os.path.join(work_dir, ".workflow", "checkpoints", rollback_target)
    if ckpt_seq is None or not os.path.isdir(ckpt_dir):
        print(json.dumps({"result": "[STUCK]",
                          "reason": "rollback 无法执行: %s 缺少 checkpoint（旧账本？）" % rollback_target},
                         ensure_ascii=False))
        return 1
    number = int(status.get("rollbacks_used", 0)) + 1
    stem = "%s.to.%s.%d" % (
        exhausted_task.replace("/", "__"), rollback_target.replace("/", "__"), number)
    history_rel = os.path.join(".workflow", "history", stem)
    history_abs = os.path.join(work_dir, history_rel)
    advice_rel = os.path.join(".workflow", "advice", stem + ".md")
    advice_abs = os.path.join(work_dir, advice_rel)
    # ① 归档失败时间线的全部工作产物（过程资产，永不删除）
    orch.copy_tree(work_dir, history_abs)
    # ② advice：分析 {rollback_target} ∪ (rollback_target 的传递下游 ∩ exhausted_task 的祖先
    #    及自身) 的全部 session（含历史时间线）；邻接经 _graph 补全容器边，可穿过 subgraph 容器
    children, parents = _graph(stream, node_by_id, tasks)
    range_ids = {rollback_target} | (_descendants(children, rollback_target)
                                     & _ancestors(parents, exhausted_task))
    advice_entry = build_advice_entry(work_dir,
                RollbackPlan(exhausted_task=exhausted_task, rollback_target=rollback_target,
                             number=number, history_abs=history_abs, advice_abs=advice_abs,
                             range_ids=range_ids))
    # ③ 恢复 checkpoint(rollback_target)（清空现场后拷回；.workflow 不受影响）
    orch.clear_tree(work_dir)
    orch.copy_tree(ckpt_dir, work_dir)
    # ④ 重置状态：pass 且 pass_seq ≤ checkpoint_seq(rollback_target) 的不动；非目标下游的
    #    continue-exhausted 不动；其余全部回 pending（retries 清零）。所有 checkpoint
    #    目录与 checkpoint_seq 元数据都是已有账本资产，跨回滚永久保留。
    target_descendants = _descendants(children, rollback_target)
    for tid, entry in tasks.items():
        st = entry.get("status")
        if st == "pass" and int(entry.get("pass_seq", 0)) <= ckpt_seq:
            continue
        node = _node_of(tid, node_by_id, subs)
        if _keep_continue_exhausted(st, entry, node, tid, target_descendants):
            continue
        entry["status"] = "pending"
        entry["retries"] = 0
        for k in ("exhausted", "pass_seq", "advice"):
            entry.pop(k, None)
    os.makedirs(os.path.dirname(advice_abs), exist_ok=True)
    status["advice_pending"] = dict(advice_entry, **{
        "from": exhausted_task, "to": rollback_target, "number": number,
        "history": history_abs})
    status["rollbacks_used"] = number
    del status["rollback_pending"]
    _save_status(status_path, status)
    orch.log_event(work_dir, event="rollback", advice=advice_rel, history=history_rel,
                   rollbacks_used=number, **{"from": exhausted_task, "to": rollback_target})
    return 0


def build_prompt(node, phase, work_dir, user_prompt, advice=None, system_prompt=None):
    """execute 阶段含 Approach 与 executed 协议句；verify 阶段要求 pass/fail；advice 仅 execute 阶段注入；
    system_prompt 配置后以 "System-Prompt:" 前缀块插到 prompt 最顶部（两阶段均注入）。"""

    def block(name, items):
        return "%s:\n%s" % (name, "\n".join("- " + s for s in items))
    parts = ["$WORK_DIR=%s" % work_dir, "$USER_PROMPT=%s" % user_prompt]
    if system_prompt:
        parts.append("$SYSTEM_PROMPT=%s" % system_prompt)
    parts += ["[%s] %s" % (node["id"], node["title"]), block("Goal", node["goal"])]
    if phase == "execute":
        parts.append(block("Approach", node["approach"]))
        if advice:
            with open(advice, encoding="utf-8") as f:
                advice_content = f.read()
            parts.append("Rollback-Advice: %s\n%s" % (advice, advice_content))
    elif phase == "verify" and "procedure" in node:
        parts.append(block("Procedure", node["procedure"]))
    parts += [block("Acceptance", node["acceptance"]), block("Out-of-Scope", node["out_of_scope"])]
    parts.append("After finishing, reply with only: executed" if phase == "execute"
                 else "After verifying, reply with only: pass or fail")
    return "\n".join(parts)


def _queue_rollback(status, tid, node, max_rollbacks):
    """on_exhaust=rollback 的裁决：置 rollback_pending 或返回预算耗尽的 STUCK 消息。

    返回 (queued, stuck)：queued=True 表示本次新置了 rollback_pending（需写回 status）；
    stuck=消息 表示回滚预算耗尽，应进 exhausted_exit（同 exit 短路）。二者互斥。
    """
    if "rollback_pending" in status:
        return False, None  # 已有待执行回滚：本节点留待回滚执行时一并重置（免费重做）
    if status.get("rollbacks_used", 0) >= max_rollbacks:
        return False, "%s (回滚预算耗尽 rollbacks_used=%d >= max_rollbacks=%d)" % (
            tid, status.get("rollbacks_used", 0), max_rollbacks)
    to = node["rollback_to"]
    if "/" in tid:  # 子图子任务：rollback_to 是子图命名空间内的裸 id，拼父级前缀
        to = tid.rsplit("/", 1)[0] + "/" + to
    status["rollback_pending"] = {"from": tid, "to": to}
    return True, None


def _apply_retry_strategy(tasks, node_by_id, subs, status, max_rollbacks):
    """重试策略：预算内 fail→pending 重试；超预算→exhausted 标记 + on_exhaust 分流。

    返回 (changed, exhausted_exit)：changed 表示 status 有变需写回；
    exhausted_exit 为 exit/回滚预算耗尽的 STUCK 消息列表（非空应短路）。
    """
    changed, exhausted_exit = False, []
    for tid, entry in tasks.items():
        if entry.get("status") != "fail":
            continue
        node = _node_of(tid, node_by_id, subs)
        if node is None:
            continue
        if entry.get("retries", 0) <= node["max_retries"]:
            entry["status"] = "pending"
            entry.pop("exhausted", None)  # 用户调大 max_retries 后重试，清除历史耗尽标记
            changed = True
            continue
        if not entry.get("exhausted"):
            entry["exhausted"] = True
            changed = True
        if node["on_exhaust"] == "exit":
            exhausted_exit.append("%s (重试预算耗尽 retries=%d > max_retries=%d)"
                                  % (tid, entry.get("retries", 0), node["max_retries"]))
        elif node["on_exhaust"] == "rollback":
            queued, stuck = _queue_rollback(status, tid, node, max_rollbacks)
            if queued:
                changed = True
            elif stuck:
                exhausted_exit.append(stuck)
        # else continue：交由跳过任务集合处理（这里只标记 exhausted）
    return changed, exhausted_exit


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

    max_rollbacks = config.get("max_rollbacks", 1)  # 顶层可选键，validate_workflow 已校验类型

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

    advice_result = resolve_advice(status, status_path)
    if advice_result is not None:
        return advice_result

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
    # Keep targets discovered during an earlier materialization pass: after a
    # rollback, a subgraph can be pending again and therefore not materialized
    # in this pass, but its child checkpoints must remain addressable.
    checkpoint_target_set = set(status.get("checkpoint_targets") or ())
    checkpoint_target_set.update(collect_checkpoint_targets(config["nodes"], subs))
    checkpoint_targets = sorted(checkpoint_target_set)
    if status.get("checkpoint_targets") != checkpoint_targets:
        status["checkpoint_targets"] = checkpoint_targets
        changed = True
    # 重试策略：预算内 fail → pending 重试；超预算 → exhausted 标记 + on_exhaust 分流
    retry_changed, exhausted_exit = _apply_retry_strategy(
        tasks, node_by_id, subs, status, max_rollbacks)
    changed = changed or retry_changed
    if changed:
        try:
            _save_status(status_path, status)
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

    # 回滚：有在飞则输出 [] 由 orchestrator 现有等待逻辑自然排干；
    # 无在飞则执行（归档→advice→恢复→重置），随后按新状态正常构建批次
    if status.get("rollback_pending"):
        if any(t.get("status") in IN_FLIGHT for t in tasks.values()):
            print("[]")
            return 0
        rc = execute_rollback(work_dir, status, status_path,
                              (stream, node_by_id, subs), tasks)
        if rc:
            return rc
        return resolve_advice(status, status_path)

    # 跳过任务集合：以下所有 eff() 调用显式传入
    skipped_tasks = compute_skipped_tasks(stream, tasks, node_by_id, sub_ids)

    limit = config["max_parallel"] - sum(
        1 for t in tasks.values() if t.get("status") in IN_FLIGHT)
    batch = []
    execute_ids = []
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
            "prompt": build_prompt(node, phase, work_dir, up_path, tasks[tid].get("advice"),
                                   system_prompt=config.get("system_prompt")),
        })
        if phase == "execute":
            execute_ids.append(tid)

    if batch:
        try:
            create_checkpoints(work_dir, status, status_path, execute_ids,
                               set(checkpoint_targets))
        except OSError as e:
            return fail("checkpoint 创建失败: %s" % e)
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
