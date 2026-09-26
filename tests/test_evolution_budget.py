from datetime import timedelta
from unittest.mock import patch

import pytest
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.store import (
    configure_store,
    get_controller,
    list_mission_ids,
    reset_runtime,
    reset_store,
    save_mission,
)
from hypertrade.db import ArcMission, Database
from test_arc_evolution import prepare


@pytest.fixture
def service():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield EvolutionService(db)
    reset_store()


def finish(service, child, when):
    child.projection.state = "failed"
    save_mission(child)
    with service.db.session() as session:
        row = session.get(ArcMission, child.mission_id)
        row.updated_at = when


def budget_at(service, when):
    with patch("hypertrade.arc.evolution.datetime") as clock:
        clock.now.return_value = when
        return service.status()["budget"]


def test_period_budget_survives_restart_and_resumes_next_utc_day(service, monkeypatch):
    now = prepare(service, monkeypatch)
    service.configure(
        EvolutionConfig(enabled=True, max_research_per_day=1), revision=1, actor="test"
    )
    first = service.tick(now)
    assert first["status"] == "research_created"
    child = get_controller(first["payload"]["mission_id"])
    finish(service, child, now)
    reset_runtime()
    restarted = EvolutionService(service.db, service.client)
    second = restarted.tick(now + timedelta(hours=1))
    assert second["payload"]["budget"]["reason"] == "period_budget_exhausted"
    assert second["payload"]["budget"]["period_used"] == 1
    assert second["payload"]["budget"]["next_run_at"] == "2026-09-13T00:00:00+00:00"
    assert restarted.tick(now + timedelta(days=1))["status"] == "research_created"
    assert len(list_mission_ids()) == 2


def test_total_budget_does_not_reset_at_period_boundary(service, monkeypatch):
    now = prepare(service, monkeypatch)
    service.configure(EvolutionConfig(enabled=True, max_research_total=1), revision=1, actor="test")
    first = service.tick(now)
    child = get_controller(first["payload"]["mission_id"])
    finish(service, child, now)
    result = service.tick(now + timedelta(days=2))
    assert result["payload"]["budget"]["reason"] == "total_budget_exhausted"
    assert result["payload"]["budget"]["total_used"] == 1
    assert result["payload"]["budget"]["next_run_at"] is None


def test_stable_paper_can_be_explored_without_claiming_degradation(service, monkeypatch):
    now = prepare(service, monkeypatch)
    service.configure(
        EvolutionConfig(enabled=True, proactive_enabled=True), revision=1, actor="test"
    )
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows",
        lambda *a, **k: {
            "triggered": False,
            "reasons": [],
            "end_at": "2026-09-12T00:00:00Z",
        },
    )
    result = service.tick(now)
    assert result["status"] == "research_created"
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.evolution_context["trigger_source"] == "proactive"
    assert goal.evolution_context["paper_feedback"]["triggered"] is False
    assert "可证伪" in goal.objective
    assert result["payload"]["budget"]["period_used"] == 1


def test_long_research_terminal_time_starts_cooldown(service, monkeypatch):
    now = prepare(service, monkeypatch)
    first = service.tick(now)
    child = get_controller(first["payload"]["mission_id"])
    finish(service, child, now + timedelta(days=3))
    result = service.tick(now + timedelta(days=3, hours=1))
    assert result["payload"]["budget"]["reason"] == "source_cooldown"
    assert result["payload"]["budget"]["next_run_at"] == "2026-09-16T12:00:00+00:00"
    assert service.tick(now + timedelta(days=4))["status"] == "research_created"


def test_pending_effect_blocks_even_if_task_is_terminal(service, monkeypatch):
    now = prepare(service, monkeypatch)
    first = service.tick(now)
    child = get_controller(first["payload"]["mission_id"])
    child.projection.avo["pending"] = {"kind": "tool", "effect": "unknown"}
    finish(service, child, now)
    result = service.tick(now + timedelta(days=3))
    assert result["payload"]["budget"]["reason"] == "source_active"
    assert result["payload"]["budget"]["active"] == 1
    assert result["payload"]["budget"]["next_run_at"] is None
    assert len(list_mission_ids()) == 1


def stop_on_budget(service, child, reason, when):
    child.apply_event("operator_needed", {"reason": reason})
    save_mission(child)
    with service.db.session() as session:
        session.get(ArcMission, child.mission_id).updated_at = when


