# Copyright (c) 2026 Huawei Technologies Co., Ltd. — modifications only.
# The unmodified content is derived from
# https://github.com/just-it/ascendopgenagent (commit d530e7b), which distributes
# it under the Apache License, Version 2.0. See LICENSE-APACHE in the plugin root
# for the full text of that License.

import torch
import torch.nn as nn
import torch_npu
import custom_ops_lib


def module_fn(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:
    return custom_ops_lib.layer_norm_custom(x, weight, bias, eps)


class ModelNew(nn.Module):

    def __init__(self, normalized_shape: tuple):
        """
        Initializes the LayerNorm layer parameters.

        Args:
        normalized_shape (tuple): Shape of the input tensor to be normalized.
        """
        super(ModelNew, self).__init__()
        # bf16 variant: weights and biases must match input dtype
        self.weight = nn.Parameter(torch.ones(normalized_shape, dtype=torch.bfloat16))
        self.bias = nn.Parameter(torch.zeros(normalized_shape, dtype=torch.bfloat16))

    def forward(self, x: torch.Tensor, fn=module_fn) -> torch.Tensor:
        """
        Applies Layer Normalization to the input tensor.

        Args:
        x (torch.Tensor): Input tensor of shape (*, normalized_shape).
        fn: Function to apply (defaults to module_fn)

        Returns:
        torch.Tensor: Output tensor with Layer Normalization applied, same shape as input.
        """
        return fn(x, self.weight, self.bias)
