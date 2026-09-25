/**
 * Copyright (c) 2026 Huawei Technologies Co., Ltd. — modifications only.
 * The unmodified content is derived from
 * https://github.com/just-it/ascendopgenagent (commit d530e7b), which distributes
 * it under the Apache License, Version 2.0. See LICENSE-APACHE in the plugin root
 * for the full text of that License.
 */

#include <torch/library.h>
#include <torch/csrc/autograd/custom_function.h>
#include "pytorch_npu_helper.hpp"
#include <torch/extension.h>

at::Tensor layer_norm_custom_impl_npu(const at::Tensor& input, const at::Tensor& weight, const at::Tensor& bias, double eps) {
    // bf16 variant: input/output tensors are bfloat16
    // The kernel handles bf16↔f32 casting internally
    at::Tensor result = at::empty_like(input);  // preserves bf16 dtype
    EXEC_NPU_CMD(aclnnLayerNormCustom, input, weight, bias, eps, result);
    return result;
}

TORCH_LIBRARY_IMPL(myops, PrivateUse1, m) {
    m.impl("layer_norm_custom", &layer_norm_custom_impl_npu);
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
    m.def("layer_norm_custom", &layer_norm_custom_impl_npu, "Layer Normalization");
}