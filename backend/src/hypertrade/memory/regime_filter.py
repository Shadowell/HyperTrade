"""
Market Regime Contextual Memory Filter for Autonomous Memory 3.0

Tags memories with market regime identifiers and filters/ranks memories matching
the active WorldModel market regime.
"""

from __future__ import annotations

from typing import Any


class MarketRegimeMemoryFilter:
    """
    Contextual Memory Filter prioritizing memories generated under identical market regimes.
    """

    VALID_REGIMES: set[str] = {
        "bull_trend",
        "bear_crash",
        "sideways_range",
        "high_volatility",
    }

    def __init__(self, cross_regime_penalty: float = 0.5) -> None:
        self.cross_regime_penalty = cross_regime_penalty

    def tag_memory(self, memory_item: dict[str, Any], regime: str) -> dict[str, Any]:
        valid_tag = regime if regime in self.VALID_REGIMES else "sideways_range"
        memory_item["market_regime"] = valid_tag
        return memory_item

    def filter_and_rank(
        self,
        memories: list[dict[str, Any]],
        current_regime: str,
    ) -> list[dict[str, Any]]:
        ranked = []
        for mem in memories:
            item_regime = mem.get("market_regime", "sideways_range")
            raw_score = mem.get("score", 1.0)
            if item_regime == current_regime:
                effective_score = raw_score
            else:
                effective_score = raw_score * self.cross_regime_penalty

            mem_copy = dict(mem)
            mem_copy["regime_matched"] = item_regime == current_regime
            mem_copy["effective_score"] = round(effective_score, 4)
            ranked.append(mem_copy)

        ranked.sort(key=lambda x: x["effective_score"], reverse=True)
        return ranked
