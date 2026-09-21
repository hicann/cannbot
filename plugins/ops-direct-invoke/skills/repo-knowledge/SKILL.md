---
name: repo-knowledge
description: CANN Bench 直调算子工程知识：评测任务、源码提交接口、精度与评分契约。理解本仓交付和评测要求时使用。
---

# 仓库领域知识

本仓开发通过 Ascend C `<<<>>>` 启动的算子，提交给 CANN Bench 的 CANN 评测后端。候选源码工程、评测任务数据与评测器是三个独立对象：源码实现算子，任务描述规格与 golden，用例由评测器加载并执行。

源码交付保留 `cann_bench` 包及同名算子命名空间，以 `examples/direct_launch_example` 为工程基础。评测任务按 `proto.yaml`、`golden.py`、`cases.yaml`、`desc.md` 组织；同一评测接口承接黑盒、白盒和回归，不按用例来源划分工作模式。

需要核对目录、接口发现、精度或评分含义时，读取 [评测契约](references/evaluation-contract.md)。本 Skill 只提供工程事实，不决定流程节点或替用户选择技术路线。
