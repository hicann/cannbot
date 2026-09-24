#!/bin/bash
# =============================================================================
# inspect_kernel_binaries.sh
#
# Scan installed kernel .o binaries and report .o count + per-.o sub-kernel count.
#
# Usage:  ./inspect_kernel_binaries.sh <kernel_install_root>
# Example: ./inspect_kernel_binaries.sh \
#   /home/developer/Ascend/cann-9.1.0/opp/vendors/EuclideanNorm/op_impl/ai_core/tbe/kernel
# =============================================================================
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <kernel_install_root>"
    exit 1
fi

ROOT="$1"
if [ ! -d "$ROOT" ]; then
    echo "ERROR: directory not found: $ROOT"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required but not installed"
    exit 1
fi

mapfile -t O_FILES < <(find "$ROOT" -name '*.o' ! -path '*_CPack_Packages*' | sort)

if [ ${#O_FILES[@]} -eq 0 ]; then
    echo "ERROR: no .o files found under: $ROOT"
    exit 1
fi

echo "======================================================================"
echo "  Kernel Binary Inspector"
echo "======================================================================"
echo "  Root: $ROOT"
echo "  .o files found: ${#O_FILES[@]}"
echo

TOTAL_SUB=0
for o in "${O_FILES[@]}"; do
    json="${o%.o}.json"
    name=$(basename "$o")
    rel=${o#"$ROOT/"}

    if [ ! -f "$json" ]; then
        echo "  $name"
        echo "    path:         $rel"
        echo "    WARNING: sibling .json not found"
        echo "    sub-kernels:  0"
        echo
        continue
    fi

    dtype=$(jq -r '.supportInfo.inputs[0].dtype // "?"' "$json")
    sub_count=$(jq '.kernelList | length' "$json")
    sub_names=$(jq -r '.kernelList[] | "      - " + .kernelName' "$json")

    TOTAL_SUB=$((TOTAL_SUB + sub_count))

    echo "  $name"
    echo "    path:         $rel"
    echo "    dtype:        $dtype"
    echo "    sub-kernels:  $sub_count"
    if [ -n "$sub_names" ]; then
        echo "$sub_names"
    fi
    echo
done

echo "======================================================================"
echo "  SUMMARY"
echo "======================================================================"
echo "  .o files:          ${#O_FILES[@]}"
echo "  Total sub-kernels: $TOTAL_SUB"
