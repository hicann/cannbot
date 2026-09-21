# Preflight 清单

有标杆时，以下每项都记录 target、golden、状态和证据路径；target/golden 对照是本清单的主结构。每一侧涉及多节点时，值必须
注明适用 Node 或按 Node 展开，同侧差异另行记录，不能用共享代码目录推断运行环境一致。

## 运行上下文确认门禁

检查运行依赖前，先对 target/golden 分别确认探测命令是否运行在实际训练上下文。每个适用 Node/进程角色至少记录：

- bare metal、Docker、Conda/venv 的实际组合，容器名称/ID 与镜像证据、环境名与 prefix、挂载和工作目录；
- 项目或用户提供的既有进入/只读探测方式，以及该方式对应的 Node、容器、调度 allocation 或 worker 角色；
- 环境内 `sys.executable`、`sys.prefix`、`sys.base_prefix`、cwd、训练入口及 torch/torch_npu/msProbe 的实际导入路径；
- 启动日志、运行中进程、解析后配置或现场等价证据，证明上述指纹与发生症状的训练进程相对应。

容器、镜像或环境名称不能代替环境内指纹。只有探测结果与实际训练进程上下文匹配时，相关运行依赖才可写 `confirmed`。若当前 Agent
位于宿主机、登录节点、控制节点或默认 base 环境，且没有已验证的进入方式，则运行依赖写 `unknown`，返回 `needs_user_input` 或
handoff；不得把当前 Shell 的结果当作 target/golden。项目已有且可直接执行的只读进入方式可以使用；自行创建容器、申请 allocation、
启动 worker 或改变环境需要 Primary 先确认。`not-applicable` 只表示该层确实未使用，不能表示无法进入。

驱动、固件等明确属于 Node 宿主层的证据可以在宿主侧采集，但必须标注证据层和对应 Node；不能用它替代容器内 Python 包、CANN
用户态组件及导入路径。多节点时逐 Node 执行同一门禁，不能由控制节点一次探测代表所有计算节点。

## 数据与权重

- 数据集版本/路径/清单、样本 ID 或内容校验值、tokenizer、预处理、Label/Mask/position id/padding、sampler、shuffle、worker seed。
- 预训练/断点权重路径、校验和、加载日志、缺失/多余 key、dtype 转换、量化/压缩/有损加载。
- 参数与 buffer 状态、权重绑定关系、`train/eval` 模式；断点恢复时另核对 optimizer/scaler/scheduler 状态、global step 和 RNG 状态。

## 运行依赖

- 本节仅在对应 target/golden 运行上下文门禁为 `confirmed` 后执行；未通过时各项保持 `unknown`，不得比较出伪 mismatch。
- Python、torch、torch_npu、msProbe 的版本、真实加载路径和可用状态；msProbe 的名称映射、状态判定和不可用处理按 Plugin
  [工具语义 Reference](tool-semantics-and-version-probe.md) 执行，Preflight 不安装依赖。
- CANN Toolkit/Kernel/NNAL/驱动/固件及容器映射；只读取现场存在的版本文件和工具输出。
- 工具可用时记录 `msprobe --help`、子命令帮助和 Python API 签名；不可用时记录解释器和原始错误，停止 msProbe 工具分支。
- 多节点时逐 Node 记录上述版本、真实加载路径和关键环境变量；一侧内部不一致时保留完整分布，再判断 target/golden 是否可比较。

## 代码状态

```bash
git status --short
git diff --stat
git diff -- '*.py'
git diff --cached --stat
```

用户给出标杆 branch/commit 时才执行对应 `git diff <golden>..<target>`。重点检查 dtype、算子替换、softmax/layernorm/attention/loss、
并行与通信、converter/patch、数据预处理、CANN/驱动适配。不得读取 Git 历史来猜恢复方案。

共享工程场景还要逐 Node 记录启动 cwd、训练入口和关键配置的规范路径及 SHA-256，并用运行时导入路径确认进程确实加载共享代码；
同一路径不能替代哈希，也不能证明进程已在修改后重启。

