// =============================================================================
// golden_probe.cpp — Tiling UT harness 最小可编译验证器（pattern B）
//
// 覆盖范围（VERIFIED 只担保这三项，其余事实仍按对应 references 排查）：
//   1. SDK 布局与头文件存在性
//   2. 链接配方（libtiling_api.a 顺序、ABI define、库清单——编译链接通过即验证）
//   3. 平台 mock 映射（填非默认值 → PlatformAscendC 读回相等）
//   builder 链 / LogCapture / registry dlopen / run.sh 不在本探测范围。
//
// 编译（基线版本见 SKILL.md；$CANN 为 SDK 根）：
//   g++ -std=c++17 -fno-access-control -D_GLIBCXX_USE_CXX11_ABI=0 \
//     golden_probe.cpp -o golden_probe \
//     -I$CANN/x86_64-linux/include -I$CANN/x86_64-linux/pkg_inc -I$CANN/x86_64-linux/pkg_inc/base \
//     $CANN/x86_64-linux/lib64/libtiling_api.a \
//     -L$CANN/lib64 -lopp_registry -lmetadef -lplatform -lc_sec -lunified_dlog \
//     -ldl -lpthread
//   ./golden_probe   # 期望退出码 0，stdout 全部 [PASS]
//
// 注意：libtiling_api.a 必须在 libunified_dlog 之前；-lbase 不存在，不要加。
// =============================================================================

#include <cstdio>
#include <map>
#include <string>

#include "platform/platform_infos_def.h"
#include "tiling/platform/platform_ascendc.h"

// 引用出参形态（与 UT 的 SetupPlatform 同构；不按值返回，不依赖拷贝/移动语义）
static void MakePlatform(fe::PlatFormInfos &pi, uint32_t coreNum, uint64_t ubSize)
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

int main()
{
    // 1. 伪造芯片：24 AIV 核 / 253952 B UB —— 非默认值，读回必须相等
    fe::PlatFormInfos pi;
    MakePlatform(pi, 24, 253952);
    platform_ascendc::PlatformAscendC plat(&pi);

    uint32_t aiv = plat.GetCoreNumAiv();
    printf("GetCoreNumAiv = %u (expect 24)  -> %s\n", aiv, aiv == 24 ? "[PASS]" : "[FAIL]");

    uint64_t ub = 0;
    plat.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ub);
    printf("GetCoreMemSize UB = %lu (expect 253952)  -> %s\n",
           static_cast<unsigned long>(ub), ub == 253952 ? "[PASS]" : "[FAIL]");

    // 2. 换一组非默认值再读回：证明读取链路消费的是 mock 值而非宿主机残留
    fe::PlatFormInfos pi2;
    MakePlatform(pi2, 25, 999999);
    platform_ascendc::PlatformAscendC plat2(&pi2);
    uint64_t ub2 = 0;
    plat2.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ub2);
    printf("second mock: aiv=%u (expect 25) ub=%lu (expect 999999)  -> %s\n",
           plat2.GetCoreNumAiv(), static_cast<unsigned long>(ub2),
           (plat2.GetCoreNumAiv() == 25 && ub2 == 999999) ? "[PASS]" : "[FAIL]");

    return (aiv == 24 && ub == 253952 && plat2.GetCoreNumAiv() == 25 && ub2 == 999999) ? 0 : 1;
}