@pytest.mark.parametrize(
    "reason",
    [
        "avo_context_budget_exhausted",
        "avo_model_budget_exhausted",
        "avo_tool_budget_exhausted",
        "avo_wall_budget_exhausted",
        "avo_provider_unavailable",
        "avo_no_candidate",
    ],
)
def test_human_mode_epoch_end_releases_slot_after_cooldown(service, monkeypatch, reason):
    # Production 2026-09-25/26: human-mode missions stopped on context budget and
    # on an unsupported provider model held the active slots and deferred every later cycle.
    now = prepare(service, monkeypatch)
    first = service.tick(now)
    child = get_controller(first["payload"]["mission_id"])
    assert child.projection.goal.paper_review_mode == "human"
    stop_on_budget(service, child, reason, now)
    assert child.projection.state == "needs_operator"
    blocked = service.tick(now + timedelta(hours=1))
    assert blocked["payload"]["budget"]["active"] == 0
    assert blocked["payload"]["budget"]["reason"] == "source_cooldown"
    assert service.tick(now + timedelta(days=1, hours=1))["status"] == "research_created"


def test_human_mode_budget_end_with_pending_effect_keeps_slot(service, monkeypatch):
    now = prepare(service, monkeypatch)
    first = service.tick(now)
    child = get_controller(first["payload"]["mission_id"])
    child.projection.avo["pending"] = {"kind": "tool", "effect": "unknown"}
    stop_on_budget(service, child, "avo_context_budget_exhausted", now)
    result = service.tick(now + timedelta(days=3))
    assert result["payload"]["budget"]["reason"] == "source_active"
    assert result["payload"]["budget"]["active"] == 1


def test_unresolved_operator_reason_keeps_slot(service, monkeypatch):
    now = prepare(service, monkeypatch)
    first = service.tick(now)
    child = get_controller(first["payload"]["mission_id"])
    stop_on_budget(service, child, "avo_invalid_tool_batch", now)
    result = service.tick(now + timedelta(days=3))
    assert result["payload"]["budget"]["reason"] == "source_active"


def test_research_provider_is_frozen_into_created_research(service, monkeypatch):
    now = prepare(service, monkeypatch)
    assert EvolutionConfig().research_provider == "codex"
    state = service.status()
    config = EvolutionConfig.model_validate(
        {**state["config"], "research_provider": "deepseek"}
    )
    service.configure(config, revision=state["revision"], actor="test")
    first = service.tick(now)
    goal = get_controller(first["payload"]["mission_id"]).projection.goal
    assert goal.provider_name == "deepseek"


def test_shared_admission_is_atomic_and_idempotent(service, monkeypatch):
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_models import EvolutionCycle
    from hypertrade.arc.research_budget import admit
    from sqlalchemy import select

    now = prepare(service, monkeypatch)
    service.configure(
        EvolutionConfig(enabled=True, max_active_research=1), revision=1, actor="test"
    )
    first = service.tick(now)
    original = get_controller(first["payload"]["mission_id"])
    replay = admit(original, now=now, db=service.db)
    assert replay["accepted"] and replay["replayed"]
    assert replay["total_used"] == 1
    other = ARCController(goal=original.projection.goal.model_copy(deep=True))
    other.projection.goal.evolution_context["source_instance_id"] = "another-paper"
    other.projection.goal.evolution_context["trigger_source"] = "degradation"
    other.projection.goal.feedback_parent = {"instance_id": "another-paper"}
    refusal = admit(other, now=now, db=service.db)
    assert refusal["reason"] == "concurrency_limit"
    assert get_controller(other.mission_id) is None
    with service.db.session() as session:
        rows = list(
            session.scalars(
                select(EvolutionCycle).where(EvolutionCycle.status == "budget_admitted")
            )
        )
        assert len(rows) == 1
        denied = session.scalar(
            select(EvolutionCycle).where(EvolutionCycle.status == "budget_denied")
        )
        assert denied.payload_json["reason"] == "concurrency_limit"


def test_concurrent_producers_never_exceed_shared_limit(service, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit

    now = prepare(service, monkeypatch)
    first = service.tick(now)
    original = get_controller(first["payload"]["mission_id"])
    finish(service, original, now)
    service.configure(
        EvolutionConfig(enabled=True, max_active_research=1), revision=1, actor="test"
    )
    barrier = Barrier(2)

    def submit(index):
        ctrl = ARCController(goal=original.projection.goal.model_copy(deep=True))
        ctrl.projection.goal.evolution_context["source_instance_id"] = f"paper-{index}"
        barrier.wait()
        return admit(ctrl, now=now + timedelta(days=1), db=service.db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [1, 2]))
    assert sum(r["accepted"] for r in results) == 1
    assert {r["reason"] for r in results} <= {None, "budget_busy", "concurrency_limit"}
    assert len(list_mission_ids()) == 2


