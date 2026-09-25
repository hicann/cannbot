# Copyright (c) 2026 Huawei Technologies Co., Ltd. — modifications only.
# The unmodified content is derived from
# https://github.com/just-it/ascendopgenagent (commit d530e7b), which distributes
# it under the Apache License, Version 2.0. See LICENSE-APACHE in the plugin root
# for the full text of that License.

import torch
import torch.nn as nn
import torch.nn.functional as F


def module_fn(predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    """
    Functional implementation of Mean Squared Error loss.

    Args:
        predictions (torch.Tensor): Predicted values.
        targets (torch.Tensor): Target values.

    Returns:
        torch.Tensor: Mean squared error loss.
    """
    return torch.mean((predictions - targets) ** 2)


class Model(nn.Module):
    """
    A model that computes the Mean Squared Error loss for regression tasks.

    Parameters:
        None
    """

    def __init__(self):
        super(Model, self).__init__()

    def forward(self, predictions, targets, fn=module_fn):
        return fn(predictions, targets)


BATCH_SIZE = 128
INPUT_SHAPE = (4096, )
DIM = 1


def get_inputs():
    return [torch.rand(BATCH_SIZE, *INPUT_SHAPE), torch.rand(BATCH_SIZE, *INPUT_SHAPE)]


def get_init_inputs():
    return []
