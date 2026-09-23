# 多节点诊断作业执行、产物汇集与分析门禁

本规范适用于需要新启动作业的多节点 Preflight 验证、Scope Reducer 实验和三类症状采集。它说明如何使用现场已有调度器、
SSH/pssh/run-script 或用户代执行方式安全启动诊断作业，如何统一代码/配置来源，并将各 Node/global Rank 的日志与 dump 归集到
唯一 run/attempt 的共享存储或可核验离线交接路径；同时定义进入 compare/overflow_check 前的执行、汇集和完整性门禁。它不替代
target/golden Preflight 对照、症状专属分析或用户审批。

## 1. 四类状态

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `execution_mode` | `direct / handoff / offline` | Agent 直接使用已验证的现场能力、用户按清单代执行，或只分析既有产物。 |
| `scheduler_mode` | `managed / manual-ssh / unknown / not-applicable` | 使用项目既有调度系统、使用项目既有逐节点 SSH/pssh/run-script 流程，或尚未确认。 |
| `execution_readiness` | `ready / blocked / unknown / not-applicable` | 新作业的共享存储、启动方式、节点范围和授权条件是否满足。 |
| `collection_state` | `not-started / pending / complete / incomplete / unknown / not-applicable` | 本 attempt 的预期 Node/Rank 产物是否已经停止写入并全部汇集。 |

单节点作业的共享存储和 `scheduler_mode` 可为 `not-applicable`。`offline` 只允许读取既有产物，不授权创建训练、插桩或补采作业；
产物已从原集群复制到分析节点时，记录原始生产路径、当前绝对路径、复制/交接方式、关键哈希和 Node/Rank 来源。

## 2. Intake 必须确认的集群事实

由 Primary 向用户统一确认，Subagent 不直接追问：

- 所有参与 Node、分析节点及其 Node/Rank 映射；
- 所有参与 Node 和分析节点均可访问的共享存储绝对路径；
- 实际训练是否从共享工程目录加载，实际配置是否也来自共享目录；
- 可用于本 Case 的共享 dump 根目录、容量、inode、写权限和保留策略；
- 是否存在集群调度/任务管理系统；存在时记录项目已有的提交、查询、日志和取消方式；
- 不存在调度系统时，记录项目已有的节点清单、SSH/pssh/run-script 操作手册、启动协调方式和 rendezvous 信息来源；
- 若计划从控制节点批量执行，确认现场是否已有 `pssh`、它的真实路径/版本/帮助，以及项目认可的 host 清单；
- 若计划由 Agent 通过 `manual-ssh` direct 拉起，提示用户或集群管理员提前配置控制节点到全部参与 Node 的 SSH 公钥免密和主机身份
  信任，并记录逐 Node 非交互连通证据；
- Agent 是否具备已验证的直接访问能力；否则使用 `handoff`，由用户执行命令并返回证据。

存在已验证的现场启动方式和直接访问能力时，默认使用 `direct`。`handoff` 只用于用户明确要求代执行，或 Agent 的直接执行能力
不可用、阻塞、未知或在执行前失效；不能仅因作业耗时、多节点或操作复杂而选择 `handoff`。

未知事实写 `unknown`。不得推测 SSH 用户、密钥、节点地址、启动顺序、环境初始化命令或 rendezvous 参数。

## 3. 共享存储与共享工程门禁

多节点新实验必须确认所有参与 Node 能向共享 dump 根写入，分析节点能读取该根并向独立分析输出目录写入；否则
`execution_readiness=blocked`。已有产物仍可采用 `execution_mode=offline` 分析，但不能据此发起补采。

共享工程目录用于提供同一份代码和配置，不能证明进程实际加载内容一致。每次获批运行前，按 Node 记录：

- 启动工作目录、训练入口与关键配置的 `realpath` 或现场等价规范路径；
- 训练入口、启动脚本和关键配置文件的 SHA-256；
- 运行时实际导入文件路径；Python 模块优先使用 `inspect.getsourcefile`；
- 进程是否在相关修改之后重新拉起。

同一路径但哈希不同、路径落入本地覆盖目录、容器挂载不一致或进程未重启时，代码/配置一致性为 `unknown` 或已确认不一致，
不能进入本次实验。共享存储也不能证明 Python、torch、torch_npu、CANN、msProbe、驱动、固件、环境变量和包加载路径一致；
这些仍由 Preflight 在 target/golden 各 Node 的实际训练容器/Conda/worker 上下文中探测，并分别汇总。登录节点、控制节点或宿主机
探测只代表其明确证据层，不能替代计算进程上下文；上下文进入方式未确认时对应运行依赖保持 `unknown`。

共享存储事实可由现场已有挂载证据确认；需要新建探测文件验证跨节点读写时，把确切路径、Node 范围和清理方式纳入 Primary 的审批。

## 4. Run 与 attempt 隔离

每次实验使用唯一目录：

```text
<shared-root>/precision_diagnosis/<case-id>/runs/<run-id>/attempt-<n>/
├── manifests/
└── dump/
```

将 `dump/` 作为现场版本支持的 `dump_data_dir` 或等价配置值。内部 Step/Rank 结构由现场 msProbe 创建，不能预设固定层级或手工
伪造目录。`manifests/` 索引每个生产者的 Node、global Rank、local Rank、PID、命令/配置哈希、开始/结束时间、退出状态和产物路径。

重试必须增加 `attempt-<n>`，不得继续写入、复制覆盖或分析前一 attempt 的 dump。任何分析集合只能引用同一 run、同一 attempt；
跨 attempt 拼接缺失 Rank 时，`collection_state=incomplete`。

