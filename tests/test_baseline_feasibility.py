"""Unit tests for the sealed-baseline feasibility precheck and its failure memory."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from hypertrade.arc.baseline_feasibility import (
    DETERMINISTIC_BASELINE_FAILURES,
    MIN_WINDOW_DAYS,
    backoff_hours,
    baseline_failure,
    baseline_verdict,
    failure_fingerprint,
    fit_windows_to_history,
    infeasibility,
    policy_warmup_bars,
)
from hypertrade.arc.contracts import ResearchWindowsV1
from hypertrade.arc.evolution import research_windows_for

AS_OF = date(2026, 11, 1)
# 2026-11-01 - 60 validation days - 1 embargo day - 119 development days.
DEVELOPMENT_START = date(2026, 5, 5)
DAY_MS = 86_400_000


def windows() -> ResearchWindowsV1:
    return ResearchWindowsV1(as_of=AS_OF)


def ms(day: date) -> int:
    """UTC midnight of `day` in epoch milliseconds."""
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def projection(*, state: str = "failed", avo: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(state=state, avo={} if avo is None else avo)


def terminal(message: str, reasons: list[str] | None = None) -> dict:
    if reasons is None:
        reasons = ["baseline_data_snapshot_unavailable"]
    return {"terminal_execution_failure": {"reasons": reasons, "message": message}}


def context(*, policy: str = "policy-a", strategy: str = "v1", config: str = "c1") -> dict:
    return {
        "variant_policy": {"baseline_backtest": {"supported": False, "policy": policy}},
        "source_snapshot": {"strategy_version": strategy, "config_version": config},
    }


# --- baseline_verdict ---------------------------------------------------------


def test_baseline_verdict_returns_bitpro_answer_unchanged():
    verdict = {"supported": True}
    assert baseline_verdict({"baseline_backtest": verdict}) is verdict


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        "x",
        3,
        {"baseline_backtest": "x"},
        {"baseline_backtest": None},
        {"baseline_backtest": [1]},
    ],
)
def test_baseline_verdict_absent_or_unreadable_is_none(policy):
    assert baseline_verdict(policy) is None


# --- policy_warmup_bars -------------------------------------------------------


def test_policy_warmup_bars_reads_positive_int():
    assert policy_warmup_bars({"baseline_backtest": {"warmup_policy_bars": 740}}) == 740


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        {"baseline_backtest": {}},
        {"baseline_backtest": {"warmup_policy_bars": None}},
        {"baseline_backtest": {"warmup_policy_bars": 0}},
        {"baseline_backtest": {"warmup_policy_bars": -1}},
        {"baseline_backtest": {"warmup_policy_bars": True}},
        {"baseline_backtest": {"warmup_policy_bars": "740"}},
    ],
)
def test_policy_warmup_bars_rejects_unusable_values(policy):
    assert policy_warmup_bars(policy) is None


# --- infeasibility ------------------------------------------------------------


def test_infeasibility_ignores_absent_verdict():
    assert infeasibility(None, timeframe="1d", windows=windows()) is None
    assert infeasibility({}, timeframe="1d", windows=windows()) is None


def test_infeasibility_reports_unsupported_policy():
    found = infeasibility(
        {
            "supported": False,
            "reason_code": "strategy_warmup_exceeds_policy",
            "warmup_required_bars": 10001,
            "warmup_max_bars": 10000,
        },
        timeframe="1d",
        windows=windows(),
    )
    assert found is not None
    assert found["reason_code"] == "strategy_warmup_exceeds_policy"
    assert "10001" in found["message"]
    assert "10000" in found["message"]


def test_infeasibility_unsupported_without_reason_code_uses_default():
    found = infeasibility({"supported": False}, timeframe="1d", windows=windows())
    assert found is not None
    assert found["reason_code"] == "baseline_unsupported"


def test_infeasibility_reports_history_shorter_than_window():
    listed = ms(date(2025, 11, 1))
    found = infeasibility(
        {"history_start_ms": listed, "warmup_policy_bars": 500},
        timeframe="1d",
        windows=windows(),
    )
    assert found is not None
    assert found["reason_code"] == "history_shorter_than_window"
    assert found["history_start_ms"] == listed
    assert found["needed_start_ms"] == ms(date(2024, 12, 21))
    assert "2025-11-01" in found["message"]
    assert "2024-12-21" in found["message"]


def test_infeasibility_accepts_history_long_enough():
    found = infeasibility(
        {"history_start_ms": ms(date(2024, 6, 1)), "warmup_policy_bars": 500},
        timeframe="1d",
        windows=windows(),
    )
    assert found is None


@pytest.mark.parametrize(
    ("timeframe", "bar_ms", "warmup_bars", "margin_ms"),
    [
        ("1d", DAY_MS, 500, 2 * DAY_MS),
        ("1h", 3_600_000, 1000, DAY_MS),
    ],
)
def test_infeasibility_boundary_uses_listing_slack(
    timeframe: str, bar_ms: int, warmup_bars: int, margin_ms: int
):
    needed = ms(DEVELOPMENT_START) - warmup_bars * bar_ms
    # The slack in the listing timestamp is tolerated: exactly at the edge is still feasible.
    assert (
        infeasibility(
            {"history_start_ms": needed + margin_ms, "warmup_policy_bars": warmup_bars},
            timeframe=timeframe,
            windows=windows(),
        )
        is None
    )
    found = infeasibility(
        {"history_start_ms": needed + margin_ms + 1, "warmup_policy_bars": warmup_bars},
        timeframe=timeframe,
        windows=windows(),
    )
    assert found is not None
    assert found["reason_code"] == "history_shorter_than_window"
    assert found["needed_start_ms"] == needed


def test_infeasibility_skips_unknown_timeframe():
    # Without a convertible bar length nothing can be judged, however late the listing.
    assert (
        infeasibility(
            {"history_start_ms": ms(date(2026, 10, 31)), "warmup_policy_bars": 500},
            timeframe="3x",
            windows=windows(),
        )
        is None
    )


@pytest.mark.parametrize(
    "verdict",
    [
        {"history_start_ms": True, "warmup_policy_bars": 500},
        {"history_start_ms": ms(date(2025, 11, 1)), "warmup_policy_bars": True},
        {"history_start_ms": "1", "warmup_policy_bars": 500},
        {"history_start_ms": ms(date(2025, 11, 1)), "warmup_policy_bars": "1"},
        {"warmup_policy_bars": 500},
        {"history_start_ms": ms(date(2025, 11, 1))},
    ],
)
def test_infeasibility_skips_unusable_history(verdict):
    assert infeasibility(verdict, timeframe="1d", windows=windows()) is None


@pytest.mark.parametrize(
    "verdict",
    [
        {"supported": True},
        {"supported": True, "warmup_policy_bars": 500},
        {"supported": True, "history_start_ms": ms(date(2026, 10, 31))},
    ],
)
def test_infeasibility_supported_without_history_is_none(verdict):
    assert infeasibility(verdict, timeframe="1d", windows=windows()) is None


# --- failure_fingerprint ------------------------------------------------------


def test_failure_fingerprint_is_stable_16_hex():
    empty = failure_fingerprint({})
    assert failure_fingerprint({}) == empty
    assert len(empty) == 16
    assert int(empty, 16) >= 0


def test_failure_fingerprint_tracks_only_deciding_fields():
    base = failure_fingerprint(context())
    assert len(base) == 16
    assert failure_fingerprint(context()) == base
    assert failure_fingerprint(context(policy="policy-b")) != base
    assert failure_fingerprint(context(strategy="v2")) != base
    assert failure_fingerprint(context(config="c2")) != base


def test_failure_fingerprint_ignores_unrelated_keys():
    base = failure_fingerprint(context())
    unrelated = {**context(), "x": 1, "av": {"anything": True}}
    assert failure_fingerprint(unrelated) == base


def test_failure_fingerprint_treats_missing_and_null_policy_alike():
    assert failure_fingerprint({"variant_policy": None}) == failure_fingerprint({})


# --- baseline_failure ---------------------------------------------------------


@pytest.mark.parametrize("message", sorted(DETERMINISTIC_BASELINE_FAILURES))
def test_baseline_failure_returns_the_deterministic_reason(message):
    assert baseline_failure(projection(avo=terminal(message))) == message


def test_baseline_failure_ignores_a_crashed_worker():
    assert (
        baseline_failure(projection(avo=terminal("回测工作进程异常退出（code=-15），详见服务日志")))
        is None
    )


def test_baseline_failure_requires_the_baseline_reason():
    avo = terminal("incomplete_official_bar_grid", reasons=["other"])
    assert baseline_failure(projection(avo=avo)) is None


def test_baseline_failure_only_counts_a_failed_mission():
    avo = terminal("incomplete_official_bar_grid")
    assert baseline_failure(projection(state="needs_operator", avo=avo)) is None


def test_baseline_failure_without_terminal_failure():
    assert baseline_failure(projection(avo={})) is None
    assert baseline_failure(projection(avo={"terminal_execution_failure": None})) is None


# --- backoff_hours ------------------------------------------------------------


@pytest.mark.parametrize(
    ("streak", "expected"),
    [(0, 0), (-3, 0), (1, 24), (2, 48), (3, 96), (4, 168), (5, 168), (50, 168)],
)
def test_backoff_hours_doubles_to_a_week_cap(streak: int, expected: int):
    assert backoff_hours(streak) == expected


# --- research_windows_for -----------------------------------------------------


def test_research_windows_shrink_for_many_symbols():
    found = research_windows_for(120, "15m", as_of=AS_OF)
    assert found.development_days == 81
    assert found.validation_days == 60


def test_research_windows_reserve_the_bitpro_warmup():
    found = research_windows_for(120, "15m", as_of=AS_OF, warmup_bars=560)
    assert found.development_days == 80
    assert found.validation_days == 60


def test_research_windows_default_warmup_matches_none():
    assert research_windows_for(120, "15m", as_of=AS_OF, warmup_bars=None) == research_windows_for(
        120, "15m", as_of=AS_OF
    )


def test_research_windows_reject_warmup_beyond_backtest_bounds():
    with pytest.raises(ValueError, match="research_window_exceeds_backtest_bounds"):
        research_windows_for(120, "15m", as_of=AS_OF, warmup_bars=8000)


def test_research_windows_ignore_warmup_for_daily_bars():
    found = research_windows_for(1, "1d", as_of=AS_OF, warmup_bars=9000)
    assert found.development_days == 119
    assert found.validation_days == 60


# --- recently listed parents: windows follow the history --------------------------------------


def young(listed: date, *, bars: int = 30, policy: int | None = 500) -> dict:
    """BitPro's answer for a parent whose youngest symbol was listed on `listed`."""
    verdict = {"supported": True, "history_start_ms": ms(listed), "warmup_min_bars": bars}
    if policy is not None:
        verdict["warmup_policy_bars"] = policy
    return verdict


