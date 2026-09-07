#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""Workflow orchestrator — 主循环。

python3 orchestrator.py --yaml <wf.yaml> --work-dir <dir> [--provider opencode]
                        [--prompt <p>] [--dry-run]

启动分流：
- $WORK_DIR/.workflow/status.json 不存在 → 必须 --prompt，委托 init_status.py 初始化后进主循环
- 已存在 → 恢复执行（传了 --prompt 则打警告）；先重置瞬态：running→pending、verifying→executed
  （瞬态是进程内的，崩溃后滞留会造成永久在飞 → 死锁）

主循环（轮次制，D1）：
- get_task.py 出批次 → 主线程逐个 update_status 占坑（pending→running / executed→verifying，
  回复传空串）→ 线程池并发跑 agent → 主线程逐个 update_status 回收（回复由 provider.parse_reply
  从 stdout 提取；原始 stdout 存档到 .workflow/sessions/<task_id>.<phase>.<时间戳>.jsonl）。两次 update 均在主线程串行，避免并发写坏 status.json。
- get_task 输出映射（D3）：batch → 执行；[ALL TASK FINISHED] → 报告 exit 0；
  [STUCK]（重试预算耗尽等）→ 报告 exit 1；[] → 原地重置瞬态再试，连续 3 轮仍空 → exit 2。
- agent 进程退出码非零 = 基础设施故障：立即停机 exit 2，任务留在瞬态，重跑本命令自动恢复。
- 单实例互斥：.workflow/orchestrator.lock（pid + 存活探测，陈旧锁自动接管）。
  所有 status.json 写入均为临时文件 + rename 原子替换，写半截崩溃不损坏旧文件。

