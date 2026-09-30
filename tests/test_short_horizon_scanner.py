from datetime import datetime

import pytest
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.store import configure_store, get_controller, reset_store
from hypertrade.db import Database
from test_arc_evolution import Paper
from test_short_horizon import END, Ports, snapshot


@pytest.fixture
def service():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    yield EvolutionService(database)
    reset_store()


class ShortPaper(Paper):
    def paper_snapshot(self, **kwargs):
        return {**snapshot(), "strategy": {"symbols": ["SOL/USDT:USDT"]}}

    def strategy_return_series(self, **kwargs):
        return (
            Ports(self.paper_snapshot())
            .read_equity_series(
                kwargs["source_id"],
                start_ms=int(datetime.fromisoformat(kwargs["start_at"]).timestamp() * 1000),
                end_ms=int(datetime.fromisoformat(kwargs["end_at"]).timestamp() * 1000),
            )
            .raw
        )

    def strategy_get(self, **kwargs):
        result = super().strategy_get(**kwargs)
        result["strategy"]["config"]["initial_capital"] = 100
        return result

    def strategy_trades(self, **kwargs):
        rows = super().strategy_trades(**kwargs)
        rows[0]["timestamp"] = int(END.timestamp() * 1000) - 3600000
        return rows

    def strategy_research_variant_policy(self, **kwargs):
        return {
            "variant_creation_supported": True,
            "parent_strategy_id": 44,
            "parent_manifest_sha256": "a" * 64,
            "parent_execution_identity_sha256": "b" * 64,
            "authorized_parameters": [{"key": "fast_window", "min": 2, "max": 20}],
        }


def test_short_shock_creates_budgeted_research_without_waiting_for_long_window(
    service, monkeypatch
):
    service.client = ShortPaper()
    service.configure(EvolutionConfig(), revision=0, actor="test")

    def long_must_not_run(*args, **kwargs):
        raise AssertionError("short shock must not wait for fourteen days")

    monkeypatch.setattr("hypertrade.arc.evolution.collect_windows", long_must_not_run)
    result = service.tick(END)
    assert result["status"] == "research_created", result
    ctrl = get_controller(result["payload"]["mission_id"])
    context = ctrl.projection.goal.evolution_context
    assert context["paper_feedback"]["measurement"] == "short_paper_equity.v1"
    assert context["paper_feedback"]["direct_adoption_allowed"] is False
    assert ctrl.projection.goal.paper_review_required is True


def test_disabling_emergency_keeps_existing_long_gates(service):
    service.client = ShortPaper()
    service.configure(EvolutionConfig(emergency_enabled=False), revision=0, actor="test")
    result = service.tick(END)
    assert result["status"] == "no_action"


class GapPaper(ShortPaper):
    def paper_snapshot(self, **kwargs):
        return {**snapshot(age_days=20, trades=50), "strategy": {"symbols": ["SOL/USDT:USDT"]}}

    def strategy_return_series(self, **kwargs):
        from datetime import timedelta

        start = datetime.fromisoformat(kwargs["start_at"])
        end = datetime.fromisoformat(kwargs["end_at"])
        rows = []
        for i in range(int((end - start).total_seconds() / 3600) + 1):
            stamp = start + timedelta(hours=i)
            if end - start > timedelta(days=7) and 40 <= i < 47:
                continue
            rows.append(
                {
                    "timestamp": stamp.isoformat(),
                    "equity": "100" if stamp <= END - timedelta(days=7) else "80",
                }
            )
        return {
            "schema_version": "strategy_return_series.v1",
            "source_layer": "paper",
            "source_id": "paper-source",
            "strategy_id": 44,
            "strategy_version": "v1",
            "config_version": "c1",
            "currency": "USDT",
            "cost_model": {"fees": "net"},
            "bucket_seconds": 3600,
            "timezone": "UTC",
            "points": rows,
            "source_hash": "a" * 64,
            "content_hash": "b" * 64,
            "data_gaps": ["gross_return_unavailable"],
            "pagination": {"next_cursor": None},
        }


def test_bounded_long_gap_does_not_hold_the_entire_research_queue(service, monkeypatch):
    from hypertrade.arc.evolution_continuation import acceptance_entries

    service.client = GapPaper()
    service.configure(EvolutionConfig(), revision=0, actor="test")

    def strict_gap(*args, **kwargs):
        raise ValueError("duplicate_or_missing_samples")

    monkeypatch.setattr("hypertrade.arc.evolution.collect_windows", strict_gap)
    result = service.tick(END)
    assert result["status"] == "research_created", result
    ctrl = get_controller(result["payload"]["mission_id"])
    feedback = ctrl.projection.goal.evolution_context["paper_feedback"]
    assert feedback["measurement"] == "observed_weekly_returns.v1"
    assert feedback["previous"]["max_drawdown"] is None
    stage = next(
        e
        for e in acceptance_entries(ctrl.projection, END)
        if e["stage"] == "trigger_observed_7_plus_7"
    )
    assert stage["result"] == "passed"


def test_emergency_never_bypasses_source_variant_risk_envelope(service):
    class Unsupported(ShortPaper):
        def strategy_research_variant_policy(self, **kwargs):
            return {"variant_creation_supported": False}

    service.client = Unsupported()
    service.configure(EvolutionConfig(), revision=0, actor="test")
    result = service.tick(END)
    assert result["status"] == "no_action"
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["short_horizon"]["triggered"]
    blocker = next(
        b for b in diagnostic["continuation"]["blockers"] if b["code"] == "source_variant_policy"
    )
    assert blocker["resolution"] == "operator"
