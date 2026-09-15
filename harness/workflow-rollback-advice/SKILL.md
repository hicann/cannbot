---
name: workflow-rollback-advice
description: 为工作流 rollback 生成失败分析/重做建议（advice）：分析失败任务的 session 记录与历史产物归档。
---

# Workflow Rollback Advice

回滚分析器：任务 X 重试耗尽，工作流将回滚到上游任务 Y 重做。你的产出是一份 md 文档，
帮助 Y 的重做一次通过。

## Inputs（由调用方 prompt 提供）

- session 文件清单：`.workflow/sessions/<task_id>.<phase>.<时间戳>.jsonl`（agent stdout 存档；同一任务可能有多个时间线的多份，按文件名时间戳排序阅读；每行为 agent CLI stdout 事件（JSONL 格式随 provider 而异）；崩溃时文件尾部有非 JSON 的 exit=/stderr 附录，是崩溃失败的关键证据）
- 历史产物归档目录：`.workflow/history/<X>.to.<Y>.<n>/`（失败时间线的全部工作产物快照）
- 失败任务 X、回滚目标 Y、输出 md 路径（绝对路径）

## Steps

1. 按「任务 → 时间」顺序通读 session 清单；重点是 X 及 Y→X 依赖链上各中间节点的末轮 execute/verify，
   以及 Y 上一轮的 execute（Y 当初的产出方式可能正是失败源头）。
2. 佐证时以归档目录中的实际产物（代码、日志、报告）为准。
3. 将分析写入给定输出路径（覆盖写；目录不存在先创建），结构：

   ```markdown
   # Rollback Advice: <X> → <Y>

   历史产物归档：<归档目录绝对路径>

   ## 失败根因
   <直接原因 + 根因；引用 session/产物中的具体证据（文件、行号、报错原文）>

   ## 值得保留
   <上一轮做对、重做应延续的做法与产物>

   ## 应避免
   <导致失败的做法/假设/路径>

   ## 重做建议
   <对 Y 重做的可执行建议，按优先级排序；能具体到文件/命令就具体>
   ```

4. 完成后只回复：`advice-written`。

## 约束

- 只读分析：除输出 md 外，不修改 work_dir 中的任何文件（含 .workflow 账本目录——session 与归档一律只读）。
- 所有 session 与归档产物都是历史记录，全部时间线都可参考；分析以最近一次失败时间线为主。