def test_switch_and_scope_are_checked_at_atomic_admission(service, monkeypatch):
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit

    now = prepare(service, monkeypatch)
    first = service.tick(now)
    original = get_controller(first["payload"]["mission_id"])
    other = ARCController(goal=original.projection.goal.model_copy(deep=True))
    service.configure(EvolutionConfig(enabled=False), revision=1, actor="test")
    assert admit(other, now=now, db=service.db)["reason"] == "disabled"
    service.configure(EvolutionConfig(enabled=True, strategy_ids=[99]), revision=2, actor="test")
    assert admit(other, now=now, db=service.db)["reason"] == "outside_strategy_scope"
    assert len(list_mission_ids()) == 1


def test_cli_exposes_same_read_only_budget_route():
    import argparse

    from hypertrade.research_cli import add_research_parser, research_request

    parser = argparse.ArgumentParser()
    add_research_parser(parser.add_subparsers())
    assert research_request(parser.parse_args(["research", "evolution"])) == (
        "GET",
        "/api/v1/arc/evolution",
        {},
        {},
    )


@pytest.mark.parametrize("fault", ["session", "version", "cost", "coverage", "fills"])
def test_proactive_requires_source_evidence_through_real_collector(service, fault):
    from datetime import UTC, datetime

    from test_paper_feedback import PaperClient

    class Client(PaperClient):
        def paper_snapshot(self, **kwargs):
            row = super().paper_snapshot(**kwargs)
            if fault == "session":
                row["session"] = {}
            if fault == "version":
                row["strategy_version"] = None
            return row

        def strategy_return_series(self, **kwargs):
            row = super().strategy_return_series(**kwargs)
            for point in row["points"]:
                point["equity"] = "100"
            if fault == "cost":
                row["cost_model"] = {}
            if fault == "coverage":
                row["pagination"] = {"next_cursor": "not-read"}
            return row

        def strategy_trades(self, **kwargs):
            return [] if fault == "fills" else super().strategy_trades(**kwargs)

    service.client = Client()
    service.configure(
        EvolutionConfig(enabled=True, proactive_enabled=True), revision=0, actor="test"
    )
    result = service.tick(datetime(2026, 8, 15, tzinfo=UTC))
    assert result["status"] == "no_action"
    assert result["payload"]["diagnostics"][0]["status"] == "unavailable"
    assert list_mission_ids() == []


def test_degradation_has_priority_over_stable_paper_independent_of_inventory_order(
    service, monkeypatch
):
    from test_arc_evolution import Paper

    now = prepare(service, monkeypatch)
    service.configure(
        EvolutionConfig(enabled=True, proactive_enabled=True), revision=1, actor="test"
    )

    class Multi(Paper):
        def paper_strategy_performance(self, **kwargs):
            return {
                "strategies": [
                    {"strategy_id": sid, "mode": "paper", "timeframe": "1H"} for sid in [44, 45]
                ]
            }

        def paper_snapshot(self, **kwargs):
            sid = kwargs["strategy_id"]
            return {
                **super().paper_snapshot(**kwargs),
                "strategy_id": sid,
                "instance_id": f"paper-{sid}",
            }

        def strategy_trades(self, **kwargs):
            return [
                {**row, "strategy_id": kwargs["strategy_id"]}
                for row in super().strategy_trades(**kwargs)
            ]

    service.client = Multi()
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows",
        lambda client, instance, sid, *args, **kwargs: {
            "triggered": sid == "45",
            "reasons": ["return_drop"] if sid == "45" else [],
            "end_at": "2026-09-12T00:00:00Z",
        },
    )
    result = service.tick(now)
    assert result["payload"]["source_strategy_id"] == 45
    assert result["payload"]["trigger_source"] == "degradation"
    second = service.tick(now + timedelta(hours=1))
    assert second["payload"]["source_strategy_id"] == 44
    assert second["payload"]["trigger_source"] == "proactive"


