from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from hypertrade.arc.short_horizon import collect_short_horizon, verify_short_trigger

END = datetime(2026, 9, 29, 12, tzinfo=UTC)


def snapshot(age_days=4, trades=12):
    return {
        "strategy_id": 44,
        "instance_id": "paper-source",
        "strategy_version": "v1",
        "config_version": "c1",
        "status": "running",
        "trade_count": trades,
        "session": {"started_at": (END - timedelta(days=age_days)).isoformat()},
    }


class Ports:
    def __init__(self, snap, drop=0.2, missing=(), bad=None):
        self.snap, self.drop, self.missing, self.bad = snap, drop, set(missing), bad

    def get_session_snapshot(self, **kwargs):
        return SimpleNamespace(source=self.snap)

    def read_equity_series(self, instance, **kwargs):
        start = datetime.fromtimestamp(kwargs["start_ms"] / 1000, UTC)
        hours = int((END - start).total_seconds() / 3600)
        points = [
            {
                "timestamp": (start + timedelta(hours=i)).isoformat(),
                "equity": str(100 * (1 - self.drop * i / hours)),
            }
            for i in range(hours + 1)
            if i not in self.missing
        ]
        page = {
            "schema_version": "strategy_return_series.v1",
            "source_layer": "paper",
            "source_id": instance,
            "strategy_id": 44,
            "strategy_version": "v1",
            "config_version": "c1",
            "currency": "USDT",
            "cost_model": {"fees": "net"},
            "bucket_seconds": 3600,
            "timezone": "UTC",
            "points": points,
            "source_hash": "a" * 64,
            "content_hash": "b" * 64,
            "data_gaps": ["gross_return_unavailable"],
            "pagination": {"next_cursor": None},
        }
        if self.bad == "identity":
            page["config_version"] = "other"
        if self.bad == "cost":
            page["cost_model"] = {}
        if self.bad == "cursor":
            page["pagination"]["next_cursor"] = "next"
        if self.bad == "nan":
            page["points"][-1]["equity"] = "NaN"
        if self.bad == "mixed":
            page["data_gaps"] = ["historical_version_missing"]
        return SimpleNamespace(raw=page)


def test_three_day_drop_triggers_without_fourteen_days_or_thirty_trades():
    snap = snapshot()
    result = collect_short_horizon(Ports(snap), snap, END)
    assert result["triggered"] is True
    assert result["measurement"] == "short_paper_equity.v1"
    assert result["metrics"]["drawdown_pct"] == pytest.approx(20)
    assert result["direct_adoption_allowed"] is False
    assert verify_short_trigger(result)


def test_ten_trades_allow_a_younger_session_observation():
    snap = snapshot(age_days=1, trades=10)
    result = collect_short_horizon(Ports(snap), snap, END)
    assert result["triggered"]
    assert result["qualification"] == "trade_count"
    assert result["observed_hours"] == 24


def test_cold_start_still_reports_observed_shock_but_does_not_launch_research():
    snap = snapshot(age_days=1, trades=3)
    result = collect_short_horizon(Ports(snap), snap, END)
    assert result["status"] == "cold_start"
    assert result["alert"] is True
    assert result["triggered"] is False


def test_small_gaps_are_display_only_imputations_never_used_as_observations():
    snap = snapshot()
    result = collect_short_horizon(Ports(snap, missing=range(30, 36)), snap, END)
    assert result["triggered"]
    assert result["gap_hours"] == 6
    assert len(result["observed_points"]) == 67
    assert len(result["display_points"]) == 73
    assert sum(p["imputed"] for p in result["display_points"]) == 6
    assert result["metrics"]["return_pct"] == pytest.approx(-20)
    assert verify_short_trigger(result)
    result["metrics"]["return_pct"] = 20
    assert not verify_short_trigger(result)


@pytest.mark.parametrize("bad", ["identity", "cost", "cursor", "nan", "mixed"])
def test_identity_metadata_and_pagination_fail_closed(bad):
    snap = snapshot()
    result = collect_short_horizon(Ports(snap, bad=bad), snap, END)
    assert result["status"] == "unknown"
    assert not result["triggered"]


def test_large_gap_and_stale_tail_do_not_trigger():
    snap = snapshot()
    for missing in (range(20, 35), range(69, 73)):
        result = collect_short_horizon(Ports(snap, missing=missing), snap, END)
        assert not result["triggered"]
        assert result["status"] == "unknown"


def test_stable_window_is_observed_without_research_trigger():
    snap = snapshot()
    result = collect_short_horizon(Ports(snap, drop=0.01), snap, END)
    assert result["status"] == "observed"
    assert result["triggered"] is False


def test_short_receipt_has_its_own_acceptance_stage_and_readiness():
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution import EvolutionConfig
    from hypertrade.arc.evolution_continuation import acceptance_entries, readiness

    snap = snapshot(age_days=1, trades=10)
    short = collect_short_horizon(Ports(snap), snap, END)
    diagnostic = {"status": "opportunity", "window": short, "short_horizon": short}
    status = readiness(snap, diagnostic, EvolutionConfig(), END)
    assert not {"minimum_trades", "completed_utc_window"} & {b["code"] for b in status["blockers"]}
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="emergency",
            research_mode="avo",
            paper_review_required=True,
            evolution_context={"source_instance_id": snap["instance_id"], "paper_feedback": short},
        )
    )
    stages = acceptance_entries(ctrl.projection, END)
    assert next(s for s in stages if s["stage"] == "trigger_short_horizon")["result"] == "passed"
    assert not any(s["stage"] == "trigger_7_plus_7" for s in stages)


def test_zero_equity_is_an_observed_total_loss_not_missing_data():
    snap = snapshot()
    result = collect_short_horizon(Ports(snap, drop=1), snap, END)
    assert result["triggered"]
    assert result["metrics"]["drawdown_pct"] == 100


def test_long_window_small_gap_uses_real_boundaries_without_claiming_complete_drawdown():
    from hypertrade.arc.short_horizon import collect_observed_long_window, verify_long_trigger

    snap = snapshot(age_days=20, trades=30)

    class LongPorts(Ports):
        def read_equity_series(self, instance, **kwargs):
            result = super().read_equity_series(instance, **kwargs)
            start = datetime.fromtimestamp(kwargs["start_ms"] / 1000, UTC)
            for point in result.raw["points"]:
                hour = int(
                    (datetime.fromisoformat(point["timestamp"]) - start).total_seconds() / 3600
                )
                point["equity"] = "100" if hour <= 168 else "80"
            return result

    result = collect_observed_long_window(
        LongPorts(snap, missing=range(40, 47)), snap, END, threshold_pp=10
    )
    assert result["triggered"]
    assert result["measurement"] == "observed_weekly_returns.v1"
    assert result["return_drop_pp"] == "20.0"
    assert result["previous"]["max_drawdown"] is None
    assert result["gap_hours"] == 7
    assert verify_long_trigger(result)


def test_equivalent_utc_session_timestamps_keep_the_same_identity():
    snap = snapshot()

    class ZuluPorts(Ports):
        def get_session_snapshot(self, **kwargs):
            latest = {
                **self.snap,
                "session": {
                    "started_at": self.snap["session"]["started_at"].replace("+00:00", "Z")
                },
            }
            return SimpleNamespace(source=latest)

    result = collect_short_horizon(ZuluPorts(snap), snap, END)
    assert result["triggered"]
