# 工作流编排器（Workflow Orchestrator）

运行 `workflow.yaml` 中定义的开发工作流：一个由任务节点组成的 DAG，每个节点由子代理执行并验证，状态全部落盘，重启后进度不丢。

## 启动运行

调用技能（`/workflow-orchestrator`）并提供四项输入。缺哪一项Agent都会向你询问，绝不擅自编造：

| 输入 | 含义 |
|---|---|
| `workflow.yaml` | 工作流定义文件的路径 |
| `work_dir` | 工作流产出物的存放目录（不存在则自动创建） |
| `provider` | 承载执行器/验证器子代理的 Coding Agent CLI |
| `prompt` | 开发任务提示词（仅首次运行需要） |

技能会先校验 YAML（所有键都是必填，没有默认值，缺键即报错），然后在 tmux 会话中后台运行 `orchestrator.py`，结束后回传 `orchestrator.log`。对已有的 `work_dir` 再次运行，会从保存的状态继续。

## 执行模型

- 每个节点分两个阶段：**执行**（由 `executor` 子代理负责，状态流转 `pending → running → executed`），然后**验证**（由 `verifier` 子代理对照 `acceptance` 检查，状态流转 `executed → verifying → pass/fail`）。
- **pass** 解锁依赖它的节点；**fail** 时若 `max_retries` 预算没用完，节点打回 `pending` 重新执行；预算耗尽后由 `on_exhaust` 裁决：`exit` 终止整个工作流，`continue` 让其他分支照常派发。
- 最多 `max_parallel` 个任务并发；依赖互不重叠的节点并行派发。
- **子图节点**（`task_type: subgraph`）只带一个 `file` 字段，指向另一个工作流 YAML；等它的依赖全部通过后，子节点会被实例化进同一个 DAG。

## 定义工作流

schema 完全显式：每个键都必填、没有默认值，缺键或键名写错都会校验失败。建议从带注释的模板 [`templates/basic_workflow.yaml`](templates/basic_workflow.yaml) 入手；下面的字段说明是依据它和实战中的 [`op-develop.yaml`](../../plugins-official/ops-registry-invoke-glacier/workflow/op-develop.yaml) 整理的。

节点是怎么变成提示词的：每次派发都会把节点字段拼装成子代理的提示词——开头是 `$WORK_DIR=<work_dir>` / `$USER_PROMPT=<prompt>` 前缀，接着是 `[id] title` 和 Goal、Acceptance、Out-of-Scope 三个块（Approach 只在执行阶段出现），最后一行是协议约定：执行器完成后原样回复 `executed`，验证器回复 `pass` 或 `fail`。写每个字段时，都要清楚它会落在提示词的哪个位置。

### 顶层键

| 键 | 类型 | 说明 |
|---|---|---|
| `workflow` | str | 工作流名称；记录在 `.workflow/log.jsonl` 的 init 事件中 |
| `max_parallel` | int ≥ 1 | 同时在跑的任务数上限；每批派发都受此限制 |
| `nodes` | list | 任务节点。执行顺序完全由 `depends_on` 的边决定，与书写顺序无关 |

### 普通节点 — `task_type: normal`

主力类型：一个任务由两个子代理接力完成（先执行器，后验证器）。

| 键 | 类型 | 说明 |
|---|---|---|
| `id` | str | 全局唯一的节点 id；是它在 `status.json` 里的主键，也是 `depends_on` 引用的对象 |
| `task_type` | str | `normal` |
| `title` | str | 一句话概述；在派发提示词中渲染为 `[id] title` |
| `goal` | list[str] | "做完"的标准——完成契约，同时发给执行器和验证器 |
| `approach` | list[str] | 建议的做法；只进执行阶段的提示词，仅供参考，执行器可以不走这条路 |
| `acceptance` | list[str] | 验证阶段的判定标准；两个阶段都会收到，好让执行器提前知道验收线。最好写成能直接跑的 shell 检查（如 `test -s report.md`） |
| `out_of_scope` | list[str] | 明确排除的工作；给两个阶段都划好边界，防止范围蔓延 |
| `depends_on` | list[str] | 必须全部达到 `pass` 才会派发本节点的上游节点 id；`[]` 表示立即可跑 |
| `executor` | str | 执行阶段的子代理名 |
| `verifier` | str | 验证阶段的子代理名 |
| `max_retries` | int ≥ 0 | 验证失败的容错次数：预算内失败就打回 `pending` 重新执行；`0` 表示一次不过直接失败 |
| `on_exhaust` | `exit` \| `continue` | 预算耗尽时：`exit` 终止整个工作流；`continue` 继续派发未受影响的节点 |

### 子图节点 — `task_type: subgraph`

动态扇出：子任务到运行时才确定。恰好四个键——没有 `executor`/`verifier`/`max_retries`：

| 键 | 类型 | 说明 |
|---|---|---|
| `id` | str | 同上 |
| `task_type` | str | `subgraph` |
| `file` | str | 子工作流 YAML（顶层只有一个 `nodes` 键），相对 `work_dir` 的路径；由上游节点生成，编写工作流时可以还不存在 |
| `depends_on` | list[str] | 同上；依赖全部通过后，子节点被实例化进同一个 DAG，像其他节点一样派发 |

典型用法（见 `op-develop.yaml`）：一个普通节点负责生成子工作流文件，子图节点依赖它——扇出多少，全看生成器产出了什么。

### 编写要点

- 用 `$WORK_DIR` / `$USER_PROMPT`，不要硬编码路径——每次派发的提示词前缀里都定义了这两个变量。
- 一个条目只写一个事实：每个条目都会原样渲染成一个 `- ` 列表项。
- 环境检查类任务用 `max_retries: 0` + `on_exhaust: exit`，让该失败的运行快速失败；确实可能需要再来一遍的任务，给 1–2 次预算。
- `acceptance` 要写得机器可判（如 `! grep -qF '{OP}' file.md`），让验证器的结论是事实，不是感觉。

## `work_dir` 里的产物

| 路径 | 内容 |
|---|---|
| `orchestrator.log` | 编排器的完整输出 + 退出状态 |
| `.workflow/status.json` | 任务表及状态——进度的唯一权威来源 |
| `.workflow/log.jsonl` | 只追加的事件日志（init、dispatch、状态变迁） |
| `.workflow/sessions/<task_id>.<phase>.<timestamp>.jsonl` | 各阶段子代理的原始对话记录 |
| `.workflow/orchestrator.lock` | 单实例锁（残留锁自动接管） |

## 黑盒规则

`scripts/orchestrator.py` 是黑盒：只能通过 `SKILL.md` 里的命令调用，只凭输出和退出码评判它。不要读它的源码，更不要改。几个状态脚本（`init_status.py`、`get_task.py`、`update_status.py`）同样是它的内部实现，规则相同。