def test_atomic_rollback_does_not_leave_task_or_consumed_credit(service, monkeypatch):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_models import EvolutionCycle
    from hypertrade.arc.research_budget import admit
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="bounded",
            evolution_context={
                "source_instance_id": "source",
                "source_strategy_id": 44,
                "trigger_source": "degradation",
            },
        )
    )

    def crash(session, *args):
        if any(
            isinstance(r, EvolutionCycle) and r.status == "budget_admitted"
            for r in list(session.new) + list(session.dirty)
        ):
            raise RuntimeError("crash before commit")

    event.listen(Session, "before_flush", crash)
    try:
        with pytest.raises(RuntimeError, match="crash before commit"):
            admit(ctrl, now=datetime(2026, 9, 12, tzinfo=UTC), db=service.db)
    finally:
        event.remove(Session, "before_flush", crash)
    assert get_controller(ctrl.mission_id) is None
    assert service.status()["budget"]["total_used"] == 0


def test_feedback_parent_overrides_inherited_ancestor_context(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit, source_key

    service.configure(EvolutionConfig(enabled=True, strategy_ids=[44]), revision=0, actor="test")
    goal = ARCGoalV1(
        objective="descendant",
        evolution_context={
            "source_instance_id": "ancestor",
            "source_strategy_id": 1,
            "trigger_source": "proactive",
        },
        feedback_parent={
            "instance_id": "current-paper",
            "evidence": {"strategy_id": "44"},
        },
    )
    ctrl = ARCController(goal=goal)
    receipt = admit(ctrl, now=datetime.now(UTC), db=service.db)
    assert receipt["accepted"] is True
    assert receipt["source_instance_id"] == "current-paper"
    assert receipt["trigger_source"] == "degradation"
    sources = service.status()["budget"]["sources"]
    assert source_key("bitpro", 44, "current-paper") in sources
    assert source_key("bitpro", 1, "ancestor") not in sources


def test_same_instance_on_two_targets_has_distinct_source_and_shared_usage(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit, source_key
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    now = datetime(2026, 9, 22, 8, tzinfo=UTC)
    service.configure(
        EvolutionConfig(enabled=True, max_active_research=3), revision=0, actor="test"
    )
    bitpro = ARCController(
        goal=ARCGoalV1(
            objective="bitpro",
            evolution_context={
                "source_strategy_id": 44,
                "source_instance_id": "paper-same",
                "trigger_source": "degradation",
            },
        )
    )
    assert admit(bitpro, now=now, db=service.db)["accepted"]
    service.configure(
        EvolutionConfig(enabled=True, target_id="quantlab", max_active_research=3),
        revision=1,
        actor="test",
    )
    quantlab = ARCController(
        goal=ARCGoalV1(
            objective="quantlab",
            evolution_context={
                "target_id": "quantlab",
                "source_strategy_id": "44",
                "source_instance_id": "paper-same",
                "trigger_source": "degradation",
            },
        )
    )
    second = admit(quantlab, now=now, db=service.db)
    assert second["accepted"] is True
    assert second["target_id"] == "quantlab"
    assert second["source_strategy_id"] == "44"
    budget = budget_at(service, now)
    assert budget["period_used"] == budget["total_used"] == 2
    assert budget["active"] == 2
    assert source_key("bitpro", 44, "paper-same") in budget["sources"]
    assert source_key("quantlab", "44", "paper-same") in budget["sources"]


def test_same_instance_with_different_strategy_does_not_share_cooldown(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit, source_key

    now = datetime(2026, 9, 22, 8, tzinfo=UTC)
    service.configure(
        EvolutionConfig(enabled=True, max_active_research=3), revision=0, actor="test"
    )
    for strategy_id in (44, 45):
        ctrl = ARCController(
            goal=ARCGoalV1(
                objective="distinct strategy",
                evolution_context={
                    "source_strategy_id": strategy_id,
                    "source_instance_id": "paper-same",
                    "trigger_source": "degradation",
                },
            )
        )
        assert admit(ctrl, now=now, db=service.db)["accepted"] is True
    sources = service.status()["budget"]["sources"]
    assert source_key("bitpro", 44, "paper-same") in sources
    assert source_key("bitpro", 45, "paper-same") in sources


@pytest.mark.parametrize("explicit_parent_target", [False, True])
def test_feedback_parent_uses_current_target_over_inherited_ancestor(
    service, explicit_parent_target
):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit, source_key
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    service.configure(EvolutionConfig(enabled=True, target_id="quantlab"), revision=0, actor="test")
    parent = {"instance_id": "current-paper", "evidence": {"strategy_id": "AAPL:US"}}
    if explicit_parent_target:
        parent["target_id"] = "quantlab"
        context_target = "bitpro"
    else:
        context_target = "quantlab"
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="child",
            evolution_context={
                "target_id": context_target,
                "source_instance_id": "ancestor-paper",
                "source_strategy_id": 44,
                "trigger_source": "proactive",
            },
            feedback_parent=parent,
        )
    )
    result = admit(ctrl, now=datetime(2026, 9, 22, 8, tzinfo=UTC), db=service.db)
    assert result["accepted"] is True
    assert result["target_id"] == "quantlab"
    assert result["source_strategy_id"] == "AAPL:US"
    assert (
        source_key("quantlab", "AAPL:US", "current-paper") in service.status()["budget"]["sources"]
    )


def test_target_switch_cannot_reset_global_day_limit(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    now = datetime(2026, 9, 22, 8, tzinfo=UTC)
    service.configure(
        EvolutionConfig(enabled=True, max_research_per_day=1), revision=0, actor="test"
    )
    first = ARCController(
        goal=ARCGoalV1(
            objective="first",
            evolution_context={
                "source_strategy_id": 44,
                "source_instance_id": "same",
                "trigger_source": "degradation",
            },
        )
    )
    assert admit(first, now=now, db=service.db)["accepted"]
    service.configure(
        EvolutionConfig(enabled=True, target_id="quantlab", max_research_per_day=1),
        revision=1,
        actor="test",
    )
    second = ARCController(
        goal=ARCGoalV1(
            objective="second",
            evolution_context={
                "target_id": "quantlab",
                "source_strategy_id": "AAPL:US",
                "source_instance_id": "same",
                "trigger_source": "degradation",
            },
        )
    )
    denied = admit(second, now=now, db=service.db)
    assert denied["accepted"] is False
    assert denied["reason"] == "period_budget_exhausted"
    assert denied["period_used"] == 1
    assert get_controller(second.mission_id) is None


def test_same_mission_cannot_replay_for_another_target(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    now = datetime(2026, 9, 22, 8, tzinfo=UTC)
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="first",
            evolution_context={
                "source_strategy_id": 44,
                "source_instance_id": "same",
                "trigger_source": "degradation",
            },
        )
    )
    assert admit(ctrl, now=now, db=service.db)["accepted"]
    service.configure(EvolutionConfig(enabled=True, target_id="quantlab"), revision=1, actor="test")
    ctrl.projection.goal.evolution_context.update(target_id="quantlab", source_strategy_id="44")
    replay = admit(ctrl, now=now, db=service.db)
    assert replay["accepted"] is False
    assert replay["reason"] == "mission_identity_conflict"
    assert service.status()["budget"]["total_used"] == 1


def test_legacy_receipt_without_target_remains_bitpro_after_switch(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_models import EvolutionCycle
    from hypertrade.arc.research_budget import admit, source_key
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    now = datetime(2026, 9, 22, 8, tzinfo=UTC)
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="legacy",
            evolution_context={
                "source_strategy_id": 44,
                "source_instance_id": "paper-old",
                "trigger_source": "degradation",
            },
        )
    )
    assert admit(ctrl, now=now, db=service.db)["accepted"]
    with service.db.session() as session:
        receipt = session.get(EvolutionCycle, "budget_" + ctrl.mission_id)
        receipt.payload_json = {
            key: value
            for key, value in receipt.payload_json.items()
            if key not in {"target_id", "source_strategy_id", "source_key"}
        }
    service.configure(EvolutionConfig(enabled=True, target_id="quantlab"), revision=1, actor="test")
    state = budget_at(service, now)
    assert state["total_used"] == state["period_used"] == state["active"] == 1
    assert source_key("bitpro", 44, "paper-old") in state["sources"]
    assert admit(ctrl, now=now, db=service.db)["accepted"] is True


