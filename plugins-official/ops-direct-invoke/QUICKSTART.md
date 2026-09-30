# ops-direct-invoke 快速开始

设计思想、功能和目录组织见 [README.md](README.md)。

## 安装

需要 Node.js 20.11+、Python 3、PyYAML、已安装的 Agent CLI、支持 procedure 字段的 workflow-orchestrator，以及用于默认后台启动的 tmux。公共 Skill 统一从 `vendor/cannbot-skills` 安装。源码仓先执行 `git submodule update --init --recursive vendor/cannbot-skills`，然后在 cannbot 根目录执行：

```bash
node script/bin/cannbot.js install ops-direct-invoke \
  --source "$PWD" \
  --tool codex --target /absolute/operator-repo
```

安装器按 `ops-direct-invoke` 定位官方插件目录。也可在本插件目录执行 `bash init.sh project codex /absolute/operator-repo`。目前验证的客户端为 opencode、codex、claude。源码安装把 Skill 链接到源目录，打包安装复制完整 Skill 资源；角色资产安装在目标仓中。子仓可用 `--override-skills /absolute/overrides` 覆盖已有的 `repo-*` Skill，入口及调度 Skill 不在覆盖范围内。

## 安装 Skills 依赖

在本插件目录运行 `init.sh` 即完成依赖安装：

```bash
bash init.sh [project] [opencode|codex|claude|trae|dsh] [install_path]
```

默认客户端为 opencode，默认安装到 cannbot 仓根；`install_path` 用于指定目标算子仓。每次只安装一种客户端，需要多个 Agent 工具时分别执行。完整参数说明见 `bash init.sh --help`。

## 发起任务

在目标项目目录中启动所选 Agent 客户端，提出需求，例如：

```text
请使用 ops-direct-invoke 开发一个 abs 算子，开发语言为 Ascend C 直调。
```

使用 CANNBot-DSL 时明确开发语言，并提供目标 wheel、目标芯片和相关需求资料。PM 先对齐缺失信息，随后按语言选择流程：AscendC 使用 basic 或独立 feasibility，DSL 使用 op-dev。非算子开发任务可由 PM 自由规划；子 Agent 仍统一通过 harness 下发。

项目指引位于 `AGENTS.md`（Claude 使用 `CLAUDE.md`）；角色与 Skill 的实际路径见客户端配置目录下的 `cannbot-plugin.json`。Skill 在源码安装下使用软链接，PM 指引和角色配置由安装器生成，源文件变更后需要重新安装同步。

## 查看结果与恢复

每轮 YAML、日志和交付记录位于 `.cannbot/<任务名>/workflow<序号>/`。PM 按 `workflow-orchestrator` Skill 查询进度和处理审批，结束后汇总交付件与验证结果；启动成功不代表交付完成。

恢复同一轮时沿用原 YAML 和工作目录，通过公开恢复接口执行；需要新一轮修复时使用新目录，不删除或复制旧调度状态。手动组装、启动的参数见 [算子流程入口](skills/ops-direct-invoke/SKILL.md)。

## 维护后的回归

在应用仓根目录运行完整测试：

```bash
python3 plugins-official/ops-direct-invoke/skills/ops-direct-invoke-maintain/test/ut/test_all.py
```

安装后可从实际 Skill 目录调用同一入口。需要 Python 3.9+、PyYAML 和 harness；测试不调用真实模型或 NPU。默认使用同级安装的 harness，源码仓下使用应用仓的 harness；其他位置用 `--harness-skill /absolute/workflow-orchestrator` 指定。测试使用临时目录，不需要 tmux，可从任意当前目录运行。测试边界见 [测试体系](skills/ops-direct-invoke-maintain/reference/tests.md)。
