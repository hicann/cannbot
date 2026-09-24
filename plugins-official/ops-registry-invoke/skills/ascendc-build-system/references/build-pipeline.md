# Ascend C 构建管线

从源码到设备二进制的 5 层变换，以及每层留下的可观测产物。

## 管线全图

```
源文件输入
├─ op_host/*_def.cpp          → 声明 dtype 组合 (外层枚举)
├─ op_kernel/*_struct.h       → 声明 TPL 模板参数 (内层枚举)
└─ op_kernel/*_apt.cpp        → kernel 逻辑 (使用 DTYPE_X 宏 + RANK 模板参数)

Stage 1: CMake Configure (g++ + op_build)
│  g++ 编译 host 源码 → libascend_all_ops.so (产物①)
│  op_build 读取 .so → aic-*-ops-info.ini (产物②)
│  parse_ini_to_json → aic-*-ops-info.json (产物③)
│
Stage 2: CMake Configure (CMake 宏注册)
│  npu_op_kernel_sources → *_source_files.ini (产物④: op_type→kernel.cpp映射)
│  npu_op_kernel_library → 设置 binary_dir / src_base / tiling_lib
│
Stage 3: Build (ascendc_compile_kernel.py 编排)
│  npu_op_package_add → simple_kernel_compile → ascendc_compile_kernel.py
│    ├─ ascendc_gen_impl() → <OpType>.py (产物⑤: codegen Python驱动)
│    │    └─ get_dtype_fmt_options() → 注入 -DDTYPE_X=<macro>
│    ├─ ascendc_gen_param() → 枚举 dtype 组合
│    │    ├─ _param.json ×N (产物⑥: 每个dtype一份编译参数)
│    │    └─ *.sh ×N (产物⑦: asc_opc编译命令脚本)
│    ├─ ascendc_put_tiling() → 链接 tiling.so
│    └─ ascendc_build() → make 并行执行 N 个 .sh
│
Stage 4: asc_opc 编译器 (×N 并行, 每个dtype一个)
│  每个 asc_opc 执行:
│  ├─ 读取 _param.json → 确定 dtype
│  ├─ 注入宏: -DDTYPE_X=float/half/bfloat16_t
│  ├─ 检测 TPL: ASCENDC_TPL_ARGS_DECL → RANK∈{4,8}
│  ├─ 模板特化: RANK=4 → sub-kernel _0, RANK=8 → sub-kernel _1
│  └─ 编译 <op>_apt.cpp → NPU ELF 二进制
│
Stage 5: 产物输出
│  N 个 .o + .json (产物⑧: 设备二进制)
│  binary_info_config.json (产物⑨: 运行时路由表)
```

## 中间产物速查表

| 编号 | 产物 | 路径模式 | 作用 | 何时存在 |
|------|------|----------|------|----------|
| ① | `libascend_all_ops.so` | `build/autogen/` | 编译后的 host 代码，供 op_build 解析 | configure 后 |
| ② | `aic-*-ops-info.ini` | `build/autogen/` | op_build 生成的算子元信息 | configure 后 |
| ③ | `aic-*-ops-info.json` | `build/ascendc_kernels/tbe/op_info_cfg/ai_core/<soc>/` | ini 转 json，供编译器读取 | configure 后 |
| ④ | `*_source_files.ini` | `build/autogen/` | op_type → kernel 源码路径映射 | configure 后 |
| ⑤ | `<OpType>.py` | `build/ascendc_kernels/<Op>_<soc>/dynamic/` | codegen Python 编译驱动 | **仅 build 失败时**（成功后被清理） |
| ⑥ | `*_param.json` | `build/ascendc_kernels/<Op>_<soc>/bin_param/` | 每个 dtype 的编译参数 | **仅 build 失败时** |
| ⑦ | `*.sh` | `build/ascendc_kernels/<Op>_<soc>/bin_param/` | asc_opc 编译命令脚本 | **仅 build 失败时** |
| ⑧ | `*.o` + `*.json` | `build/ascendc_kernels/binary/<soc>/<op_file>/` | 设备二进制 + 元信息 | build 成功后 |
| ⑨ | `binary_info_config.json` | `build/ascendc_kernels/binary/config/<soc>/` | 运行时 dtype→.o 路由表 | build 成功后 |

## dtype → 宏注入映射

`DTYPE_X` 由 `ascendc_impl_build.py` 的 `get_dtype_fmt_options()` 注入：

| _param.json 中的 dtype | 注入的 -DDTYPE_X 值 | -DORIG_DTYPE_X 值 |
|------------------------|---------------------|---------------------|
| float32 | float | DT_FLOAT |
| float16 | half | DT_FLOAT16 |
| bfloat16 | bfloat16_t | DT_BF16 |
| int8 | int8_t | DT_INT8 |
| int32 | int32_t | DT_INT32 |
| int64 | int64_t | DT_INT64 |
| bool | bool | DT_BOOL |

