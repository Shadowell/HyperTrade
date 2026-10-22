import pytest
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.db import Database


@pytest.fixture
def service():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield EvolutionService(db)
    reset_store()


def test_defaults_are_hourly_and_enabled(service):
    state = service.status()
    assert state["config"]["enabled"] is True
    assert state["config"]["target_id"] == "bitpro"
    # The scan calls status() repeatedly; the ledger aggregate belongs to the page only.
    assert "forward_outcomes" not in state
    assert state["config"]["interval_minutes"] == 60
    assert state["config"]["threshold_pp"] == "10"
    service.configure(EvolutionConfig(enabled=False), revision=0, actor="test")
    assert service.tick()["status"] == "disabled"


def test_config_uses_revision_and_rejects_stale_updates(service):
    state = service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    assert state["revision"] == 1
    with pytest.raises(ValueError):
        service.configure(EvolutionConfig(enabled=False), revision=0, actor="test")


def test_configure_rejects_unregistered_market_target(service):
    with pytest.raises(ValueError):
        service.configure(EvolutionConfig(target_id="not-a-target"), revision=0, actor="test")


def test_tick_builds_client_from_configured_market_target(service, monkeypatch):
    from datetime import UTC, datetime

    from hypertrade.targets import (
        build_mcp_contract_profile,
        register_market_target,
        reset_market_targets,
    )

    reset_market_targets()
    fake = Paper()
    register_market_target(build_mcp_contract_profile("fake", "Fake Target"), lambda: fake)
    try:
        service.client = None
        service.configure(EvolutionConfig(enabled=True, target_id="fake"), revision=0, actor="test")
        monkeypatch.setattr(
            "hypertrade.arc.evolution.collect_windows",
            lambda *a, **k: {
                "triggered": True,
                "reasons": ["return_drop"],
                "end_at": "2026-09-12T00:00:00Z",
            },
        )
        result = service.tick(datetime(2026, 9, 12, 12, tzinfo=UTC))
        assert result["status"] == "deferred_target_write_port"
        assert result["payload"]["skip_reason"] == "target_paper_write_port_not_migrated"
        assert service.client is fake
    finally:
        reset_market_targets()


def test_preview_queues_without_creating_research(service):
    cycle = service.queue_preview()
    assert cycle["status"] == "queued"
    assert cycle["payload"]["preview"] is True
    # Preview never changes the persisted switch state.
    assert service.status()["config"]["enabled"] is True


class Paper:
    def paper_strategy_performance(self, **kwargs):
        return {
            "strategies": [
                {"strategy_id": 44, "strategy_name": "source", "mode": "paper", "timeframe": "1H"}
            ]
        }

    def paper_snapshot(self, **kwargs):
        return {
            "strategy_id": 44,
            "instance_id": "paper-source",
            "strategy_version": "v1",
            "config_version": "c1",
            "status": "running",
            "trade_count": 60,
            "strategy": {"symbols": ["SOL/USDT:USDT"]},
            "session": {"started_at": "2026-01-01T00:00:00Z"},
        }

    def strategy_get(self, **kwargs):
        return {
            "strategy": {
                "id": kwargs["strategy_id"],
                "script_content": "class Source: pass",
                "config": {"timeframe": "1H"},
            }
        }

    def strategy_trades(self, **kwargs):
        return [
            {
                "id": 1,
                "strategy_id": 44,
                "timestamp": 1789171200000,
                "symbol": "SOL/USDT:USDT",
                "fee": 1,
                "pnl": -2,
            }
        ]


def prepare(service, monkeypatch):
    from datetime import UTC, datetime

    service.client = Paper()
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows",
        lambda *a, **k: {
            "triggered": True,
            "reasons": ["return_drop"],
            "end_at": "2026-09-12T00:00:00Z",
        },
    )
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    return datetime(2026, 9, 12, 12, tzinfo=UTC)


