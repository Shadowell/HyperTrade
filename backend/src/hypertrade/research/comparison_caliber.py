"""Comparison referee contract for Champion/Challenger evolution.

M0 Handoff requires Champion vs Challenger comparisons that neither side can
dispute. Two engines can compute a Sharpe — HyperTrade's local replay and
BitPro's own backtest — and they will not agree to the last decimal. A
comparison whose numbers come from either engine interchangeably is a comparison
that can be gamed by choosing the engine after seeing the result.

The contract is therefore one-directional:

- Comparison conclusions (superior / not_superior) may only cite BitPro-owned
  backtest sources (``bitpro_mcp:``). BitPro owns market data, the execution
  engine and cost model, so it is the single referee.
- Local replay stays what it has always been: a cheap pre-filter, labelled
  ``prefilter_only``. Its numbers may guide search but must never appear in a
  promotion or comparison conclusion.
"""

from __future__ import annotations

from collections.abc import Iterable

COMPARISON_SOURCE_PREFIX = "bitpro_mcp:"
LOCAL_REPLAY_ROLE = "prefilter_only"


def comparison_eligible(source_refs: Iterable[str]) -> bool:
    """True when every cited source is a BitPro-owned reference."""
    refs = [str(ref) for ref in source_refs if str(ref)]
    return bool(refs) and all(ref.startswith(COMPARISON_SOURCE_PREFIX) for ref in refs)


def assert_comparison_sources(source_refs: Iterable[str]) -> None:
    """Raise when a comparison conclusion cites anything but BitPro evidence."""
    if not comparison_eligible(source_refs):
        offending = [
            str(ref)
            for ref in source_refs
            if ref and not str(ref).startswith(COMPARISON_SOURCE_PREFIX)
        ]
        raise ValueError(
            "比较结论只能引用 BitPro 自有回测证据（"
            f"{COMPARISON_SOURCE_PREFIX}*）；发现非 BitPro 来源: {offending}"
        )