脚本侧的同一份映射内联在 `scripts/inspect_build.py` 与 `scripts/trace_codegen.py` 顶部的 `DTYPE_TO_MACRO` / `DTYPE_TO_ORIG`——两个脚本各自 standalone，改一处要同步另一处与本表。

## 运行时 dispatch（两级路由）

```
运行时输入 (dtype=float32, rank=4)
    │
    ├─ 外层: dtype → 查 binary_info_config.json 的 simplifiedKey
    │  simplifiedKey: "ScaleCustom/d=0,p=1/0,2/0,2/0,2"
    │                                     ^^^^
    │                                   dtype=0(float32), format=2(ND)
    │  → 路由到 ScaleCustom_47c7...776.o
    │
    └─ 内层: tilingKey → host tiling 函数 SetTilingKey(RANK_4=4)
       → 选择 .o 内的 sub-kernel _0
```

simplifiedKey 中 dtype 枚举值速查：

- 0 = float32, 1 = float16, 27 = bfloat16
- 2 = int8, 9 = int16, 11 = int32, 13 = int64

## .o 文件名生成规则

格式：`<OpType>_<md5hash>.o`

MD5 来自 `ascendc_bin_param_build.py` 的 `gen_input_json()` 对 `_param.json` 内容取哈希：

```python
md5sum = hashlib.md5(json.dumps(param).encode('utf-8')).hexdigest()
bin_file = self.op_type + '_' + md5sum  # e.g. "ScaleCustom_47c7593b..."
```

外层的每个 dtype 组合 → 不同 `_param.json` 内容 → 不同 MD5 → 不同文件名。文件名是哈希，用同目录下的 `.json` 元信息或 `inspect_build.py` 把它解码回 dtype。

## 脚本速查表

3 个脚本各自 standalone，覆盖同一条管线的不同观测点，按场景选用：

| 脚本 | 何时用 | 输入 | 看什么 |
|---|---|---|---|
| `inspect_build.py` | 每次构建后 | `<build_dir>` | 5 Stage 产物全览；`✅ COMPLETE` / `❌ INCOMPLETE` 退出码；`.o` 数=外层 dtype 数 |
| `trace_codegen.py` | 构建失败、临时产物还在时 | `<build_dir> [--op-type X]` | codegen 现场勘查：`<OpType>.py` 驱动、`_param.json`、`.sh` 里 asc_opc 命令与 `-DDTYPE_X=` 注入值、报错行号→源码映射指南 |
| `inspect_kernel_binaries.sh` | **部署后验收** | `<kernel_install_root>`（已安装的 `vendors/.../kernel/`） | 扫已安装 `.o`，从同名 `.json` 读 dtype 与 `kernelList`，报 sub-kernel 名与总数。不依赖 `build/`，适合装包后或脱离源码树环境 |

选用规则：

- **build 后判完成** → `inspect_build.py`（构建期 `build/`）
- **build 失败定位** → `trace_codegen.py`（失败现场）
- **装包后/部署后核对** → `inspect_kernel_binaries.sh`（安装期 `vendors/`）
- 改 dtype 映射 → 同步改两个脚本的 `DTYPE_TO_MACRO`/`DTYPE_TO_ORIG` 与本表（脚本各自 standalone，无共享库）

## 调试决策树

```
build.sh 失败
    │
    ├─ 错误包含 "CMake Error"?
    │   → Stage 1: CMake 配置问题
    │   → 检查 CMakeLists.txt, ASCEND_HOME_PATH, find_package(ASC)
    │
    ├─ 错误包含 "opbuild" / "OpDef" / "proto"?
    │   → Stage 1: op_build 解析 OpDef 失败
    │   → 检查 op_host/*_def.cpp (DataType/Format/AddConfig)
    │
    ├─ 错误包含 "Kernel Compilation Error" / "Miss kernel implementation"?
    │   → Stage 3: ascendc_compile_kernel.py 编排失败
    │   → 运行: python3 scripts/trace_codegen.py build
    │   → 检查 source_files.ini 映射、tiling.so 是否存在
    │
    ├─ 错误包含 "error:" / "fatal error:" (C++ 编译错误)?
    │   → Stage 4: asc_opc 编译 kernel 失败
    │   → 运行: python3 scripts/trace_codegen.py build
    │   → 查看是哪个 _param.json (外层的哪个 dtype) 失败的
    │   → 检查 DTYPE_X 宏展开后的实际类型
    │   → 检查 ASCENDC_TPL 模板特化是否完整
    │
    ├─ 错误包含 "ASCENDC_TPL"?
    │   → 内层声明/选择问题
    │   → 检查 _struct.h: ARGS_DECL 与 SEL 条目是否匹配
    │
    └─ .o 文件数量不对?
        → 运行: python3 scripts/inspect_build.py build
        → 缺失的 .o 对应的 dtype 编译失败
```
