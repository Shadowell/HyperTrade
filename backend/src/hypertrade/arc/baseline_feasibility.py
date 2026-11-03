"""Can a same-window sealed baseline of this parent be built, before a research mission is spent?

Every research mission starts by sealing the parent's own data over the research window. BitPro
answers whether it can (`baseline_backtest` in the variant policy); a parent it cannot seal fails
the same way every time. This module reads that answer, shortens the research windows to the
history a recently listed symbol really has, and remembers what has already failed so the same
parent is not tried again until something that decides the outcome has changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
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
        "history_shorter_than_required_warmup",
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
# The shortest development or validation window a candidate can still be judged on.
MIN_WINDOW_DAYS = 14


def baseline_verdict(variant_policy: Any) -> dict[str, Any] | None:
    """BitPro's `baseline_backtest` answer; absent (older BitPro, unreadable) means proceed."""
    verdict = variant_policy.get("baseline_backtest") if isinstance(variant_policy, dict) else None
    return verdict if isinstance(verdict, dict) else None


def _bars(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def policy_warmup_bars(variant_policy: Any) -> int | None:
    """Warmup bars a sealed snapshot of this parent carries, when BitPro says."""
    return _bars((baseline_verdict(variant_policy) or {}).get("warmup_policy_bars"))


def _day(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%d")


def _midnight_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _history_need(
    verdict: dict[str, Any] | None, timeframe: str
) -> tuple[int, int, date, bool] | None:
    """(listing ms, warmup bars, first day a window may start, may the snapshot be shortened).

    The youngest symbol's listing, plus the listing slack and the fewest warmup bars BitPro seals
    before the window. `warmup_min_bars` is that fewest when BitPro shortens a young symbol's
    snapshot; an older BitPro only says `warmup_policy_bars`, which it always seals in full.
    """
    if not verdict or verdict.get("supported") is False:
        return None
    listed = verdict.get("history_start_ms")
    shortened = _bars(verdict.get("warmup_min_bars"))
    bars = shortened or _bars(verdict.get("warmup_policy_bars"))
    seconds = _timeframe_seconds(timeframe)
    if not seconds or bars is None or not isinstance(listed, int) or isinstance(listed, bool):
        return None
    ready = datetime.fromtimestamp((listed + _LISTING_SLACK_MS) / 1000 + bars * seconds, UTC)
    first = ready.date()
    if ready != datetime(first.year, first.month, first.day, tzinfo=UTC):
        first += timedelta(days=1)
    return listed, bars, first, shortened is not None


def fit_windows_to_history(
    windows: ResearchWindowsV1, verdict: dict[str, Any] | None, *, timeframe: str
) -> ResearchWindowsV1:
    """Shorten the windows to the history of the parent's youngest symbol, keeping the latest days.

    The windows end where they did (the most recent days are the ones that matter for a recently
    listed symbol) and start on the first day the history allows; the usable days are split in the
    proportion of the windows being shortened, and neither goes below MIN_WINDOW_DAYS. Windows
    that already fit, and parents too young for even the shortest windows, come back unchanged:
    `infeasibility` reports the latter.
    """
    need = _history_need(verdict, timeframe)
    if need is None:
        return windows
    first_day = need[2]
    if first_day <= windows.window("development")[0]:
        return windows
    usable = (windows.as_of - first_day).days - windows.embargo_days
    if usable < 2 * MIN_WINDOW_DAYS:
        return windows
    share = windows.validation_days / (windows.development_days + windows.validation_days)
    validation = max(MIN_WINDOW_DAYS, round(usable * share))
    return ResearchWindowsV1(
        as_of=windows.as_of,
        development_days=usable - validation,
        embargo_days=windows.embargo_days,
        validation_days=validation,
    )


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
    need = _history_need(verdict, timeframe)
    if need is None:
        return None
    listed, bars, first_day, shortened = need
    if shortened:
        # BitPro seals a young symbol with the history it has and the windows follow it
        # (`fit_windows_to_history`), so what is left to ask is whether two windows still fit.
        shortest = 2 * MIN_WINDOW_DAYS + windows.embargo_days
        if (windows.as_of - first_day).days >= shortest:
            return None
        ready = first_day + timedelta(days=shortest + 1)
        return {
            "reason_code": "history_shorter_than_window",
            "message": (
                f"部分标的 {_day(listed)} 才上线，历史还不够切出开发和验证两个窗口"
                f"（预热至少 {bars} 根，两个窗口各至少 {MIN_WINDOW_DAYS} 天），"
                f"最早 {ready.isoformat()} 起可以研究"
            ),
            "history_start_ms": listed,
            "needed_start_ms": _midnight_ms(first_day),
        }
    # An older BitPro always seals the full policy warmup: the windows must start that far
    # after the listing, with the slack tolerated.
    seconds = _timeframe_seconds(timeframe) or 0
    start = windows.window("development")[0]
    needed = _midnight_ms(start) - bars * seconds * 1000
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
