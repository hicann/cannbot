# CANNBot

[![npm](https://img.shields.io/npm/v/%40cannbot-plugin%2Fcannbot?style=flat-square&label=npm)](https://www.npmjs.com/package/@cannbot-plugin/cannbot)

## 🚀 概述

CANNBot 面向 CANN 与昇腾 NPU 开发场景，提供可组合的 Agent 插件、专业角色和工程工作流，支持算子开发、算子测试、模型迁移与推理优化。

## ⚡ 快速开始

### npm 安装

```bash
npx @cannbot-plugin/cannbot@latest install ${plugin} --tool opencode
```

### 源码安装

```bash
git clone --recurse-submodules --shallow-submodules https://gitcode.com/cann/cannbot.git
cd cannbot/plugins/${plugin}
bash init.sh
```

`${plugin}`：插件名称，见[官方插件](#-官方插件)，例如 `ops-direct-invoke`。

## 📦 官方插件

| 插件 | 能力 |
|------|------|
| [`ops-direct-invoke`](plugins/ops-direct-invoke/) | skill 驱动的多角色直调算子开发工作流：8 阶段 7 CP 全流程、静默模式、可插拔流程插件、算子仓继承定制 |
| [`ascendc-st-design`](plugins/ascendc-st-design/) | Ascend C 算子 L0/L1/L2 ST 用例设计 |
| [`model-infer-optimize`](plugins/model-infer-optimize/) | NPU 模型迁移、精度对齐与推理性能优化 |

## 📖 文档

- [插件安装与工作流](script/docs/cannbot-workflows.md)
- [仓库架构与维护](docs/repository-guide.md)
- [插件目录说明](plugins/README.md)
- [npm 构建与发布](script/README.md)

## 💬 相关信息

- [CANNBot Skills](https://gitcode.com/cann/cannbot-skills)
- [问题反馈](https://gitcode.com/cann/cannbot/issues)
- [许可证](LICENSE)
