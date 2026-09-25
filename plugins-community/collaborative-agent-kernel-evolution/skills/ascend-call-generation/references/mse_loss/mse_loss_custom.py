# Copyright (c) 2026 Huawei Technologies Co., Ltd. — modifications only.
# The unmodified content is derived from
# https://github.com/just-it/ascendopgenagent (commit d530e7b), which distributes
# it under the Apache License, Version 2.0. See LICENSE-APACHE in the plugin root
# for the full text of that License.

import torch
import torch.nn as nn
import torch_npu
import custom_ops_lib


def module_fn(predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    return custom_ops_lib.mse_loss_custom(predictions, targets)


class ModelNew(nn.Module):

    def __init__(self):
        super(ModelNew, self).__init__()

    def forward(self, predictions, targets, fn=module_fn):
        return fn(predictions, targets)
