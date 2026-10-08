#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""轮询工作流状态（skill 等待循环用，只读）。

python3 poll_workflow.py --work-dir <dir>

stdout 即本轮要展示给用户的文本（调用方原样转播，不做任何加工），三段按序
以空行分隔，全空则无输出：
1. 关键事件行（仅增量：自上次调用以来 log.jsonl 的新增事件中筛选 update/
   rollback/approval/approval_ignored 渲染；init/verdict 等其余类型与解析失败
   的行除外——解析失败的行原文展示不丢信息）：
   [HH:MM:SS] <task_id>: <from> → <to>（→ awaiting_approval 时附"（进入待审批）"）
   [HH:MM:SS] 回滚 <from> → <to>
   [HH:MM:SS] <task_id>: 审批 <decision>（：comment 截断 80 字）
   [HH:MM:SS] 审批被忽略：<task_id>（reason）
2. 进展块（每轮输出，作心跳——长任务执行期间无新事件时用户也能看到当前
   进度）：首行进度条 + 完成百分比（pass/总数；有 fail/待审批时附计数），
   其下约 5 行任务窗口分三段——最近完成（按 pass_seq，新近的靠下，最多
   2 条）→ 进行中/待审批/失败（须关注的全部）→ 接下来待执行；各段截断
   处以 … 示意，收尾阶段窗口由已完成回填：✓ pass、▶ running/executed/
   verifying、◉ 待审批、○ pending、✗ fail
3. 待审批条目（awaiting_approval 且无审批文件，审批文件即 .workflow/approvals/
   <百分号编码 task_id>.json，与 approve_task.py 写入路径一致）：
   ◉ 待审批 <task_id>「<title>」
     验收：
     - <acceptance 每项一行>
     确认提示：
     - <require_approval 为列表形式时的每项提示；为 true 时无此段>
   title/acceptance/require_approval 从 workflow yaml（含子图文件）解析