## 5. 调度系统与逐节点启动

### managed

只复用项目现场已有 launcher 和命令，不生成通用 Slurm、Kubernetes、torchrun 或厂商调度器模板。记录提交命令、Job ID、
allocation/Node 范围、attempt、查询证据、日志位置、取消方式和终止状态。命令缺失或语义未经现场证据确认时保持 `unknown`。

### manual-ssh

没有调度系统时，只按项目已有 SSH/pssh/run-script 操作手册在所有参与 Node 启动对应进程。`direct` 要求 Agent 已验证能访问目标节点，
且 Primary 已批准完整命令批次；否则生成逐节点 `handoff` 清单，至少包含 Node、工作目录、环境初始化、原样命令、global/local Rank、
共享输出目录、启动顺序/协调依据、日志路径、成功/失败回传项和停止方式。

`direct` 的 Preflight 硬门禁是用户或集群管理员已提前完成控制节点到全部参与 Node 的公钥免密和主机身份确认。Agent 只使用项目提供的
远端用户、host 清单、跳板路径和 runbook 做逐 Node 非交互只读探测；现场允许时可用 `BatchMode=yes` 或等价方式确认不会等待密码，
但不能把命令选项误写成已完成密钥配置。任一 Node 仍提示密码/主机确认、连接失败或结果不明时，`execution_readiness=blocked/unknown`，
不得在启动实验时临时补配或交互输入。Agent 不生成、读取、索取或分发私钥，不运行 `ssh-copy-id`、修改 `authorized_keys`，也不关闭
主机身份校验。由用户执行的 `handoff` 需明确注明 Agent 未获得 direct 访问能力。

现场已经安装并允许使用 `pssh` 时，可由一个控制节点批量拉起各参与 Node，仍归类为 `manual-ssh`，不视为调度系统。执行前先
记录控制节点，并通过真实可执行文件、`--version` 和 `--help` 探测现场命令语义；命令名、参数或输出格式与预期不一致时保持
`unknown`。host 清单必须来自项目/用户，记录绝对路径、内容摘要和 SHA-256；批量命令只调用项目已确认的逐节点 run script，
不由 Plugin 推导训练 launcher 或 rendezvous 参数。

`pssh` 执行必须保存每个 host 的退出状态、stdout/stderr、超时和未启动节点，不能只使用控制节点的聚合返回码。任一参与 Node
启动失败、状态不明或没有回传时，本次执行证据不完整，`collection_state` 不得为 `complete`；重试仍需用户授权并使用新 attempt。
`pssh` 只提供 SSH fan-out，不替代共享存储、全局 Rank 汇集、作业生命周期判定或症状证据门禁。

不得把“通常每个节点运行脚本”扩写成某个框架的固定启动方式。没有现场 runbook、启动参数来源或可核验的 pssh host 清单时，
`execution_readiness=unknown`，不得试错式 SSH 拉起。

## 6. 执行、汇集与分析门禁

Primary 在新作业前向用户展示确切命令、节点/Rank、资源、唯一变化因素、共享输出目录、预估容量、回退和停止条件。获批范围不能
自动扩展到重试、更多节点、更长 Step 或更大 dump；未包含的动作重新审批。

用户批准后，若 `execution_mode=direct` 且 `execution_readiness=ready`，收到授权范围的 Agent 必须使用已验证的现场 launcher 或
SSH/pssh/run-script 自行提交或拉起该 attempt，并记录原始命令、Job ID 或逐 Node 进程证据；不得把同一命令再次交给用户手动执行。
启动前发现直接能力失效时停止执行，将 readiness 标为 `blocked/unknown` 并返回证据，不得编造参数或静默切换为 `handoff`。

作业进入终态且所有生产进程停止写入后才能汇总。`succeeded / failed / cancelled / preempted` 分开记录；症状导致的预期失败与
基础设施失败也分开。只要仍有写入者、Job 状态不明或 Node 回传未齐，`collection_state=pending/unknown`。

`collection_state=complete` 至少要求：

- 预期 Node × global Rank 生产者清单全部到齐，Node/Rank/PID 身份可追溯；
- 没有缺失、重复或冲突 global Rank，没有跨 attempt 文件；
- 每个生产者的退出状态、日志和产物根已记录，所有写入已静止；
- 主动新作业的分析节点能读取同一共享 attempt 根；`offline` 产物则需有可核验的原始生产路径、当前路径和交接证据。

缺 Node/Rank、Rank 冲突、来源不明、作业仍写入或重试污染时为 `incomplete`，停止后续分析。完成汇集后还必须执行
[Dump 完整性、症状可代表性与分析门禁](dump-integrity-and-compare-gate.md)；联合门禁为：

```text
execution evidence complete
+ collection_state=complete
+ dump_integrity=valid
+ symptom_reproduction=reproduced
```

全部满足后才能运行 compare/overflow_check。`msprobe merge_result` 仅是 E01/E02 对完整普通 compare XLSX 的可选派生视图，
不负责跨节点搬运、Rank 汇集或完整性认证。

## 7. Reviewer 检查

Reviewer 只读核对 execution mode、scheduler/job 或 handoff 回传、run/attempt、主动作业的共享路径或 offline 产物交接证据、
生产者矩阵和 `collection_state`。
共享工程只能支持代码/配置一致性证据，不能替代逐 Node 软件栈探测。跨 attempt、缺 Rank、来源不明、主动作业共享路径未经确认、
offline 交接链缺失或 `collection_state` 非 `complete` 的产物不得进入 compare/overflow_check 或根因证据链。
