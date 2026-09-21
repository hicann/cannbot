# Reviewer Contract

本契约用于训练精度诊断的独立复核。Reviewer 只判定已有证据，不执行训练、compare、overflow_check、dump、mssanitizer 或补充实验。

## 使用方式

Primary 在派发中指定唯一 `Review section`：`有限值偏差`、`非有限值`、`受控重复运行不一致` 或 `not-applicable`。Reviewer 只应用
通用规则和指定症状章节，不得引用其他症状章节补充或改变结论；`not-applicable` 时不读取本契约的症状章节。

## 通用复核规则

- Preflight 差异只有在原复现契约下完成单变量修正、同口径复跑和回退复现，才能按对应粒度认证；一次改变多个因素最多为
  `strong candidate`。
- 内部候选必须有输入输出关系、必要反证和修复/回退验证。工具告警、首差异、传播节点、最终现象或不完整产物不能单独认证根因。
- CPU 对照和最小脚本只按实际覆盖范围解释；CPU 上症状消失或最小脚本不复现，不能排除 NPU 整网并发、通信、内存或上下文依赖。
- 只有路由、复现契约、因果或内部定位、必要反证及同口径修复/回退全部闭环时才判 `verified root cause`；否则降为
  `strong candidate` 或 `insufficient evidence`。

## 有限值偏差

### 路由与训练级验收

- 确认存在可比的外部标杆，target 自身受控重复稳定，且首发异常为有限值偏差。任一条为 `unknown` 时不得认证根因。
- 正向 Logits、激活或 Loss 首先偏差时复核正向路径；正向仍在口径内、梯度或 GradNorm 首先偏差时复核反向路径。阶段证据不足时保留 `unknown`。
- 优先使用用户或项目口径；未提供时，默认首个 Loss 相对误差 `< 0.5%`、`mean(abs(loss rel error)) < 1%`、
  `mean(abs(grad_norm rel error)) <= 10%`。标杆为零时必须使用明确的绝对误差口径。
- 只计入已对齐的有效 Step；缺失、NaN 或未对齐值不得记为零。报告公式、有效样本数和阈值结果。
- 训练级验收与节点级 compare/首差异分开。`Result`、`is_same` 或 `diff_analyze` 不得替代 Loss/GradNorm 验收。

### 根因证据

- 内部定位必须对齐 Step、Rank、样本和调用实例。问题 API 的输入已偏时，当前 API 不是误差引入点；只能报告最后一致节点到首问题节点的可疑区间。
- 首个可观测差异、有限放大起点和后续放大器必须分开。compare 红项、单 Rank 差异或时序先后只是定位证据，不自动等于根因。
- targeted tensor 只能按实际采集范围解释，不能替代 NPU 正式修复/回退验证。

## 非有限值

### 路由与首发边界

- 确认训练中已出现 NaN、`+Inf`、`-Inf` 或明确 Overflow；该类症状不要求外部标杆。只有有限值偏差时路由不成立。
- 复核首发 Node/Rank/Step 和首次观测边界，不把后续 Loss NaN 当作起源。
- `logits` 首先非有限属 forward；`logits` 有限而反向/梯度首先非有限属 backward；前两者有限而参数、Optimizer/Scaler 状态或更新后权重首先异常属 optimizer-scaler。覆盖不足时保留 `unknown`。

### 工具与定位证据

- `detect_anomaly(check_nan=True)` 只能为失败的反向函数提供前向 traceback，并检查反向生成的 NaN；不证明完整覆盖前向 NaN 或任意阶段 Inf。
- overflow_check 只有在 `dump_integrity=valid` 且 `symptom_reproduction=reproduced` 时才能进入原症状证据链。无
  `anomaly_analyze_*.json` 不自动等于无异常，compare/diff 产物不是 overflow_check 证据。
- 区分更早的有限放大起点、首个“有限输入产生非有限输出”转换点和后续传播节点。三者都不能仅凭位置先后认证根因。
- 输入已非有限时继续追溯生产者。搬运、复制、初始化/占位、通信野值或 inplace 节点只能按实际写入者和消费者证据解释。
- 合法 `-Inf` 必须有 mask、位置和消费者语义证据，且不豁免下游首次 NaN。过滤规则命中不等于根因已定。
- 修复复跑必须确认非有限值消失且未迁移到其他 Node/Rank/Step。

## 受控重复运行不一致

### 路由与复现契约

- 确认 run A/run B 的数据集及顺序、输入、权重/初始状态、训练参数、环境和并行拓扑可比，且在相同 Step、Rank、样本和调用实例下仍不一致。
- 随机性契约应覆盖 Python/NumPy/PyTorch/NPU Seed、Rank 派生、sampler/worker、shuffle、Dropout/随机 API、模型与
  optimizer/scaler 初态、计算/通信确定性、编译模式和并行拓扑。“固定一个 Seed”不是完整证明。
- 任一运行在可比窗口内先出现 NaN/Inf/Overflow 时，本路由不成立，不得用该运行做确定性 compare。
- 每次都不一致但首差异 Step 不固定仍可记为稳定复现，但必须报告 Step 分布和对齐方式。

### 根因与内部定位证据

- 只改变一个已确认因素后多组 A/B 都恢复一致，并经回退再现，才能按随机性契约、配置、环境或并行粒度认证。一次补齐多个控制项只证明相关性。
- 校验值差异只证明不相等，不表示误差幅度。PyTorch `summary_mode: "md5"` 的现场语义必须核对；已确认为 CRC-32 时不得称为密码学 MD5。
- 首个可观测不相等边界不自动等于起源。只有输入、参数、状态、调用和通信参与者均对齐而输出首次不同时，当前节点才是非确定行为引入候选。
- 首问题 API 的输入已不同时，不得将其定为根因；报告最后一致节点到首问题节点的可疑区间。边界之后的差异扩大属传播或影响。
- racecheck 告警或最小并发图复现只形成竞争候选，必须经修复/回退和整网 R0 验证。全量 Dump 使症状消失时必须记录观察者效应。
- 认证 `verified root cause` 还必须具备完整随机性契约、受控 A/B 复现及多组修复/回退闭环。
