"""Can a same-window sealed baseline of this parent be built, before a research mission is spent?

Every research mission starts by sealing the parent's own data over the research window. BitPro
answers whether it can (`baseline_backtest` in the variant policy); a parent it cannot seal fails
the same way every time. This module reads that answer, and remembers what has already failed so
the same parent is not tried again until something that decides the outcome has changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from hypertrade.arc.contracts import ResearchWindowsV1
from hypertrade.arc.feedback import _timeframe_seconds

BASELINE_FAILURE_REASON = "baseline_data_snapshot_unavailable"
# BitPro's own messages for "this parent cannot be sealed as asked": the same parent under the
# same BitPro policy fails the same way, so trying it again soon only spends a research slot.
# Anything else (a crashed worker, a busy BitPro) is not here and stays an ordinary failure.
DETERMINISTIC_BASELINE_FAILURES = frozenset(
    {
        "incomplete_official_bar_grid",
        "strategy_warmup_exceeds_policy",
        "snapshot_range_exceeds_bound",
        "snapshot_file_exceeds_bound",
        "invalid_symbol_scope",
        "duplicate_symbol",
        "unsupported_bar_timeframe",
        "invalid_utc_range",
        "invalid_official_bar",
        "unconfirmed_official_bar",
    }
)
BACKOFF_FIRST_HOURS = 24
BACKOFF_MAX_HOURS = 168
# The first candle follows the listing by a little; never call a parent short on history by less.
_LISTING_SLACK_MS = 86_400_000


def baseline_verdict(variant_policy: Any) -> dict[str, Any] | None:
    """BitPro's `baseline_backtest` answer; absent (older BitPro, unreadable) means proceed."""
    verdict = variant_policy.get("baseline_backtest") if isinstance(variant_policy, dict) else None
    return verdict if isinstance(verdict, dict) else None


def policy_warmup_bars(variant_policy: Any) -> int | None:
    """Warmup bars a sealed snapshot of this parent carries, when BitPro says."""
    bars = (baseline_verdict(variant_policy) or {}).get("warmup_policy_bars")
    return bars if isinstance(bars, int) and not isinstance(bars, bool) and bars > 0 else None


def _day(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%d")


def infeasibility(
    verdict: dict[str, Any] | None, *, timeframe: str, windows: ResearchWindowsV1
) -> dict[str, Any] | None:
    """Why a sealed baseline cannot be built for these windows, or None when nothing says so."""
    if not verdict:
        return None
    if verdict.get("supported") is False:
        return {
            "reason_code": str(verdict.get("reason_code") or "baseline_unsupported"),
            "message": (
                f"该策略自身需要 {verdict.get('warmup_required_bars')} 根预热，超过回测基准数据"
                f"上限 {verdict.get('warmup_max_bars')} 根，暂时无法做同窗回测"
            ),
        }
    listed, bars = verdict.get("history_start_ms"), verdict.get("warmup_policy_bars")
    seconds = _timeframe_seconds(timeframe)
    if (
        isinstance(listed, int)
        and isinstance(bars, int)
        and not isinstance(listed, bool)
        and not isinstance(bars, bool)
        and seconds
    ):
        start = windows.window("development")[0]
        needed = (
            int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp() * 1000)
            - bars * seconds * 1000
        )
        if listed > needed + max(2 * seconds * 1000, _LISTING_SLACK_MS):
            return {
                "reason_code": "history_shorter_than_window",
                "message": (
                    f"部分标的 {_day(listed)} 才上线，晚于研究窗口前 {bars} 根预热所需的起点"
                    f" {_day(needed)}，回测基准数据建不出来"
                ),
                "history_start_ms": listed,
                "needed_start_ms": needed,
            }
    return None


def failure_fingerprint(context: dict[str, Any]) -> str:
    """What decides whether a parent can be sealed: BitPro's policy and the parent's own version.

    A failure only counts against a parent while this is unchanged; a new BitPro policy or an
    edited parent is a new question and is asked again.
    """
    verdict = baseline_verdict(context.get("variant_policy")) or {}
    snapshot = context.get("source_snapshot") or {}
    raw = json.dumps(
        [verdict.get("policy"), snapshot.get("strategy_version"), snapshot.get("config_version")],
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def baseline_failure(projection: Any) -> str | None:
    """BitPro's reason, when a mission ended because the parent's baseline could not be sealed."""
    failure = projection.avo.get("terminal_execution_failure")
    if projection.state != "failed" or not isinstance(failure, dict):
        return None
    if BASELINE_FAILURE_REASON not in (failure.get("reasons") or []):
        return None
    message = str(failure.get("message") or "")
    return message if message in DETERMINISTIC_BASELINE_FAILURES else None


def backoff_hours(streak: int) -> int:
    """24h after the first such failure, doubling to a week; 0 when there is no streak."""
    if streak <= 0:
        return 0
    return int(min(BACKOFF_MAX_HOURS, BACKOFF_FIRST_HOURS * 2 ** (streak - 1)))