def test_active_limit_is_shared_across_targets(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    now = datetime(2026, 9, 22, 8, tzinfo=UTC)
    service.configure(
        EvolutionConfig(enabled=True, max_active_research=1), revision=0, actor="test"
    )
    first = ARCController(
        goal=ARCGoalV1(
            objective="bitpro",
            evolution_context={
                "source_strategy_id": 44,
                "source_instance_id": "paper-same",
                "trigger_source": "degradation",
            },
        )
    )
    assert admit(first, now=now, db=service.db)["accepted"]
    service.configure(
        EvolutionConfig(enabled=True, target_id="quantlab", max_active_research=1),
        revision=1,
        actor="test",
    )
    second = ARCController(
        goal=ARCGoalV1(
            objective="quantlab",
            evolution_context={
                "target_id": "quantlab",
                "source_strategy_id": "AAPL:US",
                "source_instance_id": "paper-same",
                "trigger_source": "degradation",
            },
        )
    )
    denied = admit(second, now=now, db=service.db)
    assert denied["reason"] == "concurrency_limit"
    assert denied["active"] == 1
    assert get_controller(second.mission_id) is None


@pytest.mark.parametrize(
    ("target", "strategy", "reason"),
    [
        ("bitpro", 44.5, "invalid_strategy_id"),
        ("bitpro", True, "invalid_strategy_id"),
        ("bitpro", "-44", "invalid_strategy_id"),
        ("quantlab", 44, "invalid_strategy_id"),
        ("quantlab", " ", "invalid_strategy_id"),
        ("bad target", "AAPL", "invalid_target_id"),
    ],
)
def test_target_strategy_identity_validation_fails_closed(service, target, strategy, reason):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit
    from hypertrade.targets import build_mcp_contract_profile, register_market_target

    register_market_target(build_mcp_contract_profile("quantlab", "QuantLab"), replace=True)
    service.configure(
        EvolutionConfig(enabled=True, target_id="quantlab" if target != "bitpro" else "bitpro"),
        revision=0,
        actor="test",
    )
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="invalid",
            evolution_context={
                "target_id": target,
                "source_strategy_id": strategy,
                "source_instance_id": "paper",
                "trigger_source": "degradation",
            },
        )
    )
    result = admit(ctrl, now=datetime(2026, 9, 22, 8, tzinfo=UTC), db=service.db)
    assert result["accepted"] is False
    assert result["reason"] == reason
    assert get_controller(ctrl.mission_id) is None


