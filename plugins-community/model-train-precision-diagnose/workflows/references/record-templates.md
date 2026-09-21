# Case 记录模板

默认目录：`precision_diagnosis/<case-id>/`。每个事实必须带状态：`confirmed`、`unknown` 或 `not-applicable`。

## intake_record.md

```markdown
# Intake Record
- Case ID:
- Status:
- Project root:
- User goal / acceptance:
- Topology / rank map:
- Effective entry / command / cwd:
- Runtime context per target/golden (Node / process role / bare metal / container / Conda or venv):
- Runtime-context entry or read-only probe method:
- Runtime-context evidence / missing access:
- Shared storage / visibility evidence:
- Shared project/config root / shared dump root:
- Capacity / inode / permissions / retention:
- Execution mode: direct | handoff | offline
- Scheduler mode: managed | manual-ssh | unknown | not-applicable
- Scheduler commands or node runbook:
- Execution readiness: ready | blocked | unknown | not-applicable
- Symptom / first manifestation:
- Reproducibility / first-step distribution:
- Golden object / comparability:
- Available artifacts:
- Missing information:
- Routed symptom: E01 | E02 | E04 | E08 | unsupported | pending
```

## preflight_record.md

先建立“运行上下文确认门禁”表：

```markdown
| Side | Node / Process role | Container / Image | Conda or venv / Prefix | Entry or probe method | sys.executable / Prefix / cwd | Key import paths | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

每类使用表格：`Item | Target | Golden | Status | Comparison | Evidence | Hypothesis`。Status 只取
`confirmed / unknown / not-applicable`；Comparison 只取 `match / mismatch / not-compared`。覆盖数据、依赖、代码、模型、训练配置、环境变量、权重和可选硬件检查。
多节点值注明适用 Node 或附逐 Node 清单；同侧版本/路径差异与 target/golden Comparison 分开描述。另设“实验执行就绪条件”小节，
记录共享存储、共享代码/配置哈希、调度或逐节点启动方式和 readiness，不把它们伪装成标杆差异。

`manual-ssh` direct 另设非交互访问表；使用调度系统或不由 Agent 直接 SSH 时注明 `not-applicable`：

```markdown
| Source / Control Node | Remote user | Host-list evidence | Public-key / Host-identity readiness | Non-interactive probe | Per-host result | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
```

只记录认证方式和探测证据，不记录私钥、密码或其他凭据内容。任一计划 Node 未确认时不得把 manual-ssh direct 标记为 `ready`。

运行依赖只有在对应上下文行已为 `confirmed` 时才可写 `confirmed`；宿主机或控制节点证据单独标记证据层，不能填入容器/worker 的
Target 或 Golden 值。上下文无法进入时记录 `unknown`、缺失的进入方式和最小 handoff，不得产生伪 mismatch 假设。

## scope_record.md

本记录不可省略。记录 R0 与复现契约、当前 Node/Rank/Step/模型/配置范围、最近可复现边界、首次不复现边界、候选实验的信息增益/
成本/风险和采用或拒绝理由、被拒绝/不可用实验及最终保留配置。若不执行候选，记录 `SCOPE_SKIPPED`、`SCOPE_DECLINED` 或阻塞原因；
这些状态只表示实验执行未发生，不表示跳过 Scope Reducer 阶段。

## experiment_matrix.md

```markdown
| Run ID / Attempt | Hypothesis | Single changed factor | Execution mode | Scheduler / Job / Handoff | Command | Node/Rank/Step window | Shared artifact root | Collection state | Result | Artifact integrity | Symptom reproduction | Reproduction evidence | Artifact | Observer effect | Revert status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

## evidence_index.md

```markdown
| Evidence ID | Kind | Run / Attempt | Producer Node/Rank/PID | Absolute artifact path | Producer command | Time | Collection state | Artifact integrity | Integrity evidence | Symptom reproduction | Reproduction evidence | Scope | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

`Artifact integrity` 对 dump 记录 `dump_integrity`，对 compare/overflow_check 结果记录 `analysis_integrity`，状态只取
`valid / incomplete / unknown`，尚未产生对应产物时可写 `not-applicable`；`Symptom reproduction` 只取
`reproduced / not-reproduced / unknown`。Dump 和分析产物的 `Integrity evidence` 至少记录预期/实际
Step 与 Producer、文件数/总字节数、JSON 解析结果、错误日志、关键哈希和结构差异。敏感路径或命令参数可脱敏，但不能删除
影响复现的语义。`Reproduction evidence` 记录采集前声明的症状信号、可比窗口、等价判据及独立日志/检查证据；E01/E02 和 E08
按比较对记录，不要求 golden 或单次 run 各自“有症状”。大型 dump 不复制，仅索引。

多节点证据的 `Collection state` 只取 `not-started / pending / complete / incomplete / unknown / not-applicable`。只有同一
run/attempt 的预期 Node × global Rank 生产者均已停止写入且可追溯时才能为 `complete`；不得跨 attempt 拼接缺失 Rank。
主动作业记录共享路径；offline 复制产物同时记录原始生产路径、当前路径、交接方式和关键哈希。

## final_report.md

```markdown
# Precision Diagnosis Report
## Conclusion and confidence
## Symptom and reproduction contract
## Preflight findings
先报告 target/golden 的运行上下文门禁、进入/探测方式和证据；明确宿主机/控制节点证据是否仅代表 host layer。
## Scope-reduction boundary
## Experiment matrix reviewed
## Cluster execution and artifact collection
记录 execution/scheduler mode、Job 或 handoff 证据、共享工程与 dump 根、run/attempt、逐 Node 运行环境分布和 collection state；
明确共享代码/配置不等于运行环境一致。
## Root-cause location / first divergence
按证据填写配置、数据、权重、环境、并行、随机性契约、Node/Rank/Step 或 Module/API/Tensor；不适用字段写 `not-applicable` 并说明原因。
## Training-level acceptance
记录 Loss/Global GradNorm 的对齐 Step、有效样本数、绝对相对误差口径及阈值结果；不适用时说明原因。
## Node-level analysis
记录普通 compare 的 Result/Err_message 或 compare -da/overflow_check 的现场产物、规则和首差异/首异常；不得代替训练级验收。
## Dump and analysis integrity, and symptom representativeness
多节点先复核执行证据、单一 run/attempt 和 `collection_state=complete`，再分别复核引用产物的 `dump_integrity`、分析集合的
`symptom_reproduction`、分析结果的 `analysis_integrity` 及各自证据；只有执行/汇集门禁通过且 `valid + reproduced` 可启动分析，
只有分析产物也为 `valid` 才可进入原症状根因证据链。
## Root-cause evidence and counter-evidence
## Fix or rollback verification
## Observer effects
## Unresolved gaps and minimum next action
## Remaining debug changes / artifacts
```
