---
name: repo-op-templates
description: 从 cann-bench 的 direct_launch_example 复用直调工程骨架和算子模板；新建工程或新增算子时使用。
---

# 算子工程模板

工程来源为 cann-bench 的 `examples/direct_launch_example/`，保留它的构建、接口注册和 Python 导出约定。目标仓已经有兼容工程时就地扩展，不重建或覆盖已有代码。

| 工作 | 参考 |
|------|------|
| 取得官方模板、建立工程骨架 | [工程骨架](references/project-skeleton.md) |
| 添加 kernel、launch、注册和 Python 接口 | [算子模板](references/operator-template.md) |

模板是可运行工程的起点，不证明其 Add/Sqrt 的算法、dtype 或精度适合目标算子；按已确认规格完成实现。
