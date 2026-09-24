# UT 单文件结构与 run.sh

一个算子的 Tiling UT = 一个 `test_tiling_gtest.cpp` + `CMakeLists.txt` + `run.sh`，放在 `$WORK_DIR/op/tests/tiling/`。本文件是三者各自的固定骨架（模式 B 形态）；case 矩阵与 oracle 属于任务本身，不在此列。

## 大文件分片写（强制）

`test_tiling_gtest.cpp` 全文通常 1500+ 行。**禁止用单次 write 调用写整篇**——单次输出超限会被截断，模型陷入"重新宣告→再截断"死循环。正确写法：

1. 第一次 `write` 只写文件头部（includes + fixture + mock harness + 工具函数），以一个未完成的类/命名空间结尾；
2. 之后用多次 `edit` 追加：EXCEPTION-COVERAGE 矩阵注释块 → 各 TEST_F 组 → 尾部注册；
3. 每次追加控制在 ~300 行以内；写完用 `g++ -fsyntax-only` 或直接 run.sh 验证。

## test_tiling_gtest.cpp 的固定节次

```text
1. 文件头注释块        —— 数据来源清单（design/*.md → 各自钉什么）+ PLATFORM MOCK 节
                          （记录已验证 key 映射，来自 references/platform-mock.md）
2. includes           —— 见下
3. LogCapture         —— references/log-capture.md 的模板照抄
4. SetupPlatform(pi, coreNum, ubSize) —— references/platform-mock.md 配方
5. LoadTilingKernel   —— registry dlopen，见下
6. MakeShapePair / case 输入构造
7. Invoke(ctx, ...)   —— builder 拼装 + 调 TilingFunc + 回读平台值
8. TEST_F 们          —— 每 case：mock 平台 → Invoke → 断言（成功 case 钉 TilingData 字段/
                          blockDim/tilingKey/workspace；失败 case 断返回码 + LogCapture 锚点）
9. EXCEPTION-COVERAGE MATRIX 注释块
```

核心 includes（pkg_inc 为主）：

```cpp
#include "graph/ascend_string.h"
#include "exe_graph/runtime/continuous_vector.h"
#include "exe_graph/runtime/storage_shape.h"
#include "exe_graph/runtime/tiling_context.h"
#include "exe_graph/runtime/tiling_data.h"
#include "exe_graph/runtime/tensor.h"
#include "base/context_builder/op_tiling_context_builder.h"
#include "base/registry/op_impl_space_registry_v2.h"
#include "platform/platform_infos_def.h"
```

## SetupPlatform（模板）

```cpp
void SetupPlatform(fe::PlatFormInfos &pi, uint32_t coreNum, uint64_t ubSize)
{
    pi.Init();
    std::map<std::string, std::string> soc  {{"ai_core_cnt", std::to_string(coreNum)}};
    std::map<std::string, std::string> spec {{"ub_size", std::to_string(ubSize)},
                                              {"ubblock_size", "32"}};
    std::map<std::string, std::string> ver  {{"version", "Ascend950"}, {"NpuArch", "3510"}};
    pi.SetPlatformRes("SoCInfo", soc);
    pi.SetPlatformRes("AICoreSpec", spec);
    pi.SetPlatformRes("version", ver);
}
```

## LoadTilingKernel（registry dlopen，pattern B 核心）

```cpp
gert::OpImplKernelRegistry::TilingKernelFunc LoadTilingKernel()
{
    const std::string soPath = OP_HOST_SO_ABS;   // CMake bake 的绝对路径（隔离安装树内）
    fprintf(stdout, "[setup] loading op_host .so: %s\n", soPath.c_str());  // red-baseline 审计 grep 目标，必须保留
    gert::OppSoDesc soDesc({ge::AscendString(soPath.c_str())}, ge::AscendString("op_host_so"));
    auto spaceReg = std::make_shared<gert::OpImplSpaceRegistryV2>();
    if (spaceReg->AddSoToRegistry(soDesc) != ge::GRAPH_SUCCESS) {
        fprintf(stderr, "[setup] FAILED to add op_host .so to registry\n");
        return nullptr;
    }
    gert::DefaultOpImplSpaceRegistryV2::GetInstance().SetSpaceRegistry(spaceReg);
    const auto *impl = gert::DefaultOpImplSpaceRegistryV2::GetInstance()
                          .GetSpaceRegistry()->GetOpImpl(kOpType);
    if (impl == nullptr || impl->tiling == nullptr) {
        fprintf(stderr, "[setup] FAILED: tiling kernel for '%s' not found in loaded .so\n", kOpType);
        return nullptr;
    }
    return impl->tiling;
}
```

