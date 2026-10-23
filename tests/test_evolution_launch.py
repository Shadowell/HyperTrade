from datetime import UTC, date, datetime, timedelta

import pytest
from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService, research_windows_for
from hypertrade.arc.research_budget import admit, budget_status, source_cooldown_hours
from hypertrade.arc.store import (
    configure_store,
    get_controller,
    list_mission_ids,
    reset_store,
    save_mission,
)
from hypertrade.db import ArcMission, Database
from hypertrade.targets.bitpro import BITPRO_TARGET_PROFILE
from hypertrade.targets.registry import MarketTargetBinding
from test_arc_evolution import Paper, VariantPaper, prepare


@pytest.fixture
def service():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield EvolutionService(db)
    reset_store()

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


class LaunchPaper(VariantPaper):
    """Variant-capable parent whose session is old enough (or not) to launch."""

    started_at = "2026-09-04T00:00:00Z"
    trade_count = 2
    fills_enabled = True

    def paper_snapshot(self, **kwargs):
        body = super().paper_snapshot(**kwargs)
        body["session"] = {"started_at": self.started_at}
        body["trade_count"] = self.trade_count
        return body

    def strategy_trades(self, **kwargs):
        return super().strategy_trades(**kwargs) if self.fills_enabled else []


class LaunchPlainPaper(Paper):
    """A parent without bound-variant support but with an old session."""

    started_at = "2026-09-04T00:00:00Z"
    trade_count = 2

    def paper_snapshot(self, **kwargs):
        body = super().paper_snapshot(**kwargs)
        body["session"] = {"started_at": self.started_at}
        body["trade_count"] = self.trade_count
        return body


def evidence_unavailable(*args, **kwargs):
    raise RuntimeError("evidence unavailable")


def launch_service(service, monkeypatch, *, client=None, **overrides):
    service.client = client if client is not None else LaunchPaper()
    service.client.capital = 100
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows", evidence_unavailable
    )
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_observed_long_window", evidence_unavailable
    )
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate(
            {**state["config"], "paper_capital": "10000", **overrides}
        ),
        revision=state["revision"],
        actor="test",
    )
    return NOW


def mission(service, now, *, provider, trigger="degradation", instance="paper-source"):
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="cooldown probe",
            provider_name=provider,
            evolution_context={
                "source_instance_id": instance,
                "source_strategy_id": 44,
                "trigger_source": trigger,
            },
        )
    )
    result = admit(ctrl, now=now, db=service.db)
    assert result["accepted"], result
    return ctrl


def end_mission(service, ctrl, ended):
    live = get_controller(ctrl.mission_id)
    live.projection.state = "failed"
    save_mission(live)
    with service.db.session() as session:
        session.get(ArcMission, ctrl.mission_id).updated_at = ended


def test_launch_creates_research_when_evidence_is_missing(service, monkeypatch):
    now = launch_service(service, monkeypatch, launch_enabled=True)
    result = service.tick(now)
    assert result["status"] == "research_created", result
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["status"] == "opportunity"
    assert diagnostic["trigger_source"] == "launch"
    assert diagnostic["launch_evidence_gap"]
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.evolution_context["trigger_source"] == "launch"
    assert goal.evolution_context["paper_feedback"]["measurement"] == "launch_exploration"
    codes = {blocker["code"] for blocker in diagnostic["continuation"]["blockers"]}
    assert "minimum_trades" not in codes
    assert "completed_utc_window" not in codes


def test_launch_is_off_by_default(service, monkeypatch):
    now = launch_service(service, monkeypatch, launch_enabled=False)
    result = service.tick(now)
    assert result["status"] == "no_action"
    assert result["payload"]["diagnostics"][0]["status"] == "unavailable"
    assert list_mission_ids() == []


def test_parent_younger_than_launch_days_is_not_launched(service, monkeypatch):
    paper = LaunchPaper()
    paper.started_at = "2026-09-07T00:00:00Z"
    now = launch_service(service, monkeypatch, client=paper, launch_enabled=True)
    result = service.tick(now)
    assert result["status"] == "no_action"
    assert result["payload"]["diagnostics"][0]["status"] == "unavailable"
    assert list_mission_ids() == []


def test_launch_requires_bound_source_variant_policy(service, monkeypatch):
    now = launch_service(
        service, monkeypatch, client=LaunchPlainPaper(), launch_enabled=True
    )
    result = service.tick(now)
    assert result["status"] == "no_action"
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["status"] == "unavailable"
    assert "launch_requires_source_variant_policy" in diagnostic["reason"]
    assert list_mission_ids() == []


