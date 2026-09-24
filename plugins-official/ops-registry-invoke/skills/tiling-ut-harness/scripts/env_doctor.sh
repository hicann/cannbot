#!/bin/bash
# =============================================================================
# env_doctor.sh — Tiling UT harness 环境自检
#
# 用途：写任何 harness 代码 / probe 之前跑一次。用 skill 记录的已验证映射
#       编译并运行 golden_probe：打印 VERIFIED = 平台 mock 映射与链接配方对当前
#       环境生效，可以直接引用（不必逆向二进制、不必写 probe 重新推导）；
#       打印 DRIFT-* = 与基线不一致，按消息指向的 reference 处理；
#       打印 ENV-UNAVAILABLE = CANN 未安装/未 source，是环境问题不是 skill 过期。
#
# 用法：bash skills/tiling-ut-harness/scripts/env_doctor.sh
# 退出码：0 = VERIFIED；1 = DRIFT 或环境不可用
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "${SCRIPT_DIR}")"

# ---- 定位 CANN（与 run.sh 同规则）----
_CANN_HOME="${ASCEND_HOME_PATH:-${ASCEND_TOOLKIT_HOME:-}}"
if [ -z "${_CANN_HOME}" ]; then
    for d in "${HOME}"/Ascend/cann-*; do
        [ -d "$d" ] && _CANN_HOME="$d" && break
    done
fi
if [ -z "${_CANN_HOME}" ]; then
    echo "ENV-UNAVAILABLE: CANN not found (set ASCEND_HOME_PATH or ASCEND_TOOLKIT_HOME)."
    echo "  This is an environment problem, not skill drift: install/source CANN first, then rerun."
    exit 1
fi
CANN="${_CANN_HOME}"
ARCH="$(uname -m)"
INC="${CANN}/${ARCH}-linux/include"
PKG_INC="${CANN}/${ARCH}-linux/pkg_inc"
LIB64="${CANN}/${ARCH}-linux/lib64"

echo "CANN_HOME : ${CANN}"
echo "BASELINE  : see SKILL.md (baseline versions are defined there; compare CANN_HOME above against it)"
for h in "${INC}/platform/platform_infos_def.h" "${INC}/tiling/platform/platform_ascendc.h" "${LIB64}/libtiling_api.a" "${LIB64}/libunified_dlog.so"; do
    if [ ! -e "$h" ]; then
        echo "DRIFT-LAYOUT: missing $h — SDK layout differs from baseline; re-derive key mapping per references/platform-mock.md 「重推导」"
        exit 1
    fi
done

# ---- 编译 + 运行 golden_probe（链接顺序等配方见 golden_probe.cpp 头注释）----
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if ! g++ -std=c++17 -fno-access-control -D_GLIBCXX_USE_CXX11_ABI=0 \
      "${SKILL_DIR}/assets/golden_probe.cpp" -o "${TMP}/golden_probe" \
      -I"${INC}" -I"${PKG_INC}" -I"${PKG_INC}/base" \
      "${LIB64}/libtiling_api.a" \
      -L"${LIB64}" -lopp_registry -lmetadef -lplatform -lc_sec -lunified_dlog \
      -ldl -lpthread 2>"${TMP}/cc.log"; then
    echo "DRIFT-LINK: golden_probe failed to build — ABI/include layout differs from baseline."
    echo "  -> Match the errors against references/compile-link.md 报错对照表 first; only if the table"
    echo "     cannot explain them, treat as baseline drift and re-derive per references/platform-mock.md."
    echo "----- compiler output (first 20 lines) -----"
    head -20 "${TMP}/cc.log"
    exit 1
fi

"${TMP}/golden_probe"
rc=$?
if [ $rc -eq 0 ]; then
    echo "VERIFIED: platform-mock mapping + link recipe hold for ${CANN}"
    echo "  -> cite references/platform-mock.md / compile-link.md directly; do NOT re-derive via nm/objdump/probe."
    echo "  -> scope note: builder chain / LogCapture / registry dlopen / run.sh are NOT covered by this probe."
    exit 0
else
    echo "DRIFT-KEYMAP: golden_probe built but platform mock returned unexpected values"
    echo "  -> re-derive key mapping per references/platform-mock.md 「重推导」, then update the skill."
    exit 1
fi
