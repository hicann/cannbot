---
name: repo-env-check
description: PM 检查 CANN Bench 直调算子开发及评测环境，持久化 .cannbot/环境信息.md；后续任务复用已有通过记录。
---

# 仓库环境检查

由 PM 在当前用户会话执行，不进入节点图。只检查环境，不安装、升级或修复依赖。首次需求缺项应先向用户发问，不等完整环境检查结束。

## 复用与路径

仓库级记录为 `<目标仓>/.cannbot/环境信息.md`。存在非空通过记录时直接复用，不因开发新算子重新运行 NPU、编译器或版本探测；复制为本轮 `$WORK_DIR/环境信息.md`，记录原始时间及来源，运行中只读。

空记录、失败记录或当前任务超出记录支持范围时报告差异，不把文件存在当通过，也不自动重新校验。用户明确要求重新检查时保留旧版本，更新发生在工作流运行前或整轮退出后。

## 首次检查清单

仅在没有仓库级记录时执行；结果及原始日志放在 `.cannbot/环境检查/`，通过后按 [环境信息](references/环境信息.md) 发布仓库级记录。

| 检查项 | 方法与通过依据 |
|--------|----------------|
| 评测源码 | 定位用户指定 checkout，或 `.cannbot/dependencies/ops-direct-invoke/cann-bench/`；记录 commit，确认 direct_launch_example、目标任务格式、kernel_eval CLI 可用 |
| NPU | `npu-smi info` 与所用 torch_npu 的设备信息；记录实际型号、可用设备 ID、状态及与需求目标的关系，不拿需求当检测结果 |
| CANN/编译器 | 已生效的 `ASCEND_HOME_PATH`、CANN 版本、bisheng/g++ 路径；核对当前 checkout 的要求与所选 SoC 映射 |
| Python/依赖 | 记录 Python 环境和版本、torch/torch_npu 的版本与导入；核对当前 pyproject/uv.lock/requirements 和示例依赖，不能盲目升级或重装 |
| 构建工具 | CMake、build/setuptools/wheel；直调示例要求 CMake ≥ 3.16，保留其新 CMake 链接兼容设置 |
| 评测组件 | 检查 kernel_eval CLI 的 help/任务发现、`cann_bench_utils` 是否可导入及其来源；缺失时报告准备项，不在检查中静默触发安装 |
| 仓库资产 | 记录候选源码目录、任务目录、已有 pytest/评测入口与算子文档线索；不把一次快照当作以后永久现状 |

核对版本的官方快速入门要求 Python 3.10+、CANN 9.1.0+，实际依赖以当前 checkout 为准；torch/torch_npu 组合须按该版本的依赖和平台匹配。上述最低版本不等于任意版本组合都兼容，不宣称本次检查已完成 kernel 编译或设备精度验收。

不要用 `scripts/run_evaluation.sh` 作无副作用探测：它可能构建辅助组件、安装候选包并运行评测。环境准备缺项由调用方安排修复，完成后再按授权复核；不得通过禁用保护组件绕过。

## 完成条件

缓存与本轮副本均非空，结论通过，包含 checkout/commit、Python 环境、设备、版本、支持范围和证据路径。后续源码构建、设备测试属于正常开发执行，不属于重复环境调查。

## 核对依据

已核对 cann-bench `08d519c503843bce5fd4672ffa2259abeb22fb00`；按实际 checkout 记录版本和差异。

- [docs/guide/quick_start.md](https://gitcode.com/cann/cann-bench/blob/08d519c503843bce5fd4672ffa2259abeb22fb00/docs/guide/quick_start.md)
- [requirements.txt](https://gitcode.com/cann/cann-bench/blob/08d519c503843bce5fd4672ffa2259abeb22fb00/requirements.txt)
- [scripts/run_evaluation.sh](https://gitcode.com/cann/cann-bench/blob/08d519c503843bce5fd4672ffa2259abeb22fb00/scripts/run_evaluation.sh)
