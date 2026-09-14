from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.contracts import PaperFeedbackPolicyV1
from hypertrade.arc.feedback import _benchmark_series, evaluate_windows

END = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
START = END - timedelta(days=14)
MIDDLE = END - timedelta(days=7)


def build_points(prev_week_return: float, recent_week_return: float) -> list[dict]:
    """Hourly equity curve with one linear weekly return per half."""
    points = []
    equity = 100.0
    for hour in range(0, 169):
        points.append(
            {
                "timestamp": (START + timedelta(hours=hour)).isoformat(),
                "equity": equity,
            }
        )
        equity *= 1 + prev_week_return / 168
    for hour in range(1, 169):
        equity *= 1 + recent_week_return / 168
        points.append(
            {
                "timestamp": (MIDDLE + timedelta(hours=hour)).isoformat(),
                "equity": equity,
            }
        )
    return points


def build_benchmark(prev_week_return: float, recent_week_return: float) -> dict:
    return {
        "status": "observed",
        "symbol": "SOL/USDT:USDT",
        "timeframe": "1h",
        "tolerance_seconds": 3600,
        "points": build_points(prev_week_return, recent_week_return),
    }


def policy(**overrides) -> PaperFeedbackPolicyV1:
    base = {"enabled": True, "threshold_pp": 10, "benchmark_relative": True}
    base.update(overrides)
    return PaperFeedbackPolicyV1(**base)


def test_market_crash_alone_does_not_trigger_relative_degradation() -> None:
    # Strategy -15pp week over week, but its market fell -30pp: no decay.
    result = evaluate_windows(
        build_points(0.10, -0.05), END, policy(), benchmark=build_benchmark(0.10, -0.20)
    )
    assert result["degradation_basis"] == "benchmark_relative"
    assert result["triggered"] is False
    assert result["reasons"] == []
    assert float(result["relative_return_drop_pp"]) < 0


def test_underperforming_the_market_triggers_relative_reasons() -> None:
    # Strategy deteriorated 15pp week over week while its market deteriorated
    # only 5pp: relative drop = 10pp, at the threshold.
    result = evaluate_windows(
        build_points(0.10, -0.05), END, policy(), benchmark=build_benchmark(0.10, 0.05)
    )
    assert result["triggered"] is True
    assert "relative_return_drop" in result["reasons"]
    assert float(result["relative_return_drop_pp"]) == pytest.approx(10.0, abs=0.5)
    assert result["benchmark"]["status"] == "observed"


def test_drawdown_regression_vs_market_triggers() -> None:
    # Both halves flat in returns, but the strategy's recent drawdown widens
    # 15pp while the market stays smooth: relative drawdown increase fires.
    points = build_points(0.0, 0.0)
    depth = 100.0
    for index, point in enumerate(points):
        if index > len(points) - 40:
            depth *= 0.996
            point["equity"] = depth
    result = evaluate_windows(points, END, policy(), benchmark=build_benchmark(0.0, 0.0))
    assert result["triggered"] is True
    assert "relative_drawdown_increase" in result["reasons"]


def test_unavailable_benchmark_falls_back_to_absolute_with_annotation() -> None:
    result = evaluate_windows(
        build_points(0.10, -0.20),
        END,
        policy(),
        benchmark={"status": "unavailable", "symbol": "X", "timeframe": "1h"},
    )
    assert result["degradation_basis"] == "absolute"
    assert result["triggered"] is True  # absolute drop is 30pp
    assert "return_drop" in result["reasons"]
    assert result["benchmark"]["status"] == "unavailable"
    assert "relative_return_drop_pp" not in result


def test_misaligned_benchmark_falls_back_annotated() -> None:
    partial = build_benchmark(0.10, 0.05)
    partial["points"] = partial["points"][: len(partial["points"]) // 2]
    result = evaluate_windows(build_points(0.10, -0.20), END, policy(), benchmark=partial)
    assert result["degradation_basis"] == "absolute"
    assert result["benchmark"]["status"] == "benchmark_misaligned"


def test_absolute_policy_ignores_benchmark_entirely() -> None:
    result = evaluate_windows(
        build_points(0.10, -0.20),
        END,
        policy(benchmark_relative=False),
        benchmark=build_benchmark(0.5, 0.5),
    )
    assert result["degradation_basis"] == "absolute"
    assert result["triggered"] is True
    assert "relative_return_drop_pp" not in result


class FakeKlineClient:
    def __init__(self, *, fail: bool = False, rows: int = 400) -> None:
        self.fail = fail
        self.rows = rows
        self.calls: list[dict] = []

    def market_klines(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("klines down")
        candles = []
        stamp = int((END - timedelta(hours=self.rows)).timestamp() * 1000)
        for index in range(self.rows):
            candles.append(
                {"timestamp": stamp + index * 3600 * 1000, "close": 100.0 + index * 0.1}
            )
        return {"candles": candles}


def test_benchmark_series_builds_observed_points_in_iso_utc() -> None:
    client = FakeKlineClient()
    series = _benchmark_series(client, "SOL/USDT:USDT", "1H", START, END)
    assert series["status"] == "observed"
    assert series["tolerance_seconds"] == 3600
    assert client.calls[0]["timeframe"] == "1H"
    assert len(series["points"]) == 400
    parsed = datetime.fromisoformat(series["points"][0]["timestamp"])
    assert parsed.tzinfo is not None


def test_benchmark_series_reports_unavailable_and_coverage_limits() -> None:
    assert (
        _benchmark_series(FakeKlineClient(fail=True), "X", "1H", START, END)["status"]
        == "unavailable"
    )
    # A 15m series cannot span 14 days within the 1000-row page cap.
    assert (
        _benchmark_series(FakeKlineClient(), "X", "15m", START, END)["status"]
        == "insufficient_coverage"
    )
    assert (
        _benchmark_series(FakeKlineClient(), "X", "3h", START, END)["status"]
        == "unsupported_timeframe"
    )