def test_windows_stay_when_the_youngest_symbol_has_enough_history():
    verdict = young(date(2026, 3, 4))  # 63 days before the development window starts
    assert fit_windows_to_history(windows(), verdict, timeframe="1d") == windows()
    assert infeasibility(verdict, timeframe="1d", windows=windows()) is None


def test_windows_shorten_to_a_symbol_listed_in_july():
    # 2026-07-30 + 1 day of listing slack + 30 bars of 12h = 2026-08-15: the first day a window
    # may start. 77 usable days split like the default 119:60 development:validation.
    verdict = young(date(2026, 7, 30))
    fitted = fit_windows_to_history(windows(), verdict, timeframe="12h")

    assert (fitted.development_days, fitted.validation_days) == (51, 26)
    assert (fitted.as_of, fitted.embargo_days) == (AS_OF, 1)
    assert fitted.window("development")[0] == date(2026, 8, 15)
    assert fitted.window("final") == (date(2026, 10, 6), AS_OF)
    assert infeasibility(verdict, timeframe="12h", windows=fitted) is None


def test_shortened_windows_never_exceed_the_ones_they_replace():
    start = ResearchWindowsV1(as_of=AS_OF, development_days=20, validation_days=20)
    verdict = young(date(2026, 9, 1))  # first day 2026-10-02, 30 days before as_of
    fitted = fit_windows_to_history(start, verdict, timeframe="1d")

    assert fitted.development_days <= 20 and fitted.validation_days <= 20
    assert fitted.development_days >= MIN_WINDOW_DAYS and fitted.validation_days >= MIN_WINDOW_DAYS


