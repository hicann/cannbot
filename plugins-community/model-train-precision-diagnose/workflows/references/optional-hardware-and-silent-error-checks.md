# 可选特征值检测与 Ascend DMI 检查

本 reference 只在 Preflight 证据提示罕见梯度异常、疑似静默硬件错误或已有外部 AICore 检查证据，且用户批准额外实验时读取。两类检查均为
辅助证据，不是 E01/E02/E04/E08 的默认步骤，也不能替代 target/golden 对照、显式 `torch.isfinite`、msProbe 首差异/首异常定位或
单变量修复复跑。

## 1. 共同前置门禁

1. 先记录检查目的、触发证据、目标 Node/Device、现场版本、预计时长/资源、停止条件和结果保存路径。
2. 运行真实可执行文件的 `--help`/版本查询，或核对现场 Ascend Extension for PyTorch 文档；文档、命令或字段不一致时以现场版本为准。
3. 新训练、环境变量变更和由本 Plugin 发起的 AICORE 诊断都由 Primary 提前审批。多节点执行还必须遵循
   [多节点诊断作业执行、产物汇集与分析门禁](cluster-execution-and-artifact-plane.md)。
4. 记录原训练的可复现契约；检测导致 OOM、性能变化、症状消失/迁移或训练提前终止时，作为 observer effect 单独处理。
5. 工具没有覆盖目标 dtype、图模式、设备或故障类型时写 `not-applicable/unsupported`；执行条件或结果无法确认时写 `unknown`，
   不能伪造通过。

## 2. 训练阶段在线特征值检测

### 适用范围

该能力用于训练过程中对梯度特征值异常进行在线检测，适合长稳训练中的梯度异常、高比特跳变或疑似静默数据错误线索。它不是
通用前向/反向 NaN/Inf 检查器，也不证明某个 Module/API/Tensor 是根因：

- 普通 E01/E02 标杆有限值 mismatch 不默认开启；
- 前向 NaN/Inf、Optimizer/Scaler 非有限值仍以显式有限性观测和 E04 dump 证据为准；
- 告警只能形成硬件/通信/梯度异常候选，需与 Node/Rank/Step、日志、重跑和硬件检查交叉验证；
- 未告警不能排除未覆盖 dtype、模式、采样间隔、阈值之外或其他类型的精度问题。

### 现场版本探测

官方不同版本存在开关和能力差异。至少记录 torch_npu/Ascend Extension for PyTorch 版本、执行模式、dtype、实际环境变量和启动日志：

- 较新版本文档使用 `NPU_ASD_CONFIG`；较旧版本可能使用 `NPU_ASD_ENABLE` 及其他阈值变量；不得同时照搬两套配置；
- dtype、checksum 联动、日志关键词、告警/终止行为、采样间隔、显存与性能开销均以现场版本文档为准；
- 现场版本不支持的图模式或 dtype 不得通过修改模型语义强行启用。

下方示例用于展示配置结构，可作为设计现场配置时的参考，不作为跨版本固定阈值。使用前必须按实际加载版本的官方文档核验字段、
阈值、单位和适用范围；调整阈值时记录原值、新值、理由和回退，并把默认阈值与人为调阈后的告警分开解释。

### 证据记录

对每次运行记录：环境变量的脱敏原值、适用 Node/Rank、Step/时间窗口、dtype/执行模式、训练返回状态、原始日志路径、告警关键词、
关联 Device、性能/显存变化和回退状态。告警发生后仍需确认同一 Node/Rank 是否出现训练症状、硬件/通信错误或 DMI 反证；
不能把一次特征值告警直接升级为 `verified root cause`。

### 使用示例：长稳训练偶发 GradNorm 跳变

已确认 256 卡任务在相同数据、权重和配置下偶发 GradNorm 跳变，跳变点的 Loss、梯度仍为 finite，普通短程复现无法稳定捕获，且
现有证据怀疑某个 Node/Rank 的梯度高比特异常。处理方式：

1. 在 `experiment_matrix.md` 把“仅启用现场版本支持的特征值检测”登记为唯一变化因素，记录目标 Node/Rank、预计运行窗口、显存/
   性能风险、停止条件和回退方法，由 Primary 取得新训练及环境变量变更批准。
2. 探测各目标 Node 的 torch_npu 版本和真实加载路径，并依据该版本官方文档确认使用 `NPU_ASD_CONFIG` 还是旧版
   `NPU_ASD_ENABLE` 配置族；将实际脱敏配置、启动日志和适用范围写入证据索引。建议参考下方示例的配置结构，但具体字段、阈值、
   单位和组合必须按现场版本官方文档核验后确定。
   ```
   export NPU_ASD_CONFIG=enable:true,with_checksum:true,cooldown:5,strikes_num:3,strikes_window:480,checksum_cooldown:180,upper_thresh1:1000000,upper_thresh2:100,grad_sample_interval:3
   ```
3. 按原复现契约运行获批窗口，保持数据、Seed、拓扑和训练参数不变；同步记录 GradNorm 跳变与特征值告警的 Node/Rank/Step/时间。
4. 若原症状复现且相同位置出现告警，只形成“硬件/通信/梯度异常强候选”，再与日志和可选 AICORE 诊断交叉验证；若原症状复现但
   未告警，记录“检测未命中”，不能写硬件通过；若启用后症状消失或迁移，标记 observer effect，不用本次数据认证原症状根因。

