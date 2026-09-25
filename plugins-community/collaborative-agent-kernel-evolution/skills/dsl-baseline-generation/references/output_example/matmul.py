# Copyright (c) 2026 Huawei Technologies Co., Ltd. — modifications only.
# The unmodified content is derived from
# https://github.com/just-it/ascendopgenagent (commit d530e7b), which distributes
# it under the Apache License, Version 2.0. See LICENSE-APACHE in the plugin root
# for the full text of that License.

import math

import tile.language as tl
import torch


@ascend_kernel
def matmul_kernel(a_ptr, b_ptr, c_ptr,
                  m, n, k,
                  block_m, block_n, k_tile, n_blocks):
    """
    Kernel computes one (block_M x block_N) tile of C per program/core.
    Assumes no tail handling (all tiles are full).
    """

    pid = tl.program_id(0)

    # tile coordinates for this program
    pid_m = pid // n_blocks
    pid_n = pid % n_blocks

    # global tile starts
    m_start = pid_m * block_m
    n_start = pid_n * block_n
    k_blocks = k // k_tile

    # -----------------------
    # Allocate L1 and L0 buffers (all declared here)
    # -----------------------
    a_l1 = tl.alloc_l1((block_m, k_tile), dtype=tl.float32)
    b_l1 = tl.alloc_l1((k_tile, block_n), dtype=tl.float32)
    c_l0 = tl.alloc_l0c((block_m, block_n), dtype=tl.float32)

    # Main K loop: load A_L1, B_L1, compute into C_L0
    for kb in range(k_blocks):

        k_start = kb * k_tile

        with tl.copyin():
            tl.load(a_ptr + (m_start * k + k_start), a_l1)
            tl.load(b_ptr + (k_start * n + n_start), b_l1)

        with tl.compute():
            tl.gemm_v0(a_l1, b_l1, c_l0, init=(kb == 0))

    with tl.copyout():
        tl.store(c_ptr + (m_start * n + n_start), c_l0)


# -----------------------
# Host: global planning + launch
# -----------------------
def matmul_host(a: torch.Tensor, b: torch.Tensor, c: torch.Tensor):
    m, k = a.shape
    k, n = b.shape

    # Core Partitioning
    # No inter-core sync required: each core writes distinct C tile
    block_m = 256
    block_n = 256

    m_blocks = m // block_m
    n_blocks = n // block_n

    n_cores = m_blocks * n_blocks

    # Tiling Strategy (Host)
    # Choose block sizes to fit your hardware L1 with safety headroom.
    k_tile = 128

    matmul_kernel[n_cores](
        a, b, c,
        m, n, k,
        block_m, block_n, k_tile, n_blocks
    )