def test_launch_parent_without_fills_is_still_researched(service, monkeypatch):
    paper = LaunchPaper()
    paper.fills_enabled = False
    now = launch_service(service, monkeypatch, client=paper, launch_enabled=True)
    result = service.tick(now)
    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.evolution_context["orders"]["sample_count"] == 0


def test_launch_uses_rule_tweak_when_configured(service, monkeypatch):
    now = launch_service(
        service,
        monkeypatch,
        launch_enabled=True,
        exploration_provider="rule_tweak",
    )
    result = service.tick(now)
    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.provider_name == "rule_tweak"
    assert result["payload"]["provider_name"] == "rule_tweak"


def test_proactive_exploration_uses_rule_tweak(service, monkeypatch):
    now = prepare(service, monkeypatch)
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows",
        lambda *a, **k: {
            "triggered": False,
            "reasons": [],
            "end_at": "2026-09-12T00:00:00Z",
        },
    )
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate(
            {**state["config"], "proactive_enabled": True, "exploration_provider": "rule_tweak"}
        ),
        revision=state["revision"],
        actor="test",
    )
    result = service.tick(now)
    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.evolution_context["trigger_source"] == "proactive"
    assert goal.provider_name == "rule_tweak"


def test_degradation_keeps_the_configured_research_provider(service, monkeypatch):
    now = prepare(service, monkeypatch)
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate(
            {**state["config"], "exploration_provider": "rule_tweak"}
        ),
        revision=state["revision"],
        actor="test",
    )
    result = service.tick(now)
    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.evolution_context["trigger_source"] == "degradation"
    assert goal.provider_name == EvolutionConfig().research_provider


def test_launch_keeps_research_provider_when_exploration_is_not_rule_tweak(
    service, monkeypatch
):
    now = launch_service(
        service,
        monkeypatch,
        launch_enabled=True,
        exploration_provider="research",
    )
    result = service.tick(now)
    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.provider_name == EvolutionConfig().research_provider


def test_admit_refuses_launch_when_launch_is_disabled(service):
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="launch probe",
            evolution_context={
                "source_instance_id": "paper-source",
                "source_strategy_id": 44,
                "trigger_source": "launch",
            },
        )
    )
    result = admit(ctrl, now=NOW, db=service.db)
    assert result["accepted"] is False
    assert result["reason"] == "launch_disabled"


def test_rule_tweak_mission_uses_the_short_exploration_cooldown(service):
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    first = mission(service, NOW - timedelta(hours=10), provider="rule_tweak")
    end_mission(service, first, NOW - timedelta(hours=3))
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate(
            {**state["config"], "exploration_cooldown_hours": 2}
        ),
        revision=state["revision"],
        actor="test",
    )
    result = admit(
        ARCController(
            goal=ARCGoalV1(
                objective="next",
                provider_name="rule_tweak",
                evolution_context={
                    "source_instance_id": "paper-source",
                    "source_strategy_id": 44,
                    "trigger_source": "degradation",
                },
            )
        ),
        now=NOW,
        db=service.db,
    )
    assert result["accepted"] is True


def test_rule_tweak_mission_waits_for_the_default_cooldown(service):
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    first = mission(service, NOW - timedelta(hours=10), provider="rule_tweak")
    end_mission(service, first, NOW - timedelta(hours=3))
    result = admit(
        ARCController(
            goal=ARCGoalV1(
                objective="next",
                provider_name="rule_tweak",
                evolution_context={
                    "source_instance_id": "paper-source",
                    "source_strategy_id": 44,
                    "trigger_source": "degradation",
                },
            )
        ),
        now=NOW,
        db=service.db,
    )
    assert result["accepted"] is False
    assert result["reason"] == "source_cooldown"


def test_other_providers_keep_the_configured_cooldown(service):
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    first = mission(service, NOW - timedelta(hours=10), provider="codex")
    end_mission(service, first, NOW - timedelta(hours=3))
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate(
            {**state["config"], "exploration_cooldown_hours": 2}
        ),
        revision=state["revision"],
        actor="test",
    )
    result = admit(
        ARCController(
            goal=ARCGoalV1(
                objective="next",
                provider_name="codex",
                evolution_context={
                    "source_instance_id": "paper-source",
                    "source_strategy_id": 44,
                    "trigger_source": "degradation",
                },
            )
        ),
        now=NOW,
        db=service.db,
    )
    assert result["accepted"] is False
    assert result["reason"] == "source_cooldown"