def test_the_shortest_windows_that_still_judge_a_candidate_are_the_limit():
    # first day = AS_OF - 29 days: 28 usable days after the 1-day embargo = 14 + 14.
    just_enough = young(date(2026, 9, 2))
    fitted = fit_windows_to_history(windows(), just_enough, timeframe="1d")
    assert (fitted.development_days, fitted.validation_days) == (14, 14)
    assert infeasibility(just_enough, timeframe="1d", windows=windows()) is None

    one_day_short = young(date(2026, 9, 3))
    assert fit_windows_to_history(windows(), one_day_short, timeframe="1d") == windows()
    found = infeasibility(one_day_short, timeframe="1d", windows=windows())
    assert found is not None and found["reason_code"] == "history_shorter_than_window"
    assert found["history_start_ms"] == ms(date(2026, 9, 3))
    assert found["needed_start_ms"] == ms(date(2026, 10, 4))
    assert "2026-09-03" in found["message"]
    # as_of moves up a day each day: the first research day is the one whose as_of fits.
    assert "2026-11-03" in found["message"]
    tomorrow = ResearchWindowsV1(as_of=date(2026, 11, 2))
    assert infeasibility(one_day_short, timeframe="1d", windows=tomorrow) is None


def test_a_parent_listed_yesterday_is_not_researchable_yet():
    found = infeasibility(young(AS_OF), timeframe="1h", windows=windows())
    assert found is not None
    assert "14" in found["message"] and "30" in found["message"]


