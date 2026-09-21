# Intake 与症状路由

## Intake 必填项

| 类别 | 内容 |
| --- | --- |
| 目标 | 用户期望、验收口径、允许的时间/资源范围 |
| 拓扑 | Node、每 Node 卡数、world size、Rank 映射、TP/DP/PP/CP/EP |
| 启动 | 实际训练脚本/模块、完整拉起命令、工作目录、launcher |
| 运行上下文 | target/golden 各自的 Node/进程角色、bare metal/docker/conda/venv 组合、容器身份/镜像、环境名或 prefix、挂载、设备型号 |
| 上下文进入方式 | 用户或项目已有的容器/环境进入或只读探测命令、调度/worker 执行方式及其证据；当前 Shell 是否已经处于训练环境 |
| 共享执行面 | 多节点共享存储、共享工程/配置根、共享 dump 根、容量/inode/权限/保留策略、分析节点可见性 |
| 集群控制面 | `execution_mode`、调度系统及项目已有提交/查询/日志/取消方式；无调度时的节点清单、SSH/pssh/run-script 手册和启动协调方式 |
| 症状 | Loss/Logits/激活/梯度/GradNorm/参数/Optimizer/Scaler，有限性和首发阶段 |
| 复现 | 每次是否出现、首次 Step 是否固定、成功/失败运行次数 |
| 标杆 | 对象、平台、代码、权重、数据、配置及可比较性；E08 可用自身重复运行 |
| 产物 | 日志、dump、配置、可用存储空间和保留策略 |

未知项写 `unknown`。Primary 负责形成最少追问、询问用户并维护 `intake_record.md`。材料较多时可临时委派当前运行时可用的通用
Subagent 按 Intake 表只读整理事实草稿；该 Subagent 不向用户提问、不选择症状 route、不运行探测或实验，Primary 核对来源后才可落盘。

容器名、镜像名、Conda 环境名或配置声明只能标识候选环境，不能证明当前 Shell 或探测进程已经处于训练运行上下文。Intake 只登记
用户提供或项目已有的进入/探测方式，不自行试运行；进入方式未知时明确返回给 Primary，并提示该缺口会阻断 Preflight 对运行依赖的
`confirmed` 结论。

多节点新实验缺少共享存储时，记录 `execution_readiness=blocked`；已有产物可记录 `execution_mode=offline` 继续只读分析。
共享存储不能证明各 Node 的 torch、torch_npu、CANN、msProbe 或实际加载路径一致，相关事实留给 Preflight 逐 Node 探测。

## 路由决策

```text
首个已确认异常是 NaN/Inf/Overflow？ ──是──> E04
        │否
受控重复运行自身不一致？ ──是──> E08
        │否
与外部标杆存在有限值差异？
        ├─ 首差异在正向 ──> E01
        ├─ 正向对齐、首差异在反向 ──> E02
        └─ 外部标杆未确认/阶段不明 ──> 不路由 E01/E02；建标杆或 insufficient evidence
```

多症状按最早产生者路由。下游传播形成的 NaN/Inf/Overflow 不能覆盖更早已确认的有限值偏差或受控重复运行不一致；只有首个已确认
异常是非有限值时才优先处理 E04。两次运行中任一次在可比窗口内首发非有限值时，先处理 E04，不能用该不完整运行做 E08 compare。

E04 不要求外部标杆；E08 的两次受控运行天然互为标杆。E01/E02 只有在外部标杆及可比较性已确认后才能路由。

参数更新已明确异常但不属于反向信号、Checkpoint 续训轨迹不齐、长期收敛质量差且无对照等，标记 `unsupported`。
