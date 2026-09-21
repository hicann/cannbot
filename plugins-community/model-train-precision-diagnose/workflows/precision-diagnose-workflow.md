# 模型训练精度诊断工作流

本工作流由 Plugin Primary Agent 执行。各层职责如下：本文件定义阶段、状态和完成门禁；Agent 定义角色专属判断；以下 Reference
定义操作细节，均为规范性约束：

- [Intake 与症状路由](references/intake-routing.md)
- [Preflight 清单](references/preflight-checklist.md)
- [Scope Reduction](references/scope-reduction.md)
- [记录模板](references/record-templates.md)
- [Subagent 派发模板](references/subagent-prompt-templates.md)
- [Reviewer 复核契约](references/reviewer-contract.md)
- [精度诊断工具的现场确认与结果解释](references/tool-semantics-and-version-probe.md)
- [证据与风险策略](references/evidence-and-risk-policy.md)
- [Dump 完整性、症状可代表性与分析门禁](references/dump-integrity-and-compare-gate.md)
- [多节点诊断作业执行、产物汇集与分析门禁](references/cluster-execution-and-artifact-plane.md)
- [可选特征值检测与 Ascend DMI 检查](references/optional-hardware-and-silent-error-checks.md)

## 状态机

```text
NEW
  ↓
INTAKE_PENDING ↔ WAITING_FOR_USER
  ↓
ROUTED
  ↓
PREFLIGHT_DONE
  ↓
EXECUTION_READY | HANDOFF_READY | OFFLINE_ONLY | EXECUTION_BLOCKED
  ↓  （所有分支均先完成 Scope Reducer 评估）
SCOPE_REDUCED | SCOPE_SKIPPED | SCOPE_DECLINED | 已记录阻塞原因
  ↓
DIAGNOSED | EVIDENCE_INSUFFICIENT | UNSUPPORTED
  ↓
REVIEWED
```

阶段迁移前先更新 Case 记录。Subagent 的自然语言返回不能替代落盘证据。最小算子/通信脚本未复现时，可以在同一路由下从症状诊断
回到 Scope Reducer，再返回原 Symptom Agent；不新增状态或并行症状路径。

## 阶段 0：创建 Case

1. 在被诊断项目根目录创建 `precision_diagnosis/<case-id>/`；优先使用用户提供的 case-id，否则使用时间戳。
2. 按记录模板创建六个固定文件，不覆盖既有 Case。
3. 大型产物保留原位，只在 `evidence_index.md` 登记来源、绝对路径和验证状态。

## 阶段 1：Intake

Primary 按 Intake Reference 收集症状、复现条件、拓扑、实际入口、运行上下文、标杆和集群执行条件，维护 `intake_record.md` 并只向
用户提出会影响路由或安全的最少问题。材料较多时可临时委派通用 Subagent 只读整理事实；其不得询问用户、选择 route、运行探测或
拥有 Case 状态，Primary 核验来源后才可落盘。

完成门禁：Intake Reference 的必填维度均有 `confirmed / unknown / not-applicable` 状态；会改变路由的事实不得保持未知。

## 阶段 2：Primary 症状路由

Primary 只依据已确认事实选择一个 route 并记录依据、反证和缺口：首个已确认异常是 NaN/Inf/Overflow 时优先选 E04；首发异常
不是非有限值、但受控重复运行自身不一致时选 E08；自身稳定且与外部标杆存在有限值偏差时，正向选 E01、反向选 E02。缺少
E01/E02 外部标杆时先建立标杆或以证据不足结束，超出四类症状时标记 `unsupported`。多症状选择首发症状，后续传播形成的
NaN/Inf/Overflow 或其他现象不得覆盖更早异常。

完成门禁：只选择一个 route，并有排除竞争 route 的证据。路由阶段不运行命令、症状 Skill 或实验，也不输出根因猜测。

## 阶段 3：Preflight

Primary 按 Preflight Reference 维护 `preflight_record.md`。先确认 target/golden 实际训练的 Node、进程角色和容器/虚拟环境及其已验证
进入方式，再在该上下文检查数据、代码、配置、权重和依赖；不得用宿主机、登录节点或默认 Shell 结果冒充训练环境。检查量较大时可
临时委派通用 Subagent 执行已授权只读探测，但 Primary 必须限定范围、核验证据并决定阶段完成。

特征值检测和 Ascend DMI AICORE 诊断不是默认检查。只有现有证据满足可选硬件 Reference 的触发条件时，Primary 才把它作为高风险
可选实验提交用户决定；未授权不执行，也不阻塞其余适用流程。本 Plugin 不发起或编排 AICORE 压测。

