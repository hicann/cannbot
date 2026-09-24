# Ascend C 算子工程结构

## 标准目录布局

```
<op_name>_package/
├── CMakeLists.txt              # 顶层构建脚本（6步管线）
├── build.sh                    # 构建入口脚本
├── build/                      # 构建产物（gitignore）
│   ├── autogen/                #   产物①②④: op_build 生成的中间文件
│   └── ascendc_kernels/        #   产物③⑧⑨: kernel 编译产物
├── op_host/                    # Host 侧代码（tiling、infershape、OpDef）
│   ├── <op>_def.cpp            #   算子定义（OpDef: dtype/format/attr 声明）
│   ├── <op>_infershape.cpp     #   形状推导
│   ├── <op>_tiling_arch35.h    #   tiling 头文件（compile info 结构体）
│   └── arch35/
│       └── <op>_tiling_arch35.cpp  # tiling 实现（TilingFunc、tiling key 设置）
├── op_kernel/                  # Kernel 侧代码（NPU 设备代码）
│   ├── <op>_apt.cpp            #   kernel 入口（__global__ 函数，被 asc_opc 编译）
│   └── arch35/
│       ├── <op>_struct.h       #   TPL 模板参数声明（ASCENDC_TPL_ARGS_DECL / SEL）
│       ├── <op>_kernel.h       #   kernel 实现类（ScaleCustomKernel<T, RANK>）
│       └── <op>_tiling_struct.h #  TilingData 结构体定义
├── op_api/                     # ACLNN API 代码（C 接口）
│   ├── aclnn_<op>.h            #   ACLNN API 头文件
│   ├── aclnn_<op>.cpp          #   ACLNN API 实现
│   └── <op>.cpp                #   L0 operator dispatch
├── op_graph/                   # Graph IR 代码（GE 图引擎）
│   ├── <op>_graph_infer.cpp    #   图推理
│   ├── <op>_proto.h            #   proto 头文件
│   └── <op>_proto.cc           #   proto 实现
└── tests/                      # 测试
    ├── aclnn/                  #   ACLNN ST 测试
    ├── geir/                   #   GE IR 测试
    └── tiling/                 #   Tiling UT 测试
```

## 命名规范

一个算子有三种命名形式，必须保持一致：

| 形式 | 示例 | 用途 |
|------|------|------|
| PascalCase | `ScaleCustom` | 类名、OP_TYPE、ASCENDC_TPL_ARGS_DECL 第一参数、IMPL_OP_OPTILING |
| snake_case | `scale_custom` | 文件名、函数名、命名空间 |
| UPPER_SNAKE | `SCALE_CUSTOM` | 宏名、头文件守卫、TPL rank 常量 |

### 替换规则（从 ScaleCustom 创建 FooBar）

```
ScaleCustom → FooBar              (类名、OP_TYPE、package_name)
scale_custom → foo_bar            (文件名、函数名、命名空间)
SCALE_CUSTOM → FOO_BAR            (宏名、头文件守卫)
scale_custom_apt → foo_bar_apt    (kernel 文件名、opFile 配置)
ScaleCustomKernel → FooBarKernel  (kernel 实现类名)
```

## 关键文件职责

### op_host/\<op\>_def.cpp — 算子定义（外层枚举的来源）

**这是构建管线的起点。**

```cpp
class ScaleCustom : public OpDef {
    explicit ScaleCustom(const char* name) : OpDef(name) {
        this->Input("x")
            .ParamType(REQUIRED)
            .DataType({ge::DT_FLOAT16, ge::DT_FLOAT, ge::DT_BF16})  // 3种dtype → 3个.o
            .Format({ge::FORMAT_ND, ge::FORMAT_ND, ge::FORMAT_ND})
            .UnknownShapeFormat({ge::FORMAT_ND, ge::FORMAT_ND, ge::FORMAT_ND})
            .AutoContiguous();
        // ... scale, bias, y 类似

        this->Attr("axis").Int(1L);
        this->Attr("num_axes").Int(1L);
        this->Attr("scale_from_blob").Bool(true);

        OpAICoreConfig aiCoreConfig;
        aiCoreConfig.DynamicCompileStaticFlag(true)
            .DynamicRankSupportFlag(true)
            .DynamicShapeSupportFlag(true)
            .ExtendCfgInfo("opFile.value", "scale_custom_apt");  // 链接到 kernel 文件名
        this->AICore().AddConfig("ascend950", aiCoreConfig);
    }
};
OP_ADD(ScaleCustom);
```

**关键点**：
- `.DataType({...})` 列表长度即外层枚举数
- `.Format({...})` 列表长度必须与 DataType 一致
- `.ExtendCfgInfo("opFile.value", "scale_custom_apt")` 必须匹配 kernel 文件名（不含 `.cpp`）
- `AddConfig("ascend950", ...)` 指定目标芯片

### op_kernel/\<op\>_struct.h — TPL 模板参数声明（内层枚举的来源）

```cpp
#include "ascendc/host_api/tiling/template_argument.h"

#define SCALE_CUSTOM_RANK_4 4
#define SCALE_CUSTOM_RANK_8 8

// 声明模板参数: RANK, 默认值8, 可选 {4, 8}
ASCENDC_TPL_ARGS_DECL(ScaleCustom,
    ASCENDC_TPL_UINT_DECL(RANK, 8, ASCENDC_TPL_UI_LIST,
        SCALE_CUSTOM_RANK_4, SCALE_CUSTOM_RANK_8)
);

// 声明特化: 每行一个 → 每行生成一个 sub-kernel
ASCENDC_TPL_SEL(
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_UINT_SEL(RANK, ASCENDC_TPL_UI_LIST, SCALE_CUSTOM_RANK_4)),
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_UINT_SEL(RANK, ASCENDC_TPL_UI_LIST, SCALE_CUSTOM_RANK_8))
);
```

