"""Slice 1 of the evolution handoff: the comparison referee contract.

A Champion/Challenger comparison whose numbers can come from either engine is a
comparison that can be gamed by choosing the engine after seeing the result.
These tests pin the one-directional contract: comparison conclusions cite only
BitPro-owned backtest sources; local replay stays a labelled pre-filter.
"""

from __future__ import annotations

import pytest
from hypertrade.research.comparison_caliber import (
    COMPARISON_SOURCE_PREFIX,
    LOCAL_REPLAY_ROLE,
    assert_comparison_sources,
    comparison_eligible,
)


def test_bitpro_backtest_sources_are_comparison_eligible() -> None:
    assert comparison_eligible(
        ("bitpro_mcp:backtest_get_result:450", "bitpro_mcp:strategy_create:445")
    )


def test_local_replay_sources_are_never_comparison_eligible() -> None:
    assert not comparison_eligible(("hypertrade_db:backtest_runs:bt_1",))
    assert not comparison_eligible(("prefilter:local_replay:abc",))


def test_mixed_sources_rejected_wholesale() -> None:
    """One local number inside a BitPro citation list poisons the conclusion."""
    with pytest.raises(ValueError, match="非 BitPro 来源"):
        assert_comparison_sources(
            ("bitpro_mcp:backtest_get_result:450", "hypertrade_db:market_tickers")
        )


def test_empty_citation_list_is_not_a_conclusion() -> None:
    assert not comparison_eligible([])


def test_contract_constants_are_stable() -> None:
    assert COMPARISON_SOURCE_PREFIX == "bitpro_mcp:"
    assert LOCAL_REPLAY_ROLE == "prefilter_only"
