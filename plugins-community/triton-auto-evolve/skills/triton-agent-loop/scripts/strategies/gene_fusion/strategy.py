#!/usr/bin/env python3
# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------
"""Gene-fusion strategy.

The gene-fusion algorithm delegates the bulk of its work to the sub-agent:
- Round 1 performs B1 compute-atom decomposition + B2 fusion analysis and
  spawns parallel routes internally.
- Round 2+ evolves the gene pool internally.

This Orchestrator-side strategy is therefore thin: it only needs to propose a
baseline (global baseline for round 1, best historical round afterwards) and
classify the yield of each completed round.
"""

from pathlib import Path
from typing import Any

from ..base import (
    BaselineProposal,
    RoundDecision,
    Strategy,
    StrategyCapabilities,
)


class GeneFusionStrategy(Strategy):
    """Strategy wrapper for the gene-fusion algorithm."""

    name = "gene-fusion"
    capabilities = StrategyCapabilities(
        can_propose_direction=True,
        can_propose_baseline=True,
        can_propose_multiple_baselines=False,
        can_decide_switch_internally=False,
        can_recommend_stop=False,
        needs_persistent_state=False,
        can_select_round=False,
    )
    state_file_templates: list[str] = ["gene_pool.json", "fusion_plan.json"]

    def __init__(self, **params: Any) -> None:
        # Store algorithm parameters (max_routes, crossover_rate, etc.) for
        # potential use by the Orchestrator when building the manifest.
        self.params = params

    def select_next_round(
        self,
        round_index: list[dict[str, Any]],
        op_category: str | None,
        current_policy: str,
        context: dict[str, Any] | None = None,
    ) -> RoundDecision:
        """Choose the next gene-fusion round.

        Round 1 starts from the global baseline.  Subsequent rounds start from
        the best verified historical round.
        """
        if not round_index:
            return self._build_decision(
                "Gene-fusion Round 1: decompose compute atoms, perform "
                "automatic fusion analysis, and build the initial gene pool.",
                BaselineProposal(mode="none"),
                ["model_knowledge"],
            )

        best = self._best_historical_round(round_index)
        if best is not None:
            return self._build_decision(
                "Gene-fusion evolutionary round: evolve the gene pool "
                "from the best historical round.",
                BaselineProposal(mode="single", round_dirs=[best.get("round_dir", "")]),
                ["direction_history", "model_knowledge"],
            )

        # No successful historical round yet; fall back to global baseline.
        return self._build_decision(
            "Gene-fusion round: continue exploring from the global baseline.",
            BaselineProposal(mode="none"),
            ["model_knowledge"],
        )

    def _build_decision(
        self,
        hypothesis: str,
        baseline: BaselineProposal,
        evidence_sources: list[str],
    ) -> RoundDecision:
        """Build a gene-fusion round decision envelope."""
        return RoundDecision(
            direction="pattern: custom",
            hypothesis=hypothesis,
            round_strategy="exploration",
            analysis_policy="pattern_entry",
            evidence_sources=evidence_sources,
            baseline=baseline,
            metadata={"algorithm_params": self.params},
        )

    def _best_historical_round(
        self, round_index: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Return the highest-speedup round that passed verification."""
        best: dict[str, Any] | None = None
        best_speedup = 0.0
        for r in round_index:
            if r.get("best_speedup", 0.0) <= 0 or r.get("direction_yield") == "failed":
                continue
            speedup = float(r.get("best_speedup", 0.0))
            if best is None or speedup > best_speedup:
                best = r
                best_speedup = speedup
        return best
