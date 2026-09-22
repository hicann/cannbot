---
name: repo-build-guide
description: 构建可供 CANN Bench 评测的 Ascend C 直调源码和 cann_bench wheel，检查真实加载路径与版本。编译、安装、调试构建问题时使用。
---

# 仓库构建指南

本仓采用 cann-bench `examples/direct_launch_example` 工程：bisheng 编译 kernel，g++ 编译注册包装，链接 `_C.abi3.so` 并生成 `dist/cann_bench*.whl`。评测器可从源码根目录调用 `bash build.sh`。

读取 [构建与验证](references/build-guide.md)，按当前环境、源码快照和目标芯片构建。构建成功、wheel 可导入与算子功能通过分别记录，不混为一个结论。