完成门禁：每类检查都有明确状态，运行依赖可追溯到相应 Node/进程的实际训练上下文。影响比较的上下文仍未知时停留在本阶段，返回
`needs_user_input` 或精确 handoff，不得标记 `PREFLIGHT_DONE`。

## 阶段 3.5：执行就绪判定

单节点按需将集群字段标为 `not-applicable`；多节点严格按集群执行 Reference 判定：

- `EXECUTION_READY`：新作业的共享存储、现场启动方式、节点范围、访问和授权条件已满足；
- `HANDOFF_READY`：条件已确认，由用户执行并回传证据；
- `OFFLINE_ONLY`：只读分析既有产物；
- `EXECUTION_BLOCKED`：关键执行条件缺失或未知。

本阶段只判执行能力，不把共享代码、调度方式或 SSH 状态写成 target/golden 精度差异。

## 阶段 4：Scope Reducer

Primary 必须派发 Scope Reducer。该 Agent 按 Scope Reduction Reference 建立 R0、评估当前 Node/Rank/Step/模型/配置范围，记录候选的
信息增益、成本、风险和取舍，并把获批实验写入 `scope_record.md` 与 `experiment_matrix.md`。不要求机械执行全部候选。

当前已是最小复现、用户拒绝或执行阻塞时，可以记录 `SCOPE_SKIPPED`、`SCOPE_DECLINED` 或阻塞原因；这些状态只跳过实验执行，不能
跳过范围评估和阶段 handoff。需要新作业时必须符合阶段 3.5 的执行模式。

完成门禁：R0、当前范围、候选取舍、执行状态和下一阶段范围均已落盘；已执行实验满足 Reference 的单变量与回退要求，未执行实验有
明确理由。否则不得进入症状诊断。

## 阶段 5：Symptom Diagnostic

只派发路由命中的一个 Agent：

| Route | Agent | Skill |
| --- | --- | --- |
| E01/E02 | `model-train-precision-numerical-mismatch-agent` | `model-train-precision-numerical-mismatch` |
| E04 | `model-train-precision-nonfinite-agent` | `model-train-precision-nonfinite` |
| E08 | `model-train-precision-determinism-agent` | `model-train-precision-determinism` |

Symptom Agent 先验证 Preflight 的单一差异；若在原复现口径下形成因果闭环，可直接进入 Reviewer。否则调用对应 Skill 执行内部定位。
所有实验先写入矩阵，需授权的动作由 Primary 确认后再派发。

工具名称、安装状态、框架接入点、结果语义和 CANN 现场契约统一按工具语义 Reference 核对。任何 dump 都必须先通过集群执行 Reference
和 Dump 联合门禁，才允许 compare、overflow_check 或进入根因证据链；不得从分析结果反推采集时原症状已复现。

最小脚本不复现只形成反证。Agent 应记录缺失的整网上下文并提出下一轮单变量假设，Primary 重新派发 Scope Reducer 后再返回同一
Symptom Agent。E08 满足其 Skill 规定的观察者效应和候选收敛条件时，可经用户批准在回环前单独选择 `mssanitizer` 或最小并发图检查；
检查结果仍须经过修复、回退和整网验证。

## 阶段 6：Reviewer

Primary 按语义症状在派发中传入唯一 `Review section`：`有限值偏差`、`非有限值`、`受控重复运行不一致` 或
`not-applicable`。前三者由 Reviewer 读取 `reviewer-contract.md`，只应用通用规则和指定章节；`not-applicable` 时不读取该契约。
Reviewer 只读复核五个输入记录和引用证据，不加载症状 Skill。再按证据与风险、集群执行、Dump 联合门禁和记录模板 Reference
生成 `final_report.md`。
引用特征值检测或 Ascend DMI 时，还必须检查触发依据、用户授权、版本与范围、原始结果、观察者效应和解释边界。

只有复现契约、因果或内部定位证据、必要反证以及同口径修复/回退验证均闭环时，才能判定 `verified root cause`；否则降级为
`strong candidate` 或 `insufficient evidence`。Reviewer 按证据支持的最高粒度报告，不强制把配置、数据、权重、环境、并行或随机性
契约根因补做到 Module/API/Tensor。

Primary 向用户交付结论、证据路径、风险和最小下一步。

## 停止条件

- 已验证根因并完成同口径修复/回退验证；
- 用户拒绝必要实验；
- 缺少标杆、资源、版本支持、共享存储、现场启动方式或复现条件，无法继续获得证据；
- 症状超出 E01/E02/E04/E08。

停止不等于成功；证据不足或范围外问题必须分别标记 `insufficient evidence` 或 `unsupported`。