--dry-run（UT 专用）：不拉起真 CLI，回复取 $WORK_DIR/.workflow/dry_replies.json：
{"task_id": ["回复", ...]}，FIFO、跨 execute/verify 按调用顺序消费；"$CRASH" 模拟进程
崩溃；未配置/耗尽的条目按阶段给默认回复（execute→executed，verify→pass）。
"""
import argparse
import atexit
import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CRASH = "$CRASH"
MAX_EMPTY_ROUNDS = 3


class Provider(ABC):
    """无头调用 Coding Agent CLI；接入新 CLI（如 claude）= 继承本类 + 注册进 PROVIDERS。"""
    name = ""

    @abstractmethod
    def build_command(self, agent, prompt):
        """返回完整 argv；子进程以 cwd=work_dir 运行。"""

    def parse_reply(self, stdout):
        """从 stdout 提取回复；默认取末条非空行，子类可按 CLI 输出格式覆写。"""
        lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        return lines[-1] if lines else ""


class OpenCodeProvider(Provider):
    name = "opencode"

    def build_command(self, agent, prompt):
        return ["opencode", "run", "--format", "json", "--agent", agent, prompt]

    def parse_reply(self, stdout):
        """--format json 输出 NDJSON 事件流，回复 = 全部 text 事件的 part.text 依序拼接。"""
        texts = []
        for line in stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "text":
                texts.append(ev.get("part", {}).get("text", ""))
        return "\n".join(texts)


class CannbotProvider(OpenCodeProvider):
    name = "cannbot"

    def build_command(self, agent, prompt):
        return ["cannbot", "run", "--format", "json", "--agent", agent, prompt]


class ClaudeProvider(Provider):
    name = "claude"

    def build_command(self, agent, prompt):
        return ["claude", "-p", prompt,
                "--output-format", "json",
                "--dangerously-skip-permissions",
                "--agent", agent]

    def parse_reply(self, stdout):
        """-p --output-format json 输出单个 JSON 对象，回复 = result 字段。"""
        try:
            return json.loads(stdout).get("result", "")
        except json.JSONDecodeError:
            return super().parse_reply(stdout)


class PiProvider(Provider):
    name = "pi"

    def build_command(self, agent, prompt):
        return ["pi", "-p", "--mode", "json", "--no-session", prompt]

    def parse_reply(self, stdout):
        """--mode json 输出 NDJSON 事件流，回复 = 全部 message_end(assistant) 的 text 拼接。"""
        texts = []
        for line in stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "message_end":
                msg = ev.get("message", {})
                if msg.get("role") == "assistant":
                    texts += [c.get("text", "") for c in msg.get("content", [])
                              if c.get("type") == "text"]
        return "\n".join(t for t in texts if t)


class CodexProvider(Provider):
    name = "codex"

    def build_command(self, agent, prompt):
        # --skip-git-repo-check：work_dir 常非 git 仓库，不带此标志 codex 拒绝运行
        return ["codex", "exec", "--json", "--ephemeral",
                "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox", prompt]

    def parse_reply(self, stdout):
        """--json 输出 JSONL 事件流，回复 = 全部 item.completed(agent_message) 的 text 拼接。"""
        texts = []
        for line in stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "item.completed":
                item = ev.get("item", {})
                if item.get("type") == "agent_message":
                    texts.append(item.get("text", ""))
        return "\n".join(t for t in texts if t)


PROVIDERS = {p.name: p for p in (OpenCodeProvider(), CannbotProvider(), ClaudeProvider(), PiProvider(), CodexProvider())}


def err(msg):
    print("[orchestrator] 错误: %s" % msg, file=sys.stderr)
    return 2


def log_event(work_dir, **kv):
    kv = dict(kv, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    with open(os.path.join(work_dir, ".workflow", "log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(kv, ensure_ascii=False) + "\n")


def load_status(work_dir):
    with open(os.path.join(work_dir, ".workflow", "status.json"), encoding="utf-8") as f:
        return json.load(f)


def save_status(work_dir, status):
    path = os.path.join(work_dir, ".workflow", "status.json")
    tmp = path + ".tmp"  # 原子写：写半截崩溃不损坏旧文件
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(work_dir):
    """单实例互斥：pid 锁 + 存活探测；陈旧锁自动接管，正常退出释放。
    ponytail: 双启动竞窗（同微秒首启）未做 O_EXCL，双启间隔够大即安全。"""
    lock = os.path.join(work_dir, ".workflow", "orchestrator.lock")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    if os.path.exists(lock):
        try:
            pid = int(open(lock, encoding="utf-8").read().strip() or 0)
        except (ValueError, OSError):
            pid = 0
        if pid and pid != os.getpid() and alive(pid):
            return None
    with open(lock, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(lock) and os.unlink(lock))
    return lock


def reset_transient(work_dir):
    """瞬态重置（崩溃恢复 / [] 空轮自愈）：running→pending、verifying→executed。"""
    status = load_status(work_dir)
    hits = [t for t in status["tasks"].values() if t["status"] in ("running", "verifying")]
    if not hits:
        return 0
    for t in hits:
        t["status"] = "pending" if t["status"] == "running" else "executed"
    save_status(work_dir, status)
    log_event(work_dir, event="reset", tasks=len(hits))
    return len(hits)


def session_path(work_dir, task_id, phase):
    """会话存档路径；进程启动前创建，stdout 流式写入，监控可实时读到。"""
    d = os.path.join(work_dir, ".workflow", "sessions")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.%s.%s.jsonl" % (task_id, phase, datetime.now().strftime("%Y%m%dT%H%M%S")))


def dry_reply(dry_map, task_id, phase):
    seq = dry_map.get(task_id)
    if isinstance(seq, list) and seq:
        return str(seq.pop(0))
    return "pass" if phase == "verify" else "executed"


def update(work_dir, task_id, reply):
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "update_status.py"), task_id, work_dir, reply],
        capture_output=True, text=True)


def report(work_dir):
    status = load_status(work_dir)
    for tid, t in sorted(status["tasks"].items()):
        print("[orchestrator]   %s: %s (retries=%d)" % (tid, t["status"], t.get("retries", 0)))


def loop(work_dir, provider, dry_map):
    empty_rounds = 0
    while True:
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, "get_task.py"), work_dir],
                           capture_output=True, text=True)
        if r.returncode == 2:
            sys.stderr.write(r.stderr)
            return 2
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            return err("get_task 输出无法解析: %r" % r.stdout)

        if isinstance(out, dict):
            if out.get("result") == "[ALL TASK FINISHED]":
                print("[orchestrator] 工作流完成")
                report(work_dir)
                log_event(work_dir, event="finish", result="ok")
                return 0
            if out.get("result") == "[STUCK]":
                reason = out.get("reason", "")
                print("[orchestrator] 工作流卡住: %s" % reason)
                report(work_dir)
                log_event(work_dir, event="stuck", reason=reason)
                return 1
            return err("get_task 输出无法解析: %r" % r.stdout)

        if not isinstance(out, list) or not out:
            # 轮次制下 [] 仅当 verifying 收到非 pass/fail 回复（任务滞留瞬态）：重置后重试
            empty_rounds += 1
            if empty_rounds > MAX_EMPTY_ROUNDS:
                return err("连续 %d 轮无可派发任务" % MAX_EMPTY_ROUNDS)
            reset_transient(work_dir)
            continue
        empty_rounds = 0

        # 占坑（主线程串行）：pending→running / executed→verifying；记阶段供 dry-run 默认回复
        status = load_status(work_dir)
        for d in out:
            d["_phase"] = "verify" if status["tasks"][d["task_id"]]["status"] == "executed" else "execute"
            if update(work_dir, d["task_id"], "").returncode != 0:
                return err("占坑失败: %s" % d["task_id"])

        def agent(d):
            if dry_map is not None:
                reply = dry_reply(dry_map, d["task_id"], d["_phase"])
                return reply, reply == CRASH
            path = session_path(work_dir, d["task_id"], d["_phase"])
            with open(path, "wb") as f, subprocess.Popen(
                    provider.build_command(d["agent"], d["prompt"]),
                    cwd=work_dir, stdout=f, stderr=subprocess.PIPE) as p:
                stderr = p.stderr.read().decode("utf-8", "replace")
                rc = p.wait()
            if rc != 0:  # 失败也存档：exit/stderr 追加在尾部，供排查基础设施故障
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\nexit=%d\n%s" % (rc, stderr))
                return None, True
            with open(path, encoding="utf-8") as f:
                return provider.parse_reply(f.read()), False

        with ThreadPoolExecutor(max_workers=len(out)) as ex:
            results = list(ex.map(agent, out))
        if any(crash for _, crash in results):
            log_event(work_dir, event="crash")
            return err("agent 进程失败（基础设施故障），停机；重跑本命令可恢复")
        for d, (reply, _) in zip(out, results):
            rc = update(work_dir, d["task_id"], reply).returncode
            if rc != 0:
                # 单任务更新失败不停机：可能因 agent 越权直改 status.json 造成终态冲突等。
                # 记录后继续回收其余任务，交由下一轮调度重试/告警。
                err("状态更新失败: %s (reply=%r)，跳过并继续" % (d["task_id"], reply[:200]))


def main():
    parser = argparse.ArgumentParser(description="Workflow orchestrator")
    parser.add_argument("--yaml", required=True, help="path to the workflow definition file")
    parser.add_argument("--work-dir", required=True, help="working directory for all workflow artifacts")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default=None,
                        help="Coding Agent CLI used to execute the workflow's tasks")
    parser.add_argument("--prompt", default=None, help="development task prompt (first run only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="simulate agents from .workflow/dry_replies.json (UT only)")
    args = parser.parse_args()

    if not args.dry_run and not args.provider:
        return err("必须提供 --provider（或用 --dry-run 模拟）")
    if acquire_lock(args.work_dir) is None:
        return err("另一个 orchestrator 实例正在运行（.workflow/orchestrator.lock），拒绝双跑")
    status_path = os.path.join(args.work_dir, ".workflow", "status.json")

    if os.path.exists(status_path):
        if args.prompt:
            print("[orchestrator] 警告: 工作流已在执行中(%s 已存在)，"
                  "--prompt 已被忽略，恢复执行时不应传递 prompt" % status_path, file=sys.stderr)
        try:
            reset_transient(args.work_dir)
        except (OSError, json.JSONDecodeError, KeyError) as e:
            return err("恢复失败: %s" % e)
    else:
        if not args.prompt:
            print("[orchestrator] 错误: 工作流未初始化(%s 不存在)，"
                  "首次运行必须提供 --prompt" % status_path, file=sys.stderr)
            return 1
        print("[orchestrator] 初始化工作流: %s" % status_path)
        rc = subprocess.run([
            sys.executable, os.path.join(SCRIPTS_DIR, "init_status.py"),
            "--yaml", args.yaml, "--work-dir", args.work_dir, "--prompt", args.prompt,
        ]).returncode
        if rc != 0:
            return rc

    dry_map = None
    if args.dry_run:
        path = os.path.join(args.work_dir, ".workflow", "dry_replies.json")
        try:
            with open(path, encoding="utf-8") as f:
                dry_map = json.load(f)
        except (OSError, json.JSONDecodeError):
            dry_map = {}
    try:
        return loop(args.work_dir, PROVIDERS.get(args.provider), dry_map)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        return err("主循环异常: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
