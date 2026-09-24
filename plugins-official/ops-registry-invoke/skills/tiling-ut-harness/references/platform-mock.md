# 平台伪造（fe::PlatFormInfos mock）

TilingFunc 内部通过 `platform_ascendc::PlatformAscendC` 读芯片参数，后者从 `fe::PlatFormInfos` 取值。UT 的工作是往 `PlatFormInfos` 里塞键值对，让 `GetCoreNumAiv()` / `GetCoreMemSize(UB, ...)` 读到 UT 想给的数。

## 头文件与类型

```cpp
#include "platform/platform_infos_def.h"      // fe::PlatFormInfos（注意 PlatFormInfos 的非常规大写 F/I）
#include "tiling/platform/platform_ascendc.h" // platform_ascendc::PlatformAscendC, CoreMemType
```

## 已验证的 key 映射（基线版本以 SKILL.md 为准）

**先跑 `scripts/env_doctor.sh`，打印 `VERIFIED` 才允许直接引用本表。**

| 要读的值 | 塞法（SetPlatformRes 的 label → map） |
|---|---|
| 核数 `GetCoreNum()/GetCoreNumAic()/GetCoreNumAiv()` | `SoCInfo` → `{"ai_core_cnt": "<N>"}`。**能力边界**：基线上 AIC/AIV 读同一 key，无法分别 mock——需要区分 Cube/Vector 核数的算子，映射需按「重推导」节重新确认 |
| UB 大小 `GetCoreMemSize(CoreMemType::UB, ub)` | `AICoreSpec` → `{"ub_size": "<bytes>"}` |
| UB block（如 tiling 公式需要） | `AICoreSpec` → `{"ubblock_size": "32"}`（32 = 该基线 CANN 的编译期 Ops::Base 常量，随版本核对） |
| SocVersion / NpuArch / LibApiWorkSpaceSize | `version` → `{"version": "Ascend950", "NpuArch": "3510"}`；读取 API：`GetSocVersion()`（返回枚举，printf 用 `(int)` 强转）、`GetCurNpuArch()`（返回 NpuArch 类型，接受 `"3510"` 形式塞入；printf 用 `(int)` 强转）、`GetLibApiWorkSpaceSize()`（无参，返回 uint32_t；mock 未喂对应值时返回 4294967295/-1，属正常现象非错误） |
| 本地内存直读 | `pi.GetLocalMemSize(fe::LocalMemType::UB, sz)`（注意类型是 `fe::LocalMemType` 而非 platform_ascendc 的 CoreMemType）——与 `GetCoreMemSize` 走不同读取路径，mock 值喂对时两者一致 |
| 直连 API（不走 SetPlatformRes） | `pi.SetCoreNum(N); pi.SetCoreNumByCoreType("AICore");` **与 SetPlatformRes 二选一，勿混用**（两者的覆盖关系未验证，混用后读数不可预期） |

调用顺序：先 `pi.Init()`，再 SetPlatformRes / SetCoreNum，再构造 `PlatformAscendC plat(&pi)`。

## 反事实（这些填法读回 0，不要再用）

label 与 key 交叉错位、或用了不存在的 label，`Get*` 一律读回 0（静默失败，不报错）：

- key 名对但 label 错：如 `SoCInfo.ub_size`（ub_size 属于 `AICoreSpec`）、`AICoreSpec.vector_core_cnt`（vector 核数在 `SoCInfo` 里叫 `ai_core_cnt`）
- 整个 label 不存在：`core.*`、`memory.*`（但 `GetPlatformRes("SoCInfo", "ub_size", v)` 仍能读回 SetPlatformRes 塞入的原值——查询接口与消费接口路径不同，别用它判断 mock 是否生效，回读判定以 PlatformAscendC 的 Get* 为准）

头文件不区分上述正误——正误只能靠回读验证（golden_probe 的事）或逆向二进制（重推导节的事）。

## 逐 case mock 纪律

每个 TEST_F 内构造独立 PlatFormInfos，且**在 Invoke 内用 PlatformAscendC 把关键平台值回读一遍并 ASSERT 等于 case 输入**——保证 oracle 和被测实现看到同一组平台数。默认 case 用非默认值（如 24 核 / 253952 B），另设一个改核数/UB 的 case 钉死"公式确实消费平台值"。

## 重推导（env_doctor 打印 DRIFT 时，例如 CANN 版本变化）

事实只存在于二进制里，按以下顺序重查：

```bash
C=$CANN/x86_64-linux
# 1) 哪个库导出目标函数
for l in $C/lib64/*.so; do nm -D "$l" 2>/dev/null | grep -qw GetCoreNumAiv && echo "$l"; done
# 2) 库内字符串常量段找候选 key 名
strings $C/lib64/libplatform.so | grep -iE "core_num|core_cnt|vector" 
strings $C/lib64/libaihac_codegen.so | grep -iE "SoCInfo|ub_size|GetPlatformRes"
# 3) 找引用该函数的静态库对象，反汇编看它读哪个 key
ar x $C/lib64/libtiling_api.a platform_ascendc.cpp.o
objdump -dC platform_ascendc.cpp.o | grep -A30 "<GetCoreNumAiv"
objdump -s -j .rodata platform_ascendc.cpp.o | head   # 字符串表里找 key 名
# 4) 每个候选：写最小程序塞入 → 回读 → 相等才算确认（参照 assets/golden_probe.cpp）
```

推导出的新映射写进 UT 文件头注释（PLATFORM MOCK 节），并同步回本 skill。
