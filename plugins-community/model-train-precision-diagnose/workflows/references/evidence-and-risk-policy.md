# 证据与风险策略

## 证据等级

| 等级 | 要求 |
| --- | --- |
| `verified root cause` | 满足下述“单变量因果闭环”或“内部数值定位闭环”之一，并完成同口径复跑。 |
| `strong candidate` | Preflight 差异或首差异链路与症状一致，但缺单变量验证、最小复现或修复/回退复跑。 |
| `insufficient evidence` | 只有最终现象、相关性、传播节点、不完整产物、未对齐标杆或不可复现。 |

### 单变量因果闭环

Preflight 中已确认的数据、权重、代码、配置、环境、并行或随机性契约差异先作为假设。只改变该因素完成对齐、修复或回退后，
症状在原复现口径下消失；实验可重复且其他条件保持不变，即可认证对应粒度的根因，不强制继续 dump 或定位 Module/API/Tensor。
若一次同时改变多个因素，只能保留为候选。

### 内部数值定位闭环

当 Preflight 没有可闭环差异，或证据指向算子、通信或 Tensor 内部行为时，定位首差异/首异常，证明候选输入与输出关系，
通过最小复现或修复/回退复跑验证。是否需要真实 tensor dump 由最小复现的输入需求决定。

Preflight 差异本身、工具 advisor、traceback、首红行、最终 Loss 或一次偶然不复现都不能单独认证根因。

## Dump 完整性与症状可代表性

多节点证据先执行 [多节点诊断作业执行、产物汇集与分析门禁](cluster-execution-and-artifact-plane.md)。只有执行证据完整、产物来自单一
run/attempt 且 `collection_state=complete`，才能进入 dump 完整性检查。

任何 dump、compare 或 overflow_check 证据都必须先通过
[Dump 完整性、症状可代表性与分析门禁](dump-integrity-and-compare-gate.md)。文件完整性使用 `dump_integrity`，插桩运行是否仍代表
原症状使用独立的 `symptom_reproduction`；只有 `valid + reproduced` 才能进入分析。`incomplete`、`unknown` 或
`not-reproduced` 产物不得用来声明“未发现异常”或认证原症状根因。分析执行后还须单独记录
`analysis_integrity=valid / incomplete / unknown`；不完整分析结果同样不得进入根因证据链。

## 执行授权

只读源码、配置、日志、版本和既有产物属于低风险。以下必须由 Primary 说明命令、资源、修改、回退和停止条件后获取用户批准：

- 新训练作业、Ascend DMI AICORE 诊断或扩大集群；本 Plugin 不发起或编排 AICORE 压测；
- 修改源码、启动脚本、模型/并行配置；
- detect_anomaly、msProbe 和显式 `.item()`/同步检查插桩；
- 大规模 statistics/tensor dump；
- 共享存储跨节点写入探测，以及通过调度系统、SSH 或 pssh 提交、取消、重试作业；
- 覆盖、删除或移动用户产物。

Subagent 不向用户索取授权，只返回 `approval_required` 和明确实验描述。

多节点新实验还必须满足共享存储与现场启动方式门禁。只使用项目已有调度器或逐节点 runbook；不得生成未经现场确认的通用
launcher、SSH/pssh、节点、凭据、host 清单或 rendezvous 参数。重试不继承原批准，除非原审批明确包含重试次数、范围和停止条件。

## 改动保护

- 先记录 `git status --short`、`git diff` 和 `git diff --cached`，不得假定工作区干净。
- 调试改动优先使用可关闭开关或独立小补丁，不覆盖用户修改。
- 禁止 `git reset --hard`、`git checkout --` 或删除非本流程创建的文件。
- 每个实验记录回退状态；结束时未回退的内容必须在最终报告显式列出。

## 观察者效应

detect_anomaly、dump hook、`ASCEND_LAUNCH_BLOCKING=1`、显式同步、缩小模型或关闭 compile 都可能改变时序和症状。
症状消失、Step 迁移或性能显著变化时标记 observer effect，不能直接视为修复。文件即使完整，只要原症状在声明的可比窗口未复现，
就必须标记 `symptom_reproduction=not-reproduced` 并阻断 compare/overflow_check；窗口或等价性无法确认时标记 `unknown`。
回退 instrumentation 后复核 R0：R0 恢复复现才支持“instrumentation 影响症状”的跳变边界，R0 也不复现则只能说明复现条件已漂移。
