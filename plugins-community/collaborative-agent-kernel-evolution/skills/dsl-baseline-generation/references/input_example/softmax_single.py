# Copyright (c) 2026 Huawei Technologies Co., Ltd. — modifications only.
# The unmodified content is derived from
# https://github.com/just-it/ascendopgenagent (commit d530e7b), which distributes
# it under the Apache License, Version 2.0. See LICENSE-APACHE in the plugin root
# for the full text of that License.

import torch
import torch.nn as nn
import torch.nn.functional as F


def module_fn(x: torch.Tensor) -> torch.Tensor:
    """
    Applies Softmax activation to the input tensor.

    Args:
        x (torch.Tensor): Input tensor of shape (batch_size, num_features).

    Returns:
        torch.Tensor: Output tensor with Softmax applied, same shape as input.
    """
    return torch.softmax(x, dim=1)


class Model(nn.Module):
    """
    Simple model that performs a Softmax activation.
    """

    def __init__(self):
        super(Model, self).__init__()

    def forward(self, x: torch.Tensor, fn=module_fn) -> torch.Tensor:
        """
        Applies Softmax activation to the input tensor.

        Args:
            x (torch.Tensor): Input tensor of shape (batch_size, num_features).

        Returns:
            torch.Tensor: Output tensor with Softmax applied, same shape as input.
        """
        return fn(x)


BATCH_SIZE = 256
DIM = 4000


def get_inputs():
    x = torch.randn(BATCH_SIZE, DIM)
    return [x]


def get_init_inputs():
    return []  # No special initialization inputs needed
