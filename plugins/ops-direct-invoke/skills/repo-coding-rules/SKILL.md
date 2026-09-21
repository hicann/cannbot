---
name: repo-coding-rules
description: CANN Bench 候选算子的实现真实性、包装边界、工程接口与 Ascend C 代码质量要求。编码、修复和检视时使用。
---

# 仓库编码规则

算子计算必须来自本工程的真实 NPU kernel，并符合 CANN Bench 的提交与运行接口。读取 [编码检查表](references/red-lines.md)，按实际代码和证据检视；不要把静态规则套到测试 golden 上，也不把样例结构当作所有算子都适用的算法方案。

违规项给出位置、影响和修正要求。规则只定义代码与交付质量，不持有调度状态、不指定流程回退。