def test_schedule_creates_source_bound_research_once_per_hour(service, monkeypatch):
    from hypertrade.arc.store import get_controller, list_mission_ids

    now = prepare(service, monkeypatch)
    first = service.tick(now)
    assert first["status"] == "research_created", first
    child = get_controller(first["payload"]["mission_id"])
    assert child.projection.goal.symbols == ["SOL-USDT-SWAP"]
    context = child.projection.goal.evolution_context
    assert context["source_instance_id"] == "paper-source"
    assert context["orders"]["sample_count"] == 1
    report = context["attribution_report"]
    assert report == first["payload"]["diagnostics"][0]["attribution_report"]
    assert report["schema_version"] == "paper_attribution.v1"
    assert all(d["state"] == "unknown" for d in report["dimensions"].values())
    assert child.projection.goal.paper_authorization is None
    assert child.projection.goal.paper_review_required
    assert service.tick(now)["status"] == "idle"
    assert len(list_mission_ids()) == 1


def test_preview_never_creates_research(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    service.configure(EvolutionConfig(enabled=False), revision=1, actor="test")
    service.queue_preview()
    assert service.tick(now)["status"] == "preview_complete"
    assert list_mission_ids() == []


def test_switch_off_during_diagnostics_prevents_creation(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    original = service.client.strategy_get

    def toggle(**kwargs):
        service.configure(EvolutionConfig(enabled=False), revision=1, actor="test")
        return original(**kwargs)

    service.client.strategy_get = toggle
    assert service.tick(now)["status"] == "cancelled_by_config"
    assert list_mission_ids() == []


def test_missing_paper_identity_does_not_launch_research(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    service.client.paper_snapshot = lambda **kwargs: {"status": "error"}
    result = service.tick(now)
    assert result["status"] == "no_action"
    assert result["payload"]["diagnostics"][0]["status"] == "unavailable"
    assert list_mission_ids() == []


def test_inventory_unavailable_respects_configured_strategy_scope(service):
    from datetime import UTC, datetime

    paper = Paper()
    paper.paper_strategy_performance = lambda **kwargs: {
        "strategies": [],
        "unavailable_strategies": [
            {"strategy_id": sid, "reason": "dashboard unavailable"} for sid in (480, 511)
        ],
    }
    service.client = paper
    diagnostics, chosen = service._scan(
        EvolutionConfig(strategy_ids=[511]), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert chosen is None
    assert [row["strategy_id"] for row in diagnostics] == [511]
    row = diagnostics[0]
    assert row["data_readiness"]["sampling"]["reason_code"] == "recent_read_unavailable"
    assert "稍后重试" in row["data_readiness"]["next_action"]
    assert {b["code"] for b in row["continuation"]["blockers"]} == {"evidence_recheck"}


@pytest.mark.parametrize("bad_id", ["", "not-an-id", "0", "-1"])
@pytest.mark.parametrize("strategy_ids", [[], [511]])
def test_invalid_inventory_id_is_unattributed_coverage_gap(service, bad_id, strategy_ids):
    from datetime import UTC, datetime

    paper = Paper()
    paper.paper_strategy_performance = lambda **kwargs: {
        "strategies": [],
        "unavailable_strategies": [
            {"strategy_id": bad_id, "reason": "inventory_missing_strategy_id"},
            {"strategy_id": 511, "reason": "dashboard unavailable"},
        ],
    }
    service.client = paper
    diagnostics, chosen = service._scan(
        EvolutionConfig(strategy_ids=strategy_ids), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert chosen is None
    assert [row["strategy_id"] for row in diagnostics if row.get("strategy_id")] == [511]
    gaps = [row for row in diagnostics if row["status"] == "partial_coverage"]
    assert len(gaps) == 1
    assert "strategy_id" not in gaps[0]
    assert "身份" in gaps[0]["reason"]


def test_snapshot_read_failure_does_not_claim_session_fields_missing(service):
    from datetime import UTC, datetime

    paper = Paper()

    def unavailable(**kwargs):
        raise RuntimeError("temporary upstream failure")

    paper.paper_snapshot = unavailable
    service.client = paper
    diagnostics, chosen = service._scan(
        EvolutionConfig(strategy_ids=[44]), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert chosen is None
    row = diagnostics[0]
    assert row["data_readiness"]["sampling"]["reason_code"] == "recent_read_unavailable"
    assert {b["code"] for b in row["continuation"]["blockers"]} == {"evidence_recheck"}
    assert row["error_message"] == "temporary upstream failure"
    assert row["error_id"]
    from hypertrade.arc.evolution_models import ArcRuntimeError

    with service.db.session() as session:
        receipt = session.get(ArcRuntimeError, row["error_id"])
        assert receipt.message == "temporary upstream failure"
        assert receipt.context_json["strategy_id"] == 44


def test_returned_snapshot_with_missing_fields_keeps_identity_blockers(service):
    from datetime import UTC, datetime

    paper = Paper()
    original = paper.paper_snapshot

    def incomplete(**kwargs):
        return {**original(**kwargs), "instance_id": "", "session": {"started_at": None}}

    paper.paper_snapshot = incomplete
    service.client = paper
    diagnostics, _ = service._scan(
        EvolutionConfig(strategy_ids=[44]), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert {b["code"] for b in diagnostics[0]["continuation"]["blockers"]} >= {
        "session_identity",
        "session_start",
    }


def test_bitpro_snapshot_identity_mismatch_is_contract_alert(service):
    from datetime import UTC, datetime

    paper = Paper()
    original = paper.paper_snapshot
    paper.paper_snapshot = lambda **kwargs: {**original(**kwargs), "strategy_id": 999}
    service.client = paper
    diagnostics, chosen = service._scan(
        EvolutionConfig(strategy_ids=[44]), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert chosen is None
    row = diagnostics[0]
    assert row["data_readiness"]["sampling"]["reason_code"] == "recent_series_contract_mismatch"
    assert "核对" in row["data_readiness"]["next_action"]
    assert "稍后重试" not in row["data_readiness"]["next_action"]
    assert {b["code"]: b["resolution"] for b in row["continuation"]["blockers"]} == {
        "evidence_recheck": "operator"
    }


def test_bitpro_returned_snapshot_missing_version_keeps_identity_blocker(service):
    from datetime import UTC, datetime

    paper = Paper()
    original = paper.paper_snapshot
    paper.paper_snapshot = lambda **kwargs: {**original(**kwargs), "strategy_version": None}
    service.client = paper
    diagnostics, chosen = service._scan(
        EvolutionConfig(strategy_ids=[44]), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert chosen is None
    assert "session_identity" in {
        blocker["code"] for blocker in diagnostics[0]["continuation"]["blockers"]
    }


def test_bitpro_snapshot_invalid_timestamp_is_contract_alert(service):
    from datetime import UTC, datetime

    paper = Paper()
    original = paper.paper_snapshot
    paper.paper_snapshot = lambda **kwargs: {
        **original(**kwargs),
        "session": {"started_at": "invalid"},
    }
    service.client = paper
    diagnostics, chosen = service._scan(
        EvolutionConfig(strategy_ids=[44]), datetime(2026, 9, 22, tzinfo=UTC)
    )
    assert chosen is None
    row = diagnostics[0]
    assert row["data_readiness"]["sampling"]["reason_code"] == "recent_series_contract_mismatch"
    assert {b["code"]: b["resolution"] for b in row["continuation"]["blockers"]} == {
        "evidence_recheck": "operator"
    }


def test_crash_after_creation_recovers_same_task(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    original = service._save_cycle

    def crash(key, status, payload):
        if status == "research_created":
            raise SystemExit("simulated crash")
        return original(key, status, payload)

    monkeypatch.setattr(service, "_save_cycle", crash)
    with pytest.raises(SystemExit):
        service.tick(now)
    ids = list_mission_ids()
    monkeypatch.setattr(service, "_save_cycle", original)
    assert service.tick(now)["payload"]["mission_id"] == ids[0]
    assert list_mission_ids() == ids


def test_baseline_preserves_parameters_without_reusing_runtime():
    from decimal import Decimal

    from hypertrade.arc.evolution import baseline_config

    config = baseline_config(
        {
            "config": {
                "fast_window": 20,
                "leverage": 2,
                "paper_instance_id": "old",
                "_runtime": {"positions": [1]},
                "initial_capital": 1000,
            }
        },
        Decimal(100),
    )
    assert config["fast_window"] == 20
    assert config["leverage"] == 2
    assert config["strategy_source"] == "db_script"
    assert config["script_content_source"] == "db"
    assert config["initial_capital"] == 100
    assert "paper_instance_id" not in config
    assert "_runtime" not in config
    with pytest.raises(ValueError):
        baseline_config({"config": {"api_key": "sensitive"}}, Decimal(100))


def test_long_term_memory_uses_development_receipts_not_final_holdout(service, monkeypatch):
    from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.store import save_mission

    now = prepare(service, monkeypatch)
    old = ARCController(goal=ARCGoalV1(objective="prior", symbols=["SOL-USDT-SWAP"]))
    old.projection.state = "failed"
    old.projection.attempts = [
        ARCCandidateAttemptV1(
            attempt_id="prior",
            candidate_id="prior",
            hypothesis="reduce churn",
            strategy_code="pass",
            strategy_spec={"symbol": "SOL-USDT-SWAP", "timeframe": "1H"},
            observed_metrics={"secret_final_score": 999},
        )
    ]
    old.projection.avo["development"] = {
        "prior": {
            "backtest_id": "dev-proof",
            "passed": False,
            "purpose": "development",
            "code_sha256": __import__("hashlib").sha256(b"pass").hexdigest(),
            "metrics": {
                "net_return": -0.1,
                "evaluation_window": {
                    "purpose": "development",
                    "start_date": "2026-03-01",
                    "end_date": "2026-07-01",
                },
            },
        }
    }
    save_mission(old)
    result = service.tick(now)
    from hypertrade.arc.store import get_controller

    memory = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context[
        "memory"
    ]
    assert memory[0]["development"]["backtest_id"] == "dev-proof"
    assert "secret_final_score" not in str(memory)


def test_active_evolution_blocks_duplicate_source_next_hour(service, monkeypatch):
    from datetime import timedelta

    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    assert service.tick(now)["status"] == "research_created"
    assert service.tick(now + timedelta(hours=1))["status"] == "deferred"
    assert len(list_mission_ids()) == 1


def test_evolution_migration_creates_and_removes_only_its_tables():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).parents[1] / "backend/alembic/versions/0042_arc_evolution.py"
    spec = importlib.util.spec_from_file_location("evolution_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
        assert set(inspect(connection).get_table_names()) == {
            "arc_evolution_control",
            "arc_evolution_cycles",
        }
        module.downgrade()
        assert inspect(connection).get_table_names() == []


class VariantPaper(Paper):
    """Source whose parameter variants BitPro supports, bound to its own 100U capital."""

    capital: object = 100

    def strategy_get(self, **kwargs):
        body = super().strategy_get(**kwargs)
        if self.capital is not None:
            body["strategy"]["config"]["initial_capital"] = self.capital
        return body

    def strategy_research_variant_policy(self, **kwargs):
        return {
            "parent_strategy_id": 44,
            "parent_manifest_sha256": "a" * 64,
            "parent_execution_identity_sha256": "e" * 64,
            "variant_creation_supported": True,
            "authorized_parameters": [
                {"key": "fast_window", "type": "integer", "min": 2, "max": 50}
            ],
        }


def _variant_service(service, monkeypatch, capital):
    now = prepare(service, monkeypatch)
    service.client = VariantPaper()
    service.client.capital = capital
    state = service.status()
    service.configure(
        EvolutionConfig.model_validate({**state["config"], "paper_capital": "10000"}),
        revision=state["revision"],
        actor="test",
    )
    return now


def test_variant_research_uses_source_capital_not_global_paper_capital(service, monkeypatch):
    from decimal import Decimal

    from hypertrade.arc.store import get_controller

    now = _variant_service(service, monkeypatch, 100)
    result = service.tick(now)
    assert result["status"] == "research_created"
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.paper_initial_equity == Decimal(100)
    assert goal.evolution_context["research_capital"] == "100"
    assert goal.evolution_context["baseline"]["strategy_spec"]["baseline_config"][
        "initial_capital"
    ] == 100


def test_variant_research_without_source_capital_is_unavailable(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = _variant_service(service, monkeypatch, None)
    result = service.tick(now)
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["status"] == "unavailable"
    assert "原策略资金" in diagnostic["reason"]
    assert list_mission_ids() == []


def test_unrelated_deploy_keeps_execution_identity_and_still_creates_research(
    service, monkeypatch
):
    from hypertrade.arc.store import get_controller

    class DeployedManifest(VariantPaper):
        reads = 0

        def strategy_research_variant_policy(self, **kwargs):
            self.reads += 1
            policy = super().strategy_research_variant_policy(**kwargs)
            if self.reads > 1:
                policy["parent_manifest_sha256"] = "b" * 64
            return policy

    now = _variant_service(service, monkeypatch, 100)
    service.client = DeployedManifest()
    service.client.capital = 100
    result = service.tick(now)
    assert result["status"] == "research_created"
    spec = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context[
        "baseline"
    ]["strategy_spec"]
    assert spec["parent_manifest_sha256"] == "a" * 64
    assert spec["parent_execution_identity_sha256"] == "e" * 64


@pytest.mark.parametrize(
    "identity",
    ["1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64],
    ids=["source", "stub", "dependency", "class", "config"],
)
def test_execution_identity_drift_blocks_research(service, monkeypatch, identity):
    class Drifted(VariantPaper):
        reads = 0

        def strategy_research_variant_policy(self, **kwargs):
            self.reads += 1
            policy = super().strategy_research_variant_policy(**kwargs)
            if self.reads > 1:
                policy["parent_execution_identity_sha256"] = identity
            return policy

    now = _variant_service(service, monkeypatch, 100)
    service.client = Drifted()
    service.client.capital = 100
    result = service.tick(now)
    assert result["status"] == "source_changed"
    assert result["payload"]["skip_reason"] == "原策略执行身份在诊断期间发生变化"


def test_missing_execution_identity_does_not_fall_back_to_manifest(service, monkeypatch):
    class Missing(VariantPaper):
        reads = 0

        def strategy_research_variant_policy(self, **kwargs):
            self.reads += 1
            policy = super().strategy_research_variant_policy(**kwargs)
            if self.reads > 1:
                policy.pop("parent_execution_identity_sha256")
            return policy

    now = _variant_service(service, monkeypatch, 100)
    service.client = Missing()
    service.client.capital = 100
    result = service.tick(now)
    assert result["status"] == "source_changed"
    assert result["payload"]["skip_reason"] == "当前父策略执行身份缺失，不能只按清单校验"


def test_scan_without_execution_identity_does_not_start_variant_research(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    class NoIdentity(VariantPaper):
        def strategy_research_variant_policy(self, **kwargs):
            policy = super().strategy_research_variant_policy(**kwargs)
            policy.pop("parent_execution_identity_sha256")
            return policy

    now = _variant_service(service, monkeypatch, 100)
    service.client = NoIdentity()
    service.client.capital = 100
    result = service.tick(now)
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["status"] == "unavailable"
    assert "parent execution identity missing" in diagnostic["reason"]
    assert list_mission_ids() == []


def test_mid_relay_source_is_held_not_researched(service, monkeypatch):
    """BitPro marks racing/draining strategies; evolving them would orphan or nest races."""
    from hypertrade.arc.store import list_mission_ids

    class Racing(VariantPaper):
        def strategy_research_variant_policy(self, **kwargs):
            policy = super().strategy_research_variant_policy(**kwargs)
            policy["relay"] = {
                "blocks_evolution": True,
                "role": "challenger",
                "plan_state": "observing",
                "reason": "策略正作为挑战者参与赛马，结束前不再派生变体",
            }
            return policy

    now = _variant_service(service, monkeypatch, 100)
    service.client = Racing()
    service.client.capital = 100
    result = service.tick(now)
    diagnostic = result["payload"]["diagnostics"][0]
    assert result["status"] == "no_action"
    assert diagnostic["skip_reason"] == "relay_in_progress"
    assert diagnostic["relay_hold"]["role"] == "challenger"
    codes = [b["code"] for b in diagnostic["continuation"]["blockers"]]
    assert "relay_in_progress" in codes
    assert list_mission_ids() == []


class Seated(VariantPaper):
    """A source whose BitPro parent reports variant seats (and what it already raced)."""

    def __init__(self, relay, *, parent=44):
        self.relay, self.parent = relay, parent

    def strategy_research_variant_policy(self, **kwargs):
        policy = super().strategy_research_variant_policy(**kwargs)
        policy["parent_strategy_id"] = kwargs.get("strategy_id", self.parent)
        policy["relay"] = self.relay(kwargs.get("strategy_id", self.parent)) if callable(
            self.relay
        ) else self.relay
        return policy


def _seated_service(service, monkeypatch, relay):
    now = _variant_service(service, monkeypatch, 100)
    service.client = Seated(relay)
    service.client.capital = 100
    return now


def test_parent_whose_free_seats_are_all_booked_by_queued_candidates_is_held(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    relay = {
        "blocks_evolution": False,
        "slots": {"total": 3, "used": 1, "free": 2, "queued": 2},
        "tried_variants": [],
    }
    now = _seated_service(service, monkeypatch, relay)
    result = service.tick(now)
    diagnostic = result["payload"]["diagnostics"][0]
    assert result["status"] == "no_action"
    assert diagnostic["skip_reason"] == "seats_reserved"
    assert diagnostic["relay_seats"] == {"total": 3, "used": 1, "free": 2, "queued": 2, "open": 0}
    blockers = {b["code"]: b for b in diagnostic["continuation"]["blockers"]}
    assert "排队等位" in blockers["relay_in_progress"]["condition"]
    assert list_mission_ids() == []
    demand = result["payload"]["relay_seat_demand"]
    assert demand["seats_open"] == 0 and demand["candidates_queued"] == 2


def test_parent_with_an_open_seat_is_researched_and_the_seat_facts_travel_with_the_mission(
    service, monkeypatch
):
    from hypertrade.arc.store import get_controller

    tried = [
        {
            "candidate_strategy_id": 7,
            "state": "racing",
            "kind": None,
            "parameter_changes": {"fast_window": 7},
            "structural_changes": {},
        }
    ]
    relay = {
        "blocks_evolution": False,
        "slots": {"total": 3, "used": 1, "free": 2, "queued": 1},
        "tried_variants": tried,
    }
    now = _seated_service(service, monkeypatch, relay)
    result = service.tick(now)
    assert result["status"] == "research_created"
    context = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context
    assert context["relay_seats"]["open"] == 1
    # The model sees what BitPro already raced through the policy it inspects.
    assert context["variant_policy"]["relay"]["tried_variants"] == tried
    demand = result["payload"]["relay_seat_demand"]
    assert demand == {
        "parents_reporting_seats": 1,
        "seats_total": 3,
        "seats_used": 1,
        "seats_free": 2,
        "candidates_queued": 1,
        "seats_open": 1,
        "missions_left_today": 4,
        "max_candidates_per_mission": 3,
    }


def test_a_bitpro_without_variant_seats_is_researched_as_before(service, monkeypatch):
    from hypertrade.arc.store import get_controller

    now = _variant_service(service, monkeypatch, 100)
    result = service.tick(now)
    assert result["status"] == "research_created"
    assert "relay_seat_demand" not in result["payload"]
    assert "relay_seats" not in result["payload"]["diagnostics"][0]
    assert "relay_seats" not in get_controller(
        result["payload"]["mission_id"]
    ).projection.goal.evolution_context


class TwoParents(Seated):
    """Two running BitPro parents with different numbers of open seats."""

    def paper_strategy_performance(self, **kwargs):
        return {
            "strategies": [
                {
                    "strategy_id": sid,
                    "strategy_name": f"source-{sid}",
                    "mode": "paper",
                    "timeframe": "1H",
                }
                for sid in (44, 45)
            ]
        }

    def paper_snapshot(self, **kwargs):
        sid = kwargs["strategy_id"]
        body = super().paper_snapshot(**kwargs)
        return {**body, "strategy_id": sid, "instance_id": f"paper-source-{sid}"}

    def strategy_trades(self, **kwargs):
        rows = super().strategy_trades(**kwargs)
        return [{**row, "strategy_id": kwargs["strategy_id"]} for row in rows]


def test_among_equally_urgent_parents_the_one_with_more_open_seats_is_researched_first(
    service, monkeypatch
):
    def relay(strategy_id):
        free, queued = (1, 0) if strategy_id == 44 else (3, 0)
        return {
            "blocks_evolution": False,
            "slots": {"total": 3, "used": 3 - free, "free": free, "queued": queued},
            "tried_variants": [],
        }

    now = _variant_service(service, monkeypatch, 100)
    service.client = TwoParents(relay)
    service.client.capital = 100
    result = service.tick(now)
    assert result["status"] == "research_created"
    assert result["payload"]["source_strategy_id"] == 45  # three open seats beat one
    demand = result["payload"]["relay_seat_demand"]
    assert demand["parents_reporting_seats"] == 2 and demand["seats_open"] == 4


def test_a_parent_whose_seats_are_booked_gives_way_to_one_with_an_open_seat(service, monkeypatch):
    def relay(strategy_id):
        free, queued = (3, 3) if strategy_id == 44 else (1, 0)
        return {
            "blocks_evolution": False,
            "slots": {"total": 3, "used": 3 - free, "free": free, "queued": queued},
            "tried_variants": [],
        }

    now = _variant_service(service, monkeypatch, 100)
    service.client = TwoParents(relay)
    service.client.capital = 100
    result = service.tick(now)
    assert result["status"] == "research_created"
    assert result["payload"]["source_strategy_id"] == 45
    held = next(d for d in result["payload"]["diagnostics"] if d["strategy_id"] == 44)
    assert held["skip_reason"] == "seats_reserved" and held["relay_seats"]["open"] == 0


def _forward_outcome(
    db,
    *,
    parent: str,
    challenger: str,
    verdict: str,
    ended_at: str,
    linked: bool = True,
):
    """Record one finished race; ARC lineage is stated explicitly instead of inferred."""
    from datetime import datetime

    from hypertrade.arc.evolution_models import ArcForwardOutcome
    from hypertrade.arc.forward_outcomes import ForwardOutcomeLedger

    row = ForwardOutcomeLedger(db).record(
        target_id="bitpro",
        parent_strategy_id=parent,
        challenger_strategy_id=challenger,
        verdict=verdict,
        metrics={"excess_return_pct": 1.5},
        ended_at=datetime.fromisoformat(ended_at),
    )
    if linked:
        with db.session() as session:
            stored = session.get(ArcForwardOutcome, row["id"])
            assert stored is not None
            stored.lineage_status = "linked"
            stored.changes_json = {
                "parameter_changes": {"fast_window": 20},
                "structural_changes": {},
            }
    return row


def test_memory_prepends_forward_outcomes_from_the_champion_chain(service, monkeypatch):
    from hypertrade.arc.store import get_controller

    # 44 won its way into the champion seat it is being evolved from.
    _forward_outcome(
        service.db, parent="43", challenger="44", verdict="won", ended_at="2026-01-01T00:00:00"
    )
    _forward_outcome(
        service.db,
        parent="43",
        challenger="4301",
        verdict="lost_exam",
        ended_at="2026-01-02T00:00:00",
    )
    _forward_outcome(
        service.db,
        parent="44",
        challenger="4401",
        verdict="lost_futility",
        ended_at="2026-01-03T00:00:00",
    )
    # Other lineage, neutral ending and unlinked loss: never memory for this strategy.
    _forward_outcome(
        service.db, parent="99", challenger="9901", verdict="won", ended_at="2026-01-04T00:00:00"
    )
    _forward_outcome(
        service.db,
        parent="44",
        challenger="4402",
        verdict="superseded",
        ended_at="2026-01-05T00:00:00",
    )
    _forward_outcome(
        service.db,
        parent="44",
        challenger="4403",
        verdict="lost_exam",
        ended_at="2026-01-06T00:00:00",
        linked=False,
    )

    now = _variant_service(service, monkeypatch, 100)
    result = service.tick(now)
    assert result["status"] == "research_created"
    context = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context
    memory = context["memory"]
    assert [entry["challenger_strategy_id"] for entry in memory] == ["4401", "4301", "44"]
    assert [entry["memory_id"].split(":")[0] for entry in memory] == ["outcome"] * 3
    assert [
        (entry["relation"], entry["generations_back"], entry["verdict"]) for entry in memory
    ] == [
        ("variant_of_current", 0, "lost_futility"),
        ("variant_of_ancestor", 1, "lost_exam"),
        ("made_current", 1, "won"),
    ]
    assert [entry["type"] for entry in memory] == ["forward_outcome"] * 3
    assert context["memory_manifest"]["forward_outcomes"] == {
        "policy": "forward_outcome_v1",
        "selected": 3,
        "won": 1,
        "lost": 2,
    }


def test_memory_continues_when_forward_outcomes_fail(service, monkeypatch):
    from hypertrade.arc.forward_outcomes import ForwardOutcomeLedger
    from hypertrade.arc.store import get_controller

    def unavailable(self, **kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(ForwardOutcomeLedger, "evidence_for_lineage", unavailable)
    now = _variant_service(service, monkeypatch, 100)
    result = service.tick(now)
    assert result["status"] == "research_created"
    context = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context
    assert context["memory"] == []
    manifest = context["memory_manifest"]["forward_outcomes"]
    assert manifest["policy"] == "forward_outcome_v1"
    assert manifest["selected"] == 0
    assert "ledger unavailable" in manifest["error"]


def test_forward_outcomes_precede_development_memory_in_the_model_view(service, monkeypatch):
    from hypertrade.arc.avo import _evolution_view
    from hypertrade.arc.store import get_controller
    from hypertrade.memory.service import MemoryService

    # Enough development memory to exceed the 20-entry model window on its own.
    dev = [
        {
            "memory_id": f"dev-{i}",
            "mission_id": f"m-{i}",
            "candidate_id": f"c-{i}",
        }
        for i in range(25)
    ]

    def project(self, records, **kwargs):
        return dev, {"policy": "test"}

    monkeypatch.setattr(MemoryService, "project_research", project)
    # 44 won its way into the champion seat; 4401 raced under it and lost.
    _forward_outcome(
        service.db,
        parent="44",
        challenger="4401",
        verdict="lost_futility",
        ended_at="2026-01-03T00:00:00",
    )
    _forward_outcome(
        service.db, parent="43", challenger="44", verdict="won", ended_at="2026-01-01T00:00:00"
    )

    now = _variant_service(service, monkeypatch, 100)
    result = service.tick(now)
    assert result["status"] == "research_created"
    context = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context
    memory = context["memory"]
    assert len(memory) == 27
    # Newest race first; the two outcomes stay ahead of all development entries.
    assert [entry["type"] for entry in memory[:2]] == ["forward_outcome"] * 2
    assert [entry["challenger_strategy_id"] for entry in memory[:2]] == ["4401", "44"]
    assert [entry["memory_id"] for entry in memory[2:]] == [f"dev-{i}" for i in range(25)]
    assert context["memory_manifest"]["policy"] == "test"
    assert context["memory_manifest"]["forward_outcomes"] == {
        "policy": "forward_outcome_v1",
        "selected": 2,
        "won": 1,
        "lost": 1,
    }

    # The model only reads the first 20 entries, so ordering decides what it sees.
    view = _evolution_view(context)
    assert len(view["memory"]) == 20
    assert [entry["type"] for entry in view["memory"][:2]] == ["forward_outcome"] * 2
    assert view["memory"][2]["memory_id"] == "dev-0"
    assert view["memory_in_view"] == {"shown": 20, "total": 27}