返回 nullptr 的每一支都必须先打 `[setup] FAILED ...` 到 stderr——调用方（SetUp）在拿到 nullptr 时直接 `FAIL()` 并打印该行，让失败停在加载阶段而不是变成空指针段错误。

**注册失败排查（现象→原因→修法）**：

- **现象**：`[setup] loading op_host .so: <路径>` 已打印，随后 `FAILED: tiling kernel ... not found`；或 UT 输出出现 `do not registe tiling struct` 类字样。
- **原因**：加载的 .so 里没有该算子的 tiling 注册——常见于 .so 不是本次新装包的产物（OP_HOST_SO_ABS 指向旧安装树）、或 IMPL_OP_OPTILING 所在编译单元被裁剪/未编入包。
- **修法**：核对 OP_HOST_SO_ABS 指向的 .so 确实来自本次 run.sh 装出的 dev-package（路径含 `dev-package/vendors/<OpPascal>/`）；确认 op_host 源码的 IMPL_OP_OPTILING 注册宏仍在且该编译单元参与了建包。不要在 UT 侧绕过。

`OP_HOST_SO_ABS` 由 CMake `target_compile_definitions(${UT_EXE} PRIVATE OP_HOST_SO_ABS="${OP_HOST_SO}")` 注入；`OP_HOST_SO` glob 自隔离安装树 `dev-package/vendors/<OpPascal>/op_impl/ai_core/tbe/op_tiling/lib/linux/$(uname -m)/libcust_opmaster_rt2.0.so`，glob 命中数 ≠1 时 FATAL_ERROR。

## builder 拼装（Invoke 内）

```cpp
gert::OpTilingContextBuilder builder;
struct DummyCompileInfo {} compileInfo;
builder.OpType(ge::AscendString(kOpType))
    .OpName(ge::AscendString(kOpType))
    .IONum(inCount, outCount)
    .InputTensors(inPtrs)
    .OutputTensors(outPtrs);
// 有 attr 时按 index 顺序 AppendAttr(a0); AppendAttr(a1); —— GetAttrs(i) 与之对应
builder.CompileInfo(&compileInfo)
    .PlatformInfo(&platformInfo)
    .TilingData(reinterpret_cast<gert::TilingData *>(tilingDataBuf.get()))
    .Workspace(reinterpret_cast<gert::ContinuousVector *>(wsBuf.get()));
auto holder = builder.Build();
gert::TilingContext *ctx = holder.GetContext();
```

要点：

- `tilingDataBuf = gert::TilingData::CreateCap(sizeof(<Op>TilingData))`，`wsBuf = gert::ContinuousVector::Create<size_t>(16)`；Create 不清零——缓冲预置确定性值（红相 stub 不写 TilingData 时断言才确定）。
  - **现象**：同一 case 结果不稳定——有时过、有时不过，重跑两次结果不同；而 oracle 与 case 逻辑都没改过。
  - **原因**：CreateCap/Create 分配的缓冲是脏数据，TilingData 残留字节恰好撞上断言期望值，失败呈间歇性。
  - **修法**：TilingData 缓冲在 Invoke 前整体 memset 归零；workspace 槽位机制不同——对 wsBuf 整体 memset 是错的，`Build()` 之后经 `ctx->GetWorkspaceSizes(1)` 拿到槽位指针逐个置零（该指针指向 ContinuousVector 内部，改它是合法的）。不是改 oracle。
- TilingData 布局按 design/TilingData.md §1 **手工转写**进 UT（裸 struct + 同名字段），**不得** include 算子包的 tiling_struct.h / *_tiling_arch35.h——oracle 独立性是审计算项。
- 输入 tensor 用 `gert::Tensor(shape, fmt, gert::kOnHost, dtype, nullptr)` + `StorageShape::MutableOriginShape/AppendDim`；const 值输入（如 axis 列表）的数据缓冲紧随 gert::Tensor 头之后存放（`Tensor::CreateFollowing` 分配的总长 = 头 + 数据）。