## 3. Ascend DMI AICORE 诊断

### Plugin 范围

本 Plugin 只把 Ascend DMI 的 **AICORE 诊断**作为可选硬件检查；不发起、不编排 AICORE 压测。官方对两者给出的使用场景不同：
AICORE 诊断用于训练/推理任务巡检或上线检查，AICORE 压测用于训练/推理任务已经出现 AICore ERROR 的场景。不得把二者混成
精度诊断中的前后步骤。

- 特征值/训练证据持续指向特定设备时，可申请独立运行 AICORE 诊断；
- 训练日志已有明确 AICore ERROR 时，如实记录 Node、Device、时间和原始错误，不由本 Plugin 转交或拉起压测；
- 外部流程已提供 AICORE 压测结果时，本 Plugin 只登记并通报。只有原始结果明确失败且来源、设备、时间和版本可核对时，才能写
  “外部流程硬件压测未通过”；只有 AICore ERROR 而没有外部压测结果时，压测状态写 `unknown/not-provided`，不得推断为失败；
- 外部压测结果是设备级旁证，不用于解释普通数据、代码、配置或软件栈 mismatch，也不能命名具体训练算子根因；
- 现场帮助、支持设备、权限、驱动/固件/ToolBox 前置条件不满足时停止，不猜测参数。

### 独占与集群执行

AICORE 诊断会影响 NPU 训练/推理，必须在目标设备没有业务作业时单独执行。Primary 审批中明确：

- 目标 Node/Device、是否已排空业务、资源归属和维护窗口；
- `ascend-dmi` 真实路径、ToolBox/驱动/固件版本、完整命令、轮数、预计时长、日志路径和停止方式；
- 多节点采用现场调度器或已验证 SSH/pssh runbook；逐 Node 保存结果，任一 Node 缺失不得汇总为集群通过；
- 不在仍运行训练的设备上“顺便诊断”，不因赶时间并发执行，也不擅自终止现场进程。

### 结果解释

保留命令返回码、完整原始输出和现场定义的状态。至少区分 `PASS`、`SKIP`、告警和 `FAIL`：

- `PASS` 只说明本次指定设备、检查项、轮数和版本范围内未发现异常，不能排除软件、数据、通信时序或未覆盖硬件故障；
- `SKIP` 不是通过，先检查权限、设备/版本支持和前置条件；
- AICORE 诊断告警或 `FAIL` 是硬件强候选，仍需核对设备身份、重复诊断和训练症状关联；
- 执行中断、日志缺失、部分 Node 未完成或状态无法解释时结论为 `unknown/inconclusive`。

Reviewer 只在上述范围、版本、原始输出和训练关联证据完整时引用结果；不得以 DMI `PASS` 覆盖已确认的训练精度异常，也不得仅凭
一次外部压测失败命名具体训练算子根因。外部压测明确失败时直接在最终报告通报“外部流程硬件压测未通过”，无需创建转交动作；
但必须把外部结果与本 Plugin 的 AICORE 诊断结果分栏记录。

### 使用示例：特定设备疑似静默硬件异常

特征值告警和训练症状多次落在 `node-17/device-5`，但训练日志没有明确 AICore ERROR。处理方式：

1. 将 AICORE 诊断登记为独立实验；Primary 审批目标设备、业务排空、维护窗口、轮数、预计时长、结果路径、停止和环境恢复方式。
2. 在 `node-17` 核对 `ascend-dmi` 真实路径、版本、`--help`、设备支持、权限以及驱动/固件/ToolBox 前置条件。仅按现场帮助形成
   完整命令；命令意图必须等价于下列骨架，不把占位符直接执行：

   ```text
   <ascend-dmi-realpath> -dg -i aicore <现场确认的 Device、轮数、结果路径及其他参数>
   ```

3. 确认训练进程已经停止后单独执行，保存返回码和完整原始输出。多节点时逐 Node 保留结果，不用部分设备的结果代表全局。
4. 按现场版本规定完成全部轮次且均为 `PASS` 时，只写“本次 AICORE 诊断未发现异常”；`SKIP`、缺轮次或结果缺失写
   `unknown/inconclusive`；告警或 `FAIL` 形成设备级硬件强候选，并与原训练的 Node/Device/时间关联，不能直接命名训练算子根因。
5. 若此时外部流程另有来源、设备、时间、版本均可核对的 AICORE 压测失败原始结果，最终报告另栏直接写“外部流程硬件压测未通过”；
   没有该结果时不得由训练日志或本次 AICORE 诊断代推压测失败。

## 官方资料

- [Ascend Extension for PyTorch：特征值检测](https://www.hiascend.com/document/detail/zh/Pytorch/latest/devguide/fwfeatures/docs/zh/framework_feature_guide_pytorch/feature_value_detection.md)
- [MindCluster ToolBox：Ascend DMI AICORE 诊断及场景说明](https://www.hiascend.com/document/detail/zh/mindcluster/latest/toolbox/toolboxug/toolboxug_0153.html)
