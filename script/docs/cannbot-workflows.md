# CANNBot 工作流安装与使用指南

## 安装方式

普通用户在目标项目中执行各插件下方的 `npx` 命令。源码安装进入对应插件目录执行：

```bash
cd plugins/<plugin>
bash init.sh
```

安装器按需初始化 Skill submodule，并将 Skill 链接到 cannbot 仓库根目录的客户端配置中。

## 算子领域

### 算子生成

#### Step 1：一键安装

通过 npm 插件化一键安装。

OpenCode：

```bash
npx @cannbot-plugin/cannbot install ops-direct-invoke --tool opencode
```

Codex：

```bash
npx @cannbot-plugin/cannbot install ops-direct-invoke --tool codex
```

Claude Code：

```bash
npx @cannbot-plugin/cannbot install ops-direct-invoke --tool claude
```

TRAE：

```bash
npx @cannbot-plugin/cannbot install ops-direct-invoke --tool trae
```

DSH：

```bash
npx @cannbot-plugin/cannbot install ops-direct-invoke --tool dsh
```

#### Step 2：启动 Agent 客户端

在当前项目根目录启动 Agent 客户端。以 OpenCode 为例：

```bash
opencode
```

#### Step 3：提示词样例

```text
请使用 ops-direct-invoke 工作流，根据当前项目中的算子需求生成完整的 Ascend C Kernel 直调算子。
先分析需求和运行环境，再完成方案设计、代码实现、测试、精度与性能验收。
```

### 算子测试

`ascendc-st-design` 的生成脚本需要 Python 3，以及 PyYAML、NumPy 和 pandas。安装插件后可先检查运行环境：

```bash
python3 -c "import yaml, numpy, pandas"
```

#### Step 1：一键安装

通过 npm 插件化一键安装。

OpenCode：

```bash
npx @cannbot-plugin/cannbot install ascendc-st-design --tool opencode
```

Codex：

```bash
npx @cannbot-plugin/cannbot install ascendc-st-design --tool codex
```

Claude Code：

```bash
npx @cannbot-plugin/cannbot install ascendc-st-design --tool claude
```

TRAE：

```bash
npx @cannbot-plugin/cannbot install ascendc-st-design --tool trae
```

DSH：

```bash
npx @cannbot-plugin/cannbot install ascendc-st-design --tool dsh
```

#### Step 2：启动 Agent 客户端

在当前项目根目录启动 Agent 客户端。以 OpenCode 为例：

```bash
opencode
```

#### Step 3：提示词样例

```text
使用 ascendc-st-design skill，为当前项目的 add_rms_norm Ascend C 算子设计 L0/L1/L2 系统测试（ST）用例。
基于 REQUIREMENTS.md 和 aclnn 接口文档完成参数定义、测试因子提取与约束分析，并在 operators/add_rms_norm/tests/st/ 下生成 L0/L1/L2 用例和覆盖报告。
```

## 模型领域

### 模型迁移与推理优化


#### Step 1：一键安装

通过 npm 插件化一键安装。

OpenCode：

```bash
npx @cannbot-plugin/cannbot install model-infer-optimize --tool opencode
```

Codex：

```bash
npx @cannbot-plugin/cannbot install model-infer-optimize --tool codex
```

Claude Code：

```bash
npx @cannbot-plugin/cannbot install model-infer-optimize --tool claude
```

TRAE：

```bash
npx @cannbot-plugin/cannbot install model-infer-optimize --tool trae
```

DSH：

```bash
npx @cannbot-plugin/cannbot install model-infer-optimize --tool dsh
```

#### Step 2：启动 Agent 客户端

在当前项目根目录启动 Agent 客户端。以 OpenCode 为例：

```bash
opencode
```

#### Step 3：提示词样例

```text
使用 model-infer-optimize，把当前 PyTorch 模型迁移到昇腾 NPU 推理。先建立 CPU 基线，再处理不支持算子和设备适配，最后完成精度对齐、性能分析和优化，并输出可复现的验证命令。
```