def test_valid_source_from_other_target_is_rejected(service):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit

    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="wrong target",
            evolution_context={
                "target_id": "quantlab",
                "source_strategy_id": "AAPL",
                "source_instance_id": "paper",
                "trigger_source": "degradation",
            },
        )
    )
    result = admit(ctrl, now=datetime(2026, 9, 22, 8, tzinfo=UTC), db=service.db)
    assert result["reason"] == "target_mismatch"
    assert get_controller(ctrl.mission_id) is None


@pytest.mark.parametrize(
    ("admitted_at", "expected"),
    [
        ("2026-09-12T23:59:59", 1),
        ("2026-09-13T00:00:00+00:00", 0),
        ("2026-09-14T00:00:00+08:00", 0),
    ],
)
def test_replayed_period_uses_strict_utc_half_open_window(service, admitted_at, expected):
    from datetime import UTC, datetime

    from hypertrade.arc.evolution_models import EvolutionCycle

    with service.db.session() as session:
        session.add(
            EvolutionCycle(
                id="budget_future",
                status="budget_admitted",
                payload_json={
                    "mission_id": "future",
                    "source_instance_id": "future-paper",
                    "trigger_source": "proactive",
                    "admitted_at": admitted_at,
                },
            )
        )
    state = service.status()["config"]
    config = EvolutionConfig.model_validate(state)
    from hypertrade.arc.research_budget import budget_status

    result = budget_status(service.db, config, datetime(2026, 9, 12, 12, tzinfo=UTC))
    assert result["period_used"] == expected


@pytest.mark.parametrize(
    ("context", "parent", "reason"),
    [
        (
            {"source_strategy_id": 44, "trigger_source": "degradation"},
            {},
            "invalid_source_identity",
        ),
        (
            {
                "source_instance_id": "paper",
                "source_strategy_id": "not-a-number",
                "trigger_source": "degradation",
            },
            {},
            "invalid_strategy_id",
        ),
        (
            {"source_instance_id": "paper", "source_strategy_id": 0, "trigger_source": "proactive"},
            {},
            "invalid_strategy_id",
        ),
        (
            {"source_instance_id": "paper", "source_strategy_id": 44, "trigger_source": "manual"},
            {},
            "invalid_trigger_source",
        ),
        ({}, {"instance_id": "paper", "evidence": {"strategy_id": "bad"}}, "invalid_strategy_id"),
    ],
)
def test_untyped_source_identity_is_rejected_without_raising(service, context, parent, reason):
    from datetime import UTC, datetime

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit

    service.configure(
        EvolutionConfig(enabled=True, proactive_enabled=True), revision=0, actor="test"
    )
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="malformed automatic source",
            evolution_context=context,
            feedback_parent=parent,
        )
    )
    receipt = admit(ctrl, now=datetime.now(UTC), db=service.db)
    assert receipt["accepted"] is False
    assert receipt["reason"] == reason
    assert get_controller(ctrl.mission_id) is None