已读事件偏移持久化在 .workflow/skill_poll.state，调用方无需记账。log.jsonl
只增不删（回滚也是追加事件），偏移量单调安全。status.json 不存在（编排器
尚未初始化）→ 仅可能有事件段；log/status 都不存在 → 无输出，exit 0；
读取/解析失败 → stderr 报错 exit 2（状态不落盘，下轮重试不丢事件）。
先写 stdout 再落状态：中途崩溃宁可下轮重播。无待审批任务时不加载 yaml
（事件与进展只需 log/status，title/acceptance 才读 yaml）。
"""

import argparse
import json
import logging
import os
import sys

import yaml

import approve_task  # 复用审批文件路径的百分号编码
import get_task  # 复用 yaml 契约校验与子图加载

STATE_NAME = "skill_poll.state"
WINDOW = 5  # 任务窗口行数
BAR_WIDTH = 20  # 进度条格数
MARKERS = {
    "pass": "✓",
    "fail": "✗",
    "pending": "○",
    "running": "▶",
    "executed": "▶",
    "verifying": "▶",
    "awaiting_approval": "◉",
}
ACTIVE = ("running", "executed", "verifying", "awaiting_approval")
STATUS_LABELS = {"awaiting_approval": "待审批"}  # 其余状态名原样展示
OUTPUT_LOGGER = logging.getLogger("poll_workflow.output")
OUTPUT_LOGGER.setLevel(logging.INFO)


def _write_output(text):
    """通过 logging 输出展示文本，保持 stdout 的原始内容契约。"""
    if not OUTPUT_LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        OUTPUT_LOGGER.addHandler(handler)
        OUTPUT_LOGGER.propagate = False
    OUTPUT_LOGGER.info(text)
    for handler in OUTPUT_LOGGER.handlers:
        handler.flush()


def fail(msg):
    logging.basicConfig(format="%(message)s")
    logging.error("[poll_workflow] 错误: %s", msg)
    return 2


def _trunc(text, limit):
    return text[:limit] + "…" if len(text) > limit else text


def render_event(line):
    """单条 log.jsonl 事件 → 展示文本；非关键事件返回 None；解析失败返回原文。"""
    try:
        e = json.loads(line)
    except ValueError:
        return line  # 半截行等：原文展示，不丢信息
    if not isinstance(e, dict):
        return line
    ts = e.get("timestamp") or ""
    ts = ts[11:19] if len(ts) >= 19 else ts
    ev = e.get("event")
    tid = e.get("task_id") or "?"
    if ev == "update":
        frm, to = e.get("from"), e.get("to")
        if not (frm and to):
            return line
        suffix = "（进入待审批）" if to == "awaiting_approval" else ""
        return "[%s] %s: %s → %s%s" % (ts, tid, frm, to, suffix)
    if ev == "rollback":
        frm, to = e.get("from"), e.get("to")
        if not (frm and to):
            return line
        return "[%s] 回滚 %s → %s" % (ts, frm, to)
    if ev == "approval":
        comment = e.get("comment")
        suffix = "：" + _trunc(comment, 80) if comment else ""
        return "[%s] %s: 审批 %s%s" % (ts, tid, e.get("decision") or "?", suffix)
    if ev == "approval_ignored":
        reason = e.get("reason")
        return "[%s] 审批被忽略：%s%s" % (ts, tid, "（%s）" % reason if reason else "")
    return None  # init/verdict/reset 等非关键事件不展示


def _fmt_task(tid, st):
    suffix = (
        "（%s）" % STATUS_LABELS.get(st, st) if st in ACTIVE or st == "fail" else ""
    )
    return "%s %s%s" % (MARKERS.get(st, "?"), tid, suffix)


def render_progress(task_list):
    """task_list = [[任务 id, 状态, pass_seq], ...]（status.json 顺序）→ 进度条 + 任务窗口文本。

    首行：进度条 + 完成百分比（pass/总数），有 fail/待审批时附计数（须用户行动）。
    任务窗口（约 WINDOW 行，分三段）：最近完成（pass_seq 升序，最新靠下，最多
    2 条）→ 进行中/待审批/失败（须关注，可挤占他段）→ 接下来待执行；
    各段截断处以 … 示意。无进行中且无待执行时（收尾/全部完成），窗口由已完成回填。
    """
    completed = sorted((t for t in task_list if t[1] == "pass"), key=lambda t: t[2])
    middle = [t for t in task_list if t[1] in ACTIVE or t[1] == "fail"]
    pending = [t for t in task_list if t[1] == "pending"]
    total = len(task_list)
    done = len(completed)
    filled = round(BAR_WIDTH * done / total) if total else 0
    head = "进展 %s%s %d%%（%d/%d）" % (
        "█" * filled,
        "░" * (BAR_WIDTH - filled),
        round(100 * done / total) if total else 0,
        done,
        total,
    )
    alerts = [
        "%s %d" % (STATUS_LABELS.get(s, s), sum(1 for _, x, _ in task_list if x == s))
        for s in ("fail", "awaiting_approval")
    ]
    alerts = [a for a in alerts if not a.endswith(" 0")]
    if alerts:
        head += "｜" + " · ".join(alerts)
    lines = [head]

    n_m = min(len(middle), WINDOW)
    n_c = min(len(completed), 2, WINDOW - n_m)
    n_p = min(len(pending), WINDOW - n_m - n_c)
    n_c = min(len(completed), WINDOW - n_m - n_p)  # 回填：收尾/全部完成时

    if len(completed) > n_c:
        lines.append("…")
    lines += [_fmt_task(tid, st) for tid, st, _ in (completed[-n_c:] if n_c else [])]
    lines += [_fmt_task(tid, st) for tid, st, _ in middle[:n_m]]
    if len(middle) > n_m:
        lines.append("…")
    lines += [_fmt_task(tid, st) for tid, st, _ in pending[:n_p]]
    if len(pending) > n_p:
        lines.append("…")
    return "\n".join(lines)


def render_approval(task_id, node):
    """待审批条目：任务 id + 标题 + 验收列表 + 确认提示（require_approval 为 list 时）。"""
    lines = ["◉ 待审批 %s「%s」" % (task_id, node["title"]), "  验收："]
    lines += ["  - %s" % a for a in node["acceptance"]]
    hints = node.get("require_approval")
    if isinstance(hints, list):
        lines.append("  确认提示：")
        lines += ["  - %s" % h for h in hints]
    return "\n".join(lines)


class YamlGraph:
    """workflow yaml 节点查询（顶层 + 按需加载的子图）：取任务定义（title/acceptance）。"""

    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.node_by_id = None  # 完整节点 id → 已加载的节点
        self.sub_cache = {}  # 完整子图节点 id → {局部子节点 id: 节点}
        self.sub_paths = {}  # 完整子图节点 id → 已解析真实文件路径

    def load_main(self, status):
        """加载并校验主 yaml；通过返回 None，否则返回错误信息。"""
        wf_path = status.get("workflow")
        if not get_task.is_str(wf_path) or not os.path.isfile(wf_path):
            return "status.json 的 workflow 指向不存在的 yaml: %r" % wf_path
        try:
            with open(wf_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as e:
            return "workflow yaml 解析失败: %s" % e
        err = get_task.validate_workflow(config)
        if err:
            return err
        self.node_by_id = {n["id"]: n for n in config["nodes"]}
        self.sub_cache.clear()
        self.sub_paths.clear()
        return None

    def load_sub(self, top):
        """按需加载子图文件；返回 ({子任务 id: 节点}, err)。"""
        if top in self.sub_cache:
            return self.sub_cache[top], None
        node = self.node_by_id[top]
        fpath = (
            node["file"]
            if os.path.isabs(node["file"])
            else os.path.join(self.work_dir, node["file"])
        )
        real_path = os.path.realpath(fpath)
        parent = top.rpartition("/")[0]
        while parent:
            if self.sub_paths.get(parent) == real_path:
                return None, "子图 %s 文件循环引用: %s" % (top, fpath)
            parent = parent.rpartition("/")[0]
        nodes, err = get_task.load_subgraph(fpath)
        if err:
            return None, "子图 %s 加载失败(%s): %s" % (top, fpath, err)
        self.sub_cache[top] = {c["id"]: c for c in nodes}
        self.sub_paths[top] = real_path
        self.node_by_id.update({top + "/" + c["id"]: c for c in nodes})
        return self.sub_cache[top], None

    def node_of(self, tid):
        """逐层解析完整任务 id，按需加载各层子图。"""
        parts = tid.split("/")
        for index in range(len(parts)):
            current = "/".join(parts[: index + 1])
            node = self.node_by_id.get(current)
            if node is None:
                return None, "任务 %s 在 yaml 中无对应节点: %s" % (tid, current)
            if index == len(parts) - 1:
                return node, None
            if node.get("task_type") != "subgraph":
                return None, "任务 %s 在 yaml 中找不到所属子图: %s" % (tid, current)
            _, err = self.load_sub(current)
            if err:
                return None, err
        return None, "任务 %s 在 yaml 中无对应节点" % tid


def read_state(wf_dir):
    """读持久化状态；缺失/损坏 → 空 dict（事件全量重播、进展重印，自愈）。"""
    try:
        with open(os.path.join(wf_dir, STATE_NAME), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_state(wf_dir, state):
    """tmp + rename 原子写：写半截崩溃不损坏旧状态；失败抛 OSError。"""
    path = os.path.join(wf_dir, STATE_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_events(wf_dir, state):
    """读取偏移之后的事件；读取失败不推进持久化偏移。"""
    offset = state.get("events_offset")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        offset = 0
    log_path = os.path.join(wf_dir, "log.jsonl")
    if not os.path.isfile(log_path):
        return [], offset, None
    try:
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return [], offset, "log.jsonl 读取失败: %s" % e
    event_lines = []
    for raw in lines[offset:]:
        text = render_event(raw.rstrip("\n"))
        if text:
            event_lines.append(text)
    return event_lines, len(lines), None


def pending_approval_ids(tasks, work_dir):
    """筛选尚未写入审批决定的待审批任务。"""
    pending_ids = []
    for tid, entry in tasks.items():
        if not isinstance(entry, dict) or entry.get("status") != "awaiting_approval":
            continue
        if not os.path.exists(approve_task.approval_file_path(work_dir, tid)):
            pending_ids.append(tid)
    return pending_ids


def approval_sections(status, work_dir, pending_ids):
    """按需读取 yaml 并渲染待审批条目。"""
    if not pending_ids:
        return [], None
    graph = YamlGraph(work_dir)
    err = graph.load_main(status)
    if err:
        return [], err
    blocks = []
    for tid in pending_ids:
        node, err = graph.node_of(tid)
        if err:
            return [], err
        blocks.append(render_approval(tid, node))
    return blocks, None


def status_sections(wf_dir, fallback_work_dir):
    """读取状态并构建进展与审批段；缺少状态文件时无输出。"""
    status_path = os.path.join(wf_dir, "status.json")
    if not os.path.isfile(status_path):
        return [], None
    try:
        with open(status_path, encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return [], "status.json 读取失败: %s" % e
    tasks = status.get("tasks")
    if not isinstance(tasks, dict):
        return [], "status.json 的 tasks 必须是 mapping"
    work_dir = status.get("work_dir") or os.path.abspath(fallback_work_dir)
    task_list = [
        [tid, e.get("status"), int(e.get("pass_seq") or 0)]
        for tid, e in tasks.items()
        if isinstance(e, dict)
    ]
    sections = [render_progress(task_list)]  # 每轮输出，作心跳
    blocks, err = approval_sections(
        status, work_dir, pending_approval_ids(tasks, work_dir)
    )
    if err:
        return [], err
    if blocks:
        sections.append("\n\n".join(blocks))
    return sections, None


def main(argv=None):
    p = argparse.ArgumentParser(
        description="轮询工作流状态（stdout 即待展示文本：事件/进展/待审批），只读"
    )
    p.add_argument("--work-dir", required=True)
    args = p.parse_args(argv)
    wf_dir = os.path.join(args.work_dir, ".workflow")
    state = read_state(wf_dir)
    event_lines, offset, err = read_events(wf_dir, state)
    if err:
        return fail(err)
    sections, err = status_sections(wf_dir, args.work_dir)
    if err:
        return fail(err)
    if event_lines:
        sections.insert(0, "\n".join(event_lines))
    # stdout 是展示接口；先输出并刷新，再落状态，崩溃时宁可重播也不丢事件。
    if sections:
        _write_output("\n\n".join(sections))
    new_state = {"events_offset": offset}
    if new_state != state:
        try:
            write_state(wf_dir, new_state)
        except OSError as e:
            return fail("状态文件写入失败: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
