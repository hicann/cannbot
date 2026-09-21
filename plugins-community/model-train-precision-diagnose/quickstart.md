# 模型训练精度诊断快速入门

`model-train-precision-diagnose` 用于定位 PyTorch on Ascend NPU 训练中的有限值偏差、NaN/Inf/Overflow 和受控重复运行不一致。它先确认复现条件与运行环境，再缩小问题范围、定位首个差异或异常，并由 Reviewer 复核证据闭环。

## 一、适用场景

| 症状 | 诊断入口 | 是否依赖外部标杆 |
| --- | --- | --- |
| 正向 Loss、Logits 或激活出现有限值偏差 | E01 | 是 |
| 正向基本一致，反向梯度或 GradNorm 出现有限值偏差 | E02 | 是 |
| 前向、反向、Optimizer 或 Scaler 出现 NaN、Inf 或 Overflow | E04 | 否 |
| 固定输入、权重、Seed 和确定性设置后，两次运行仍不一致 | E08 | 否，两次运行互为对照 |

不适用于推理精度、OOM、性能优化、非 PyTorch 训练或 Checkpoint 续训轨迹对齐。

## 二、安装

准备 Node.js、所使用的 Agent 客户端，以及可进入实际训练环境的目标项目。可通过 npm 包安装：

```bash
npx @cannbot-plugin/cannbot@latest install model-train-precision-diagnose \
  --tool opencode --target /path/to/training-project
```

也可从源码安装；此时还需要 Git，并且克隆 cannbot 时必须初始化 Skill submodule：

```bash
git clone --recurse-submodules --shallow-submodules https://gitcode.com/cann/cannbot.git
cd cannbot/plugins-community/model-train-precision-diagnose
bash init.sh project opencode /path/to/training-project
```

将 `opencode` 替换为实际使用的客户端：

| 客户端 | 安装参数 | Skills 目录 | Agents 目录 |
| --- | --- | --- | --- |
| OpenCode | `opencode` | `.agents/skills/` | `.opencode/agents/` |
| Codex | `codex` | `.agents/skills/` | `.codex/agents/` |
| Claude Code | `claude` | `.claude/skills/` | `.claude/agents/` |
| TRAE | `trae` | 已识别的 TRAE 配置目录下 `skills/` | 同目录下 `agents/` |
| DSH | `dsh` | `.dsh/skills/` | `.dsh/agents/` |

该社区 Plugin 支持从 npm 包或源码进行项目级安装，不作为官方 Marketplace Plugin 发布。目标项目路径建议使用绝对路径。

## 三、验证安装

安装器应报告 4 个 Skill 和 5 个 Agent。还应确认主工作流及其 References 已完整安装：

```bash
cd /path/to/training-project
set -e

test -f .cannbot/plugins/model-train-precision-diagnose/workflows/precision-diagnose-workflow.md
test -f .cannbot/plugins/model-train-precision-diagnose/workflows/references/preflight-checklist.md
test -f .cannbot/plugins/model-train-precision-diagnose/workflows/references/evidence-and-risk-policy.md
echo "workflow and references: OK"
```

OpenCode 可进一步检查 Agent：

```bash
opencode agent list
# 应看到 5 个 model-train-precision-* Agent
```

任一工作流或 Reference 缺失都表示安装不完整，不应开始诊断。

## 四、开始诊断

在目标训练项目根目录启动客户端，例如：

```bash
cd /path/to/training-project
opencode  # 也可以是 codex、claude 或对应客户端
```

首条请求建议直接提供以下信息；未知项写“未知”：

```text
同一数据集输入和权重下，固定 Seed 并开启确定性后运行两次，GradNorm 仍不一致，请定位该精度问题。

项目路径：<绝对路径>
训练入口与命令：<脚本及完整命令>
实际训练环境：<Node、容器及 Conda/venv；进入方式未知则写未知>
现象：<有限值偏差 / NaN、Inf、Overflow / 两次受控运行不一致>
复现条件：<首次已知 Step、Rank、阶段和复现频率>
标杆：<运行或产物路径；没有则写无>
现有证据：<日志、配置、Checkpoint、dump数据 等绝对路径>
```

## 五、核心工作流

Plugin 按以下顺序推进：

```text
Intake → 症状路由 → Preflight → Scope Reducer → 一个症状 Agent → Reviewer
                                      ↑                    │
                                      └──── 按证据回环 ────┘
```

- 首个已确认异常是 NaN/Inf/Overflow 时优先 E04；传播后的 Loss NaN 不覆盖更早的有限值偏差或重复运行不一致。
- E01/E02 必须先确认可比的外部标杆；缺少标杆时不会执行 compare 或套用默认阈值。
- E08 必须基于固定条件下的受控 A/B 运行；先核对随机性和确定性设置，再决定是否采集算子数据。
- Agent 会先确认实际训练所在的 Node、容器和 Python 环境，不用登录节点或默认 Shell 代替训练上下文。

完整阶段规则见[主工作流](workflows/precision-diagnose-workflow.md)。

## 六、诊断产物与执行边界

默认在目标项目下创建 `precision_diagnosis/<case-id>/`：

| 产物 | 作用 |
| --- | --- |
| `intake_record.md` | 症状、拓扑、入口、复现性和标杆 |
| `preflight_record.md` | 数据、代码、配置、权重和环境核对结果 |
| `scope_record.md` | 当前复现范围及缩圈实验取舍 |
| `experiment_matrix.md` | 单变量实验及结果 |
| `evidence_index.md` | 日志、dump 和其他证据的来源索引 |
| `final_report.md` | 根因等级、证据、修复验证和未闭环项 |

现有文件和日志可直接只读分析。下列动作会在执行前确认范围和风险：

- 启动或重复训练、多机多卡作业；
- 修改源码、配置、并行拓扑或模型结构；
- 插入检测或采集逻辑、执行大容量 dump；
- 在共享存储创建探测文件或通过调度系统、SSH/pssh 拉起作业；
- 安装、升级或替换训练环境中的软件包。

特征值检测与 Ascend DMI AICORE 诊断仅在现有证据满足触发条件时作为高风险选项，由用户决定是否执行；它们不是默认 Preflight。
本 Plugin 不发起或编排 AICORE 压测。

多节点实验还需要所有参与 Node 可访问的共享存储，以及现场已有的调度或 SSH/pssh runbook。`manual-ssh` 模式需要用户或集群管理员预先配置公钥免密和主机身份信任。

## 七、更新与帮助

更新时按[第二章](#二安装)原安装方式获取最新 npm 包或源码（源码方式同时更新 submodule），再使用相同客户端和目标项目重新执行安装。

查看安装参数：

```bash
bash init.sh --help
```
