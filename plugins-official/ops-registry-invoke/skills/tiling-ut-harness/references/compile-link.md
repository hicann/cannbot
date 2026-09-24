# 编译与链接配方

宿主机 UT/probe 的链接难点不在"哪个库"，在"什么 ABI、什么顺序、什么形式"。本文件配方以基线版本验证（见 SKILL.md）；DRIFT 时按报错表的原理逐条重核。

## 通用编译 flags（每次都要）

```bash
-std=c++17
-fno-access-control              # TilingFunc/注册表内部符号的访问性（基线验证必须）
-D_GLIBCXX_USE_CXX11_ABI=0       # CANN 9.2.0 用旧 C++ ABI；漏掉必然 undefined reference to fe::PlatFormInfos::*
```

include 三件套（顺序无关，缺一不可）：

```bash
-I$CANN/x86_64-linux/include
-I$CANN/x86_64-linux/pkg_inc
-I$CANN/x86_64-linux/pkg_inc/base
```

（`platform_infos_def.h` 在 include/，`exe_graph/runtime/*`、`base/context_builder/*` 在 pkg_inc/ 及 pkg_inc/base/。）

## 链接库清单与顺序

**libtiling_api.a 必须写在 libunified_dlog.so 之前**（静态库对象引用 CheckLogLevel 符号，动态库必须在它之后进命令行满足解析；顺序颠倒报 `DSO missing from command line`）。

probe / UT 直链（单命令形式）：

```bash
g++ -fno-access-control -D_GLIBCXX_USE_CXX11_ABI=0 ut.cpp -o ut \
  -I...（include 三件套） \
  $CANN/lib64/libtiling_api.a \
  -L$CANN/lib64 \
  -lopp_registry -lmetadef -lplatform -lc_sec -lunified_dlog \
  -ldl -lpthread
```

CMake 等价形式（UT 可执行 target）：

```cmake
target_link_directories(${UT_EXE} PRIVATE ${CANN_LIB})
target_link_libraries(${UT_EXE} PRIVATE
    gtest_oldabi
    ${CANN_LIB}/libopp_registry.so
    ${CANN_LIB}/libmetadef.so
    ${CANN_LIB}/libplatform.so
    ${CANN_LIB}/libc_sec.so
    ${CANN_LIB}/libunified_dlog.so
    ${CANN_LIB}/libtiling_api.a
    dl
    pthread
)
```

注意 `-lbase` **不存在**（`cannot find -lbase` 时删掉它，任何文档让你加都是错的）。

## 编译/链接报错对照表

| 报错串 | 原因 | 修法 |
|---|---|---|
| `undefined reference to fe::PlatFormInfos::SetPlatformRes` 等 fe:: 符号 | 漏 `-D_GLIBCXX_USE_CXX11_ABI=0`，C++ ABI 不匹配 | 加上该 define |
| `undefined reference to symbol 'CheckLogLevel'` + `libunified_dlog.so: error adding symbols: DSO missing from command line` | libtiling_api.a 在 libunified_dlog 之后 | libtiling_api.a 提到最前（见上方清单） |
| `cannot find -lbase` | 该库不存在 | 从链接行删除 |
| `'class platform_ascendc::PlatformAscendC' has no member named 'GetUbBlockSize'` | 该 API 在此 CANN 不存在（名字像但不对） | 用 `GetCoreMemSize(CoreMemType::UB, ub)`；不确定的 API 先 grep 头文件确认存在再调用 |
| `cannot bind non-const lvalue reference ... std::map ... rvalue` | SetPlatformRes 形参是非 const 左值引用 | 先建具名 map 变量再传入，不写临时对象 |
| distro 预编译 libgtest.a 链接后大量 gtest 符号 undefined / 行为异常 | 系统库是新 ABI，与 CANN 旧 ABI 冲突 | 从源码自建 gtest_oldabi（下一节） |

## gtest_oldabi（UT 必备 target）

```cmake
set(GTEST_SRC_DIR /usr/src/googletest/googletest)
add_library(gtest_oldabi STATIC ${GTEST_SRC_DIR}/src/gtest-all.cc)
target_include_directories(gtest_oldabi PUBLIC ${GTEST_SRC_DIR}/include PRIVATE ${GTEST_SRC_DIR})
target_compile_definitions(gtest_oldabi PRIVATE _GLIBCXX_USE_CXX11_ABI=0)
```

UT 主 target 链 `gtest_oldabi`，永远不链系统 gtest。单命令行编译 probe 时等价写法：

```bash
g++ ... probe.cpp /usr/src/googletest/googletest/src/gtest-all.cc \
  -I/usr/src/googletest/googletest/include -I/usr/src/googletest/googletest ...
```

## RPATH

UT 运行时 dlopen 已安装包的 op_host .so，链接期把 .so 所在目录和 CANN lib64 都写进 RPATH：

```cmake
set_target_properties(${UT_EXE} PROPERTIES
    INSTALL_RPATH "$ORIGIN;${OP_HOST_SO_DIR};${CANN_LIB}"
    BUILD_WITH_INSTALL_RPATH TRUE)
```

## 常用 include 的实际位置

| 头 | 路径（相对 $CANN/x86_64-linux） |
|---|---|
| platform_infos_def.h | include/platform/（fe::PlatFormInfos、SetPlatformRes、GetLocalMemSize） |
| platform_ascendc.h | include/tiling/platform/（部分版本在 asc/include/，sed 前先定位；PlatformAscendC、GetCoreNum*、GetCoreMemSize、CoreMemType） |
| tiling_context.h / tiling_data.h / tensor.h | pkg_inc/exe_graph/runtime/（TilingContext 读写接口、TilingData::CreateCap、Tensor、ContinuousVector） |
| op_tiling_context_builder.h | pkg_inc/base/base/context_builder/（builder 全链） |
| op_common/log/log.h | include/op_common/log/（1000+ 行宏定义；OP_LOGE 展开逻辑约在 990-1120 行，涉及 `ASCEND_SLOG_PRINT_TO_STDOUT` 行为的读这段） |
| err_msg.h | include/（错误码宏与 GRAPH_FAILED 等返回值的错误串来源） |
| registry/op_def_registry.h | pkg_inc/（IMPL_OP_OPTILING 注册宏） |

啃头文件用 `sed -n 'START,ENDp'` 读片段（单文件上千行，整读浪费 ctx）；同一个头第二次还要啃时，说明该 API 事实应沉淀进本 skill 而不是再读一遍。