def test_source_cooldown_hours_reads_the_latest_provider():
    config = EvolutionConfig(exploration_cooldown_hours=2)
    assert source_cooldown_hours({"last_provider": "rule_tweak"}, config) == 2
    assert source_cooldown_hours({"last_provider": "codex"}, config) == config.cooldown_hours
    assert source_cooldown_hours({}, config) == config.cooldown_hours


def test_research_windows_fit_bitpro_backtest_bounds():
    as_of = date(2026, 9, 11)
    windows = research_windows_for(120, "15m", as_of=as_of)
    assert windows.development_days == 81
    assert windows.validation_days == 60
    assert (81 * 96 + 501) * 120 <= 1_000_000

    defaults = research_windows_for(1, "1h", as_of=as_of)
    assert (defaults.development_days, defaults.validation_days) == (119, 60)

    daily = research_windows_for(1, "1D", as_of=as_of)
    assert (daily.development_days, daily.validation_days) == (119, 60)

    unknown = research_windows_for(1, "3x", as_of=as_of)
    assert (unknown.development_days, unknown.validation_days) == (119, 60)

    with pytest.raises(ValueError, match="research_window_exceeds_backtest_bounds"):
        research_windows_for(2000, "1m", as_of=as_of)


def test_default_config_keeps_degradation_research(service, monkeypatch):
    now = prepare(service, monkeypatch)
    result = service.tick(now)
    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.evolution_context["trigger_source"] == "degradation"
    assert goal.provider_name == EvolutionConfig().research_provider


def test_launch_fallback_is_limited_to_the_bitpro_transport(service, monkeypatch):
    """A non-BitPro target must surface the evidence failure instead of launching."""
    other_transport = BITPRO_TARGET_PROFILE.model_copy(update={"transport": "mcp_contract_v1"})
    monkeypatch.setattr(
        "hypertrade.arc.evolution.get_market_target",
        lambda target_id: MarketTargetBinding(profile=other_transport),
    )
    paper = LaunchPaper()
    # Enough trades to reach the evidence collector, so launch is the only fallback.
    paper.trade_count = 40
    now = launch_service(service, monkeypatch, client=paper, launch_enabled=True)
    result = service.tick(now)
    assert result["status"] == "no_action", result
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["status"] == "unavailable"
    assert "launch_evidence_gap" not in diagnostic
    assert list_mission_ids() == []


def _launch_ctrl():
    return ARCController(
        goal=ARCGoalV1(
            objective="launch probe",
            evolution_context={
                "source_instance_id": "paper-source",
                "source_strategy_id": 44,
                "trigger_source": "launch",
            },
        )
    )


def _two_finished_missions(service, *, older_provider, newer_provider):
    """The same source finished twice; the newer mission is always the last one."""
    service.configure(
        EvolutionConfig(
            enabled=True,
            launch_enabled=True,
            exploration_cooldown_hours=1,
        ),
        revision=0,
        actor="test",
    )
    older = mission(service, NOW - timedelta(hours=30), provider=older_provider)
    end_mission(service, older, NOW - timedelta(hours=27))
    newer = mission(service, NOW - timedelta(hours=3), provider=newer_provider)
    end_mission(service, newer, NOW - timedelta(hours=3))
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate(
            {**state["config"], "launch_enabled": True, "exploration_cooldown_hours": 2}
        ),
        revision=state["revision"],
        actor="test",
    )
    return EvolutionConfig.model_validate(service.status()["config"])


def test_source_cooldown_follows_the_latest_mission_provider(service):
    config = _two_finished_missions(
        service, older_provider="rule_tweak", newer_provider="deepseek"
    )
    sources = budget_status(service.db, config, NOW)["sources"]
    assert [source["last_provider"] for source in sources.values()] == ["deepseek"]
    result = admit(_launch_ctrl(), now=NOW, db=service.db)
    assert result["accepted"] is False
    assert result["reason"] == "source_cooldown"


def test_rule_tweak_short_cooldown_applies_when_it_is_the_latest_provider(service):
    config = _two_finished_missions(
        service, older_provider="deepseek", newer_provider="rule_tweak"
    )
    sources = budget_status(service.db, config, NOW)["sources"]
    assert [source["last_provider"] for source in sources.values()] == ["rule_tweak"]
    result = admit(_launch_ctrl(), now=NOW, db=service.db)
    assert result["accepted"] is True, result