def test_an_older_bitpro_that_always_seals_the_full_warmup_still_gets_later_windows():
    # No warmup_min_bars: BitPro seals all 500 bars. A gold-like symbol listed 2025-04-09 has
    # them from 2026-08-23 on; the windows start there instead of failing the baseline.
    verdict = young(date(2025, 4, 9))
    del verdict["warmup_min_bars"]
    fitted = fit_windows_to_history(windows(), verdict, timeframe="1d")

    assert fitted.window("development")[0] == date(2026, 8, 23)
    assert (fitted.development_days, fitted.validation_days) == (46, 23)
    assert infeasibility(verdict, timeframe="1d", windows=fitted) is None
    # ... and the old verdict on the unfitted windows is the one the old code gave.
    found = infeasibility(verdict, timeframe="1d", windows=windows())
    assert found is not None and found["reason_code"] == "history_shorter_than_window"


OCT_30 = ms(date(2026, 10, 30))


@pytest.mark.parametrize(
    ("verdict", "timeframe"),
    [
        (None, "1d"),
        ({}, "1d"),
        ({"supported": False, "history_start_ms": OCT_30, "warmup_min_bars": 30}, "1d"),
        ({"supported": True, "warmup_min_bars": 30}, "1d"),
        ({"supported": True, "history_start_ms": True, "warmup_min_bars": 30}, "1d"),
        ({"supported": True, "history_start_ms": OCT_30, "warmup_min_bars": 0}, "1d"),
        ({"supported": True, "history_start_ms": OCT_30, "warmup_min_bars": True}, "1d"),
        ({"supported": True, "history_start_ms": OCT_30, "warmup_min_bars": 30}, "3x"),
    ],
)
def test_nothing_is_fitted_without_a_usable_verdict_history_and_timeframe(verdict, timeframe):
    assert fit_windows_to_history(windows(), verdict, timeframe=timeframe) == windows()


def test_a_baseline_that_failed_for_too_little_history_is_a_deterministic_failure():
    assert "history_shorter_than_required_warmup" in DETERMINISTIC_BASELINE_FAILURES