**关键点**：
- `ASCENDC_TPL_ARGS_DECL` 第一参数必须是 PascalCase 算子名
- `ASCENDC_TPL_SEL` 中的 `ARGS_SEL` 行数即内层枚举数
- 实例化由 `ASCENDC_TPL_SEL` 在外部声明，不在 C++ 使用点推导——少一行 SEL 就少一个实例化
- host 侧 tiling 通过 `GET_TPL_TILING_KEY(SCALE_CUSTOM_RANK_4)` 设置 tiling key
- tilingKey 的位编码规则（BOOL 取值、UINT 取下标）见 **references/tiling-key-encoding.md**

### op_kernel/\<op\>_apt.cpp — Kernel 入口（被 asc_opc 编译的文件）

```cpp
#include "kernel_operator.h"
#include "arch35/scale_custom_kernel.h"
#include "arch35/scale_custom_tiling_struct.h"

using TilingData4 = ScaleCustomTilingData<4>;
using TilingData8 = ScaleCustomTilingData<8>;

template<int RANK>
__global__ __aicore__ void scale_custom(
    GM_ADDR x, GM_ADDR scale_in, GM_ADDR bias,
    GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    GM_ADDR ins[3]  = {x, scale_in, bias};
    GM_ADDR outs[1] = {y};

    REGISTER_NONE_TILING;
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);

    if constexpr (RANK == 4) {
        GET_TILING_DATA_WITH_STRUCT(TilingData4, td, tiling);
        ScaleCustomKernel<DTYPE_X, 4> kernel;   // DTYPE_X 是宏，RANK 是模板参数
        kernel.Init(ins, outs, &td);
        kernel.Process();
    } else {
        GET_TILING_DATA_WITH_STRUCT(TilingData8, td, tiling);
        ScaleCustomKernel<DTYPE_X, 8> kernel;
        kernel.Init(ins, outs, &td);
        kernel.Process();
    }
}
```

**关键点**：
- `DTYPE_X` 是预处理宏（由构建系统注入），不是 C++ 类型参数
- `RANK` 是模板参数（由 ASCENDC_TPL 系统控制实例化）
- `__global__ __aicore__` 是 Ascend C kernel 函数属性
- `GM_ADDR` 是设备全局内存指针类型
- kernel 函数名（`scale_custom`）必须与 OpDef 中的 `opInterface` 一致

### CMakeLists.txt — 6步构建管线

```cmake
# Step 1: 编译 host → libascend_all_ops.so → op_build 生成 ini/json
execute_process(COMMAND ${CMAKE_CXX_COMPILER} ... -o libascend_all_ops.so)
execute_process(COMMAND op_build ...)

# Step 2: 用手写实现覆盖自动生成的 stub
configure_file(op_api/aclnn_scale_custom.cpp ${AUTO_GEN_DIR}/aclnn_scale.cpp COPYONLY)

# Step 4: 创建 object libraries
add_library(cust_optiling_obj OBJECT ${host_tiling_srcs})
add_library(cust_opapi_obj OBJECT ${opapi_srcs})
add_library(cust_proto_obj OBJECT ${proto_srcs})

# Step 5: Vendor 打包
npu_op_package(${package_name} TYPE RUN CONFIG INSTALL_PATH ${CMAKE_BINARY_DIR})
npu_op_library(cust_optiling TILING)
npu_op_library(cust_opapi ACLNN)
npu_op_library(cust_op_proto GRAPH)
npu_op_package_add(${package_name} LIBRARY cust_optiling cust_opapi cust_op_proto)

# Step 6: Kernel 编译
npu_op_kernel_sources(ascendc_kernels
    OP_TYPE ScaleCustom
    KERNEL_DIR op_kernel
    KERNEL_FILE scale_custom_apt.cpp
)
npu_op_kernel_library(ascendc_kernels
    SRC_BASE ${CMAKE_CURRENT_SOURCE_DIR}
    TILING_LIBRARY cust_optiling
)
npu_op_package_add(${package_name} LIBRARY ascendc_kernels)
```

**关键 CMake 宏**：

| 宏 | 作用 |
|---|---|
| `npu_op_kernel_sources` | 声明 kernel 源文件（生成 source_files.ini 映射） |
| `npu_op_kernel_library` | 设置 kernel 编译环境（binary_dir、tiling_lib） |
| `npu_op_package` | 创建 vendor 包 |
| `npu_op_library` | 声明库（TILING / ACLNN / GRAPH 三种类型） |
| `npu_op_package_add` | 将库关联到 vendor 包 |

## 修改算子时的检查清单

三条清单都以完成判据收尾。

### 改 dtype（外层）

1. `op_host/*_def.cpp`: 修改 `.DataType({...})` / `.Format({...})` 列表
2. `op_kernel/*_apt.cpp`: 确认 `DTYPE_X` 的使用对新 dtype 兼容
3. `op_kernel/arch35/*_kernel.h`: 确认 kernel 实现类支持新 dtype

### 改 TPL 模板参数（内层）

1. `op_kernel/*_struct.h`: 修改 `ASCENDC_TPL_ARGS_DECL` 和 `ASCENDC_TPL_SEL`
2. `op_kernel/*_apt.cpp`: 修改 `if constexpr (RANK == ...)` 分支
3. `op_host/arch35/*_tiling_arch35.cpp`: 修改 `SetTilingKey()` 逻辑

### 改 kernel 逻辑

1. `op_kernel/arch35/*_kernel.h`: 修改 kernel 实现类
2. 外层 × 内层的每个组合都会受影响，全部重编