## case 输入构造（Invoke 前的完整片段）

把上一节的零散要点串起来，Invoke 前的构造顺序固定为：

```cpp
// 1) 形状：Origin/Storage 同形逐维 append
gert::StorageShape xShape = MakeShapePair({2, 8});          // 本 case 的输入 shape
gert::StorageShape yShape = MakeShapePair({2, 8});          // 本 case 的输出 shape

// 2) tensor：kOnHost + dtype；数据指针为 nullptr（shape 类输入不需要真实数据）
gert::Tensor xTensor(xShape, gert::StorageFormat(ge::FORMAT_ND, ge::FORMAT_ND, gert::ExpandDimsType()),
                     gert::kOnHost, ge::DT_FLOAT, nullptr);
gert::Tensor yTensor(yShape, gert::StorageFormat(ge::FORMAT_ND, ge::FORMAT_ND, gert::ExpandDimsType()),
                     gert::kOnHost, ge::DT_FLOAT, nullptr);
// const 值输入（如 attr-as-tensor 的 axis 列表）：CreateFollowing 分配 头+数据，
// 数据区紧随 gert::Tensor 头之后写入（见要点第三条）

// 3) 输出缓冲：分配即预置确定性值
auto tilingDataBuf = gert::TilingData::CreateCap(sizeof(OpTilingData));
memset(tilingDataBuf.get(), 0, sizeof(OpTilingData));   // TilingData 整体归零
auto wsBuf = gert::ContinuousVector::Create<size_t>(16);          // workspace 槽位在 Build() 后置零（见要点第一条）

// 4) 输入/输出指针数组：顺序与 IONum/OpDef 的 IO 声明一致
gert::Tensor *inPtrs[]  = {&xTensor};
gert::Tensor *outPtrs[] = {&yTensor};
```

之后进入 builder 拼装（上一节）。`TilingData` 布局转写 struct（示例中的 `OpTilingData`）按 design/TilingData.md §1 手工转写，命名模式 `<OpPascal>TilingData`。

## run.sh 四步骨架（隔离安装）

```bash
# 1) 建包：cmake -S $PKG_DIR -B build && cmake --build build --target <Op>_ascend950 && cpack
#    产物 build/custom_opp_ubuntu_x86_64.run
# 2) 隔离安装（共享工作区 dev-package 不受影响，并行任务互不污染）：
bash "$RUN_PKG_FILE" --quiet --nox11 --install-path="${SCRIPT_DIR}/dev-package"
# 3) 建 UT：cmake -S ${SCRIPT_DIR} -B build2 -DCANN_HOME=... -DOPP_INSTALL_DIR=...（dev-package）&& cmake --build
# 4) 跑 UT（日志前提 + tee 留档）：
OP_HOST_SO_DIR="${INSTALL_DIR}/vendors/<OpPascal>/op_impl/ai_core/tbe/op_tiling/lib/linux/$(uname -m)"
export LD_LIBRARY_PATH="${OP_HOST_SO_DIR}:${CANN_HOME}/lib64:${LD_LIBRARY_PATH}"
export ASCEND_SLOG_PRINT_TO_STDOUT=1
export ASCEND_GLOBAL_LOG_LEVEL=3
"${BUILD_DIR}/test_tiling_gtest" 2>&1 | tee "${SCRIPT_DIR}/ut-baseline.log"
```

TDD 红相语义：run.sh 退出码非 0 是预期行为（红基线），`ut-baseline.log` 存 `[  PASSED  ]/[  FAILED  ]` 汇总；绿相判定交给 verifier。

## 黄金样例

`assets/golden_probe.cpp` = 可独立编译运行的最小验证器，覆盖 SDK 布局、链接配方、平台 mock 映射三项（builder 链与 LogCapture 不在探测范围），链接命令见文件头注释。写 UT 前先跑它，10 秒内区分"harness 基础设施坏了"还是"case/oracle 错了"。