## 模型与训练配置

- 层数、hidden size、Attention/MoE、MTP 等可选层、专家数与 top-k。
- learning rate、batch/seq length、optimizer、scheduler、loss reduction、loss scale、AMP/autocast 范围、grad accumulation、clip grad、参数更新顺序、recompute。
- TP/DP/PP/CP/EP、Rank 映射、通信算法/顺序/归约 dtype、MoE 路由和负载均衡、compile/graph 开关。
- 实际生效配置必须由启动日志、解析后的配置或运行时对象证明，不能只看默认配置文件。

## 标杆与对齐口径

- 标杆自身的代码、数据、权重、配置和环境是否属于用户认可的比较对象。
- Loss/GradNorm 等指标的公式、reduction、采样区间和阈值是否一致；标杆值为零时记录绝对误差口径。
- Step、Rank、样本身份、同名 Module/API 的调用实例是否可一一对应；无法对应时记录 `unknown`，不得强行 compare。

## 环境变量

记录影响确定性、通信、编译、同步、精度和算子选择的变量。不要把整个环境无筛选写入报告，避免泄露凭据。

## 可选硬件检查

特征值检测和 Ascend DMI AICORE 诊断不是默认步骤。只有证据提示罕见梯度异常或疑似静默硬件错误时，才读取
[可选特征值检测与 Ascend DMI 检查](optional-hardware-and-silent-error-checks.md) 选择检查项。AICORE 压测不在本
Plugin 的执行范围；外部流程提供明确失败结果时只登记并通报，不创建转交动作。工具存在、版本/帮助、
支持范围和用户批准全部确认后才能执行；记录设备、命令、时长、负载范围、原始输出、observer effect 和结果边界。
工具缺失或现场不支持写 `not-applicable`，条件/结果不明写 `unknown`，不得编造命令或把 `SKIP` 写成通过。

## 实验执行就绪条件

共享存储、调度系统或逐节点启动方式按 Plugin 的集群执行契约记录，不作为 target/golden 精度差异。多节点新作业只有共享存储、
唯一 run/attempt 路径和现场启动方式均确认后才为 `ready`；软件栈仍须逐 Node 探测。

当 `scheduler_mode=manual-ssh` 且计划由 Agent 从控制节点直接拉起多 Node 实验时，Preflight 必须先提示用户或集群管理员提前完成：

- 控制节点到全部参与 Node 的 SSH 公钥免密配置，以及按项目安全流程完成的主机身份/`known_hosts` 确认；
- 项目认可的远端用户、host 清单、跳板路径和逐节点 runbook；
- 按该 runbook 对每个参与 Node 做非交互只读连通探测，记录源控制节点、远端用户、host、退出状态和证据路径。现场允许时可使用
  `BatchMode=yes` 或等价机制确认不会等待密码，但不能把该选项当作公钥配置本身。

任一 Node 仍弹出密码/主机确认、访问失败或结果不明时，direct readiness 为 `blocked/unknown`，不得把问题留到 Scope Reducer
启动作业时再发现；可由 Primary 请求用户补齐配置，或切换到由用户执行的 `handoff`。Agent 不生成、读取、索取或分发私钥，不代用户
运行 `ssh-copy-id`、修改 `authorized_keys` 或关闭主机身份校验。使用项目调度系统且 Agent 不直接 SSH 到计算节点时，本项可为
`not-applicable`，但调度器自身的提交和访问门禁仍须确认。

## 输出

每项状态只使用 `confirmed`、`unknown` 或 `not-applicable`。已确认项另设 `Comparison` 列记录 `match`、`mismatch` 或
`not-compared`；mismatch 进入假设表，但不直接定根因。

每个 mismatch 假设同时记录可改变的单一因素、预期现象、同口径复跑方式和回退方法，供 Symptom Agent 设计因果验证实验。
