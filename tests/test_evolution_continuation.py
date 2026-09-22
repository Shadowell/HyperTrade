from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.store import configure_store, list_mission_ids, reset_runtime, reset_store
from hypertrade.db import Database
from test_arc_evolution import Paper
from test_paper_feedback import PaperClient


class EvidencePaper(Paper, PaperClient):
    def __init__(self):
        self.calls = 0
        self.trades = 2
        self.started = "2026-08-01T12:00:00Z"

    def strategy_return_series(self, **kwargs):
        page = super().strategy_return_series(**kwargs)
        page["cost_model"] = {
            "fees": {"taker_fee_bps": 5},
            "slippage": {"slippage_bps": 2},
            "funding": {"mode": "net"},
        }
        return page

    def paper_snapshot(self, **kwargs):
        row = super().paper_snapshot(**kwargs)
        row.update(instance_id="paper-session", trade_count=self.trades)
        row["session"]["started_at"] = self.started
        return row


@pytest.fixture
def service(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/continuation.db")
    db.create_all()
    configure_store(db)
    client = EvidencePaper()
    service = EvolutionService(db, client)
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    yield service
    reset_store()


def test_blockers_survive_restart_with_exact_time_and_trade_conditions(service):
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    assert service.tick(now)["status"] == "no_action"
    reset_runtime()
    restarted = EvolutionService(service.db, service.client)
    item = restarted.status()["continuations"][0]
    assert item["observed_at"] == now.isoformat()
    blockers = {b["code"]: b for b in item["blockers"]}
    assert blockers["minimum_trades"]["observed"] == 2
    assert blockers["minimum_trades"]["required"] == 30
    assert blockers["completed_utc_window"]["eligible_at"] == "2026-08-16T00:00:00+00:00"
    assert item["evidence_cursor"]["instance_id"] == "paper-session"
    assert item["next_eligible_at"] == "2026-08-16T00:00:00+00:00"
    assert list_mission_ids() == []


def test_trade_threshold_rechecks_after_data_arrives(service):
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    service.tick(now)
    before = service.status()["continuations"][0]
    assert before["blockers"][0]["code"] == "minimum_trades"
    service.client.trades = 60
    result = service.tick(now + timedelta(hours=1))
    after = service.status()["continuations"][0]
    assert all(b["code"] != "minimum_trades" for b in after["blockers"])
    assert after["observed_at"] != before["observed_at"]
    assert result["status"] != "error"


def test_acceptance_never_infers_guarded_stages_from_paper_observing(service):
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_continuation import ContinuationLedger
    from hypertrade.arc.store import save_mission

    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="audit",
            research_mode="avo",
            paper_review_required=True,
            evolution_context={"source_strategy_id": 44, "source_instance_id": "paper-session"},
        )
    )
    ctrl.projection.state = "paper_observing"
    save_mission(ctrl)
    ledger = ContinuationLedger(service.db)
    ledger.refresh(datetime(2026, 9, 12, tzinfo=UTC))
    acceptance = ledger.view()[0]["acceptance"]
    assert acceptance["status"] == "evidence_incomplete"
    assert "reviewed_configure" in acceptance["missing_stages"]
    assert "reviewed_start" in acceptance["missing_stages"]


def test_acceptance_requires_a_positive_unexceeded_avo_budget():
    from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_continuation import acceptance_entries

    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="audit",
            research_mode="avo",
            paper_review_required=True,
            budget=ARCBudgetV1(max_candidates=1, candidates_used=2),
        )
    )
    stages = acceptance_entries(ctrl.projection, datetime(2026, 9, 12, tzinfo=UTC))
    budget = next(item for item in stages if item["stage"] == "budgeted_avo")
    assert budget["result"] == "missing"


def test_receipt_callback_is_before_start_and_failure_prevents_start():
    from hypertrade.arc.contracts import PaperPreauthorizationV1
    from hypertrade.arc.incubation import ARCPaperIncubationResolver
    from test_arc_incubation import _RecordingClient, _validated

    client = _RecordingClient()
    events = []

    def record(event, receipt):
        events.append(event)
        assert "paper_start" not in client.calls
        raise RuntimeError("ledger unavailable")

    resolver = ARCPaperIncubationResolver(client, on_receipt=record)
    attempt = _validated()
    with pytest.raises(RuntimeError):
        resolver.resolve_and_provision_paper_trading(attempt, PaperPreauthorizationV1())
    assert events == ["paper_review_configured"]
    assert "paper_start" not in client.calls


def test_check_ledger_is_idempotent_and_retains_prior_evidence(service):
    from hypertrade.arc.evolution_continuation import ContinuationLedger, readiness
    from hypertrade.arc.evolution_models import EvolutionAcceptance
    from sqlalchemy import select

    ledger = ContinuationLedger(service.db)
    now = datetime(2026, 8, 10, tzinfo=UTC)
    diagnostic = {"strategy_id": 44, "status": "unavailable", "reason": "trades"}
    diagnostic["continuation"] = readiness(
        service.client.paper_snapshot(), diagnostic, EvolutionConfig(), now
    )
    ledger.record_check("first", [diagnostic])
    ledger.record_check("first", [diagnostic])
    service.client.trades = 31
    diagnostic["continuation"] = readiness(
        service.client.paper_snapshot(), diagnostic, EvolutionConfig(), now + timedelta(hours=1)
    )
    ledger.record_check("second", [diagnostic])
    with service.db.session() as session:
        receipts = session.scalars(select(EvolutionAcceptance)).all()
        assert len(receipts) == 2
        assert receipts[0].payload_json["evidence_cursor"]["trade_count"] == 2
    assert ledger.view()[0]["evidence_cursor"]["trade_count"] == 31


def test_time_gate_uses_next_complete_utc_day_not_elapsed_fourteen_days(service):
    from hypertrade.arc.evolution_continuation import readiness

    config = EvolutionConfig()
    snap = service.client.paper_snapshot()
    result = readiness(
        snap, {"status": "unavailable"}, config, datetime(2026, 8, 15, 12, tzinfo=UTC)
    )
    assert result["next_eligible_at"] == "2026-08-16T00:00:00+00:00"
    due = readiness(snap, {"status": "unavailable"}, config, datetime(2026, 8, 16, tzinfo=UTC))
    assert not any(b["code"] == "completed_utc_window" for b in due["blockers"])
    assert any(b["code"] == "minimum_trades" for b in due["blockers"])


def test_unknown_effect_stops_acceptance_resume_and_replay_deduplicates(service):
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_continuation import ContinuationLedger
    from hypertrade.arc.evolution_models import EvolutionAcceptance
    from hypertrade.arc.store import save_mission
    from sqlalchemy import func, select

    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="audit",
            paper_review_required=True,
            research_mode="avo",
            evolution_context={"source_strategy_id": 44, "source_instance_id": "paper-session"},
        )
    )
    ctrl.projection.state = "needs_operator"
    ctrl.projection.avo["pending"] = {"kind": "tool", "id": "unknown-create"}
    save_mission(ctrl)
    ledger = ContinuationLedger(service.db)
    now = datetime(2026, 9, 12, tzinfo=UTC)
    ledger.refresh(now)
    reset_runtime()
    ledger.refresh(now + timedelta(hours=1))
    acceptance = ledger.view()[0]["acceptance"]
    assert acceptance["status"] == "reconciliation_required"
    assert acceptance["automatic_resume"] is False
    assert acceptance["pending_effect"] is True
    with service.db.session() as session:
        assert session.scalar(select(func.count()).select_from(EvolutionAcceptance)) == 3
    assert len(list_mission_ids()) == 1


def test_receipt_audit_excludes_raw_configuration_and_secrets():
    from hypertrade.arc.incubation import audit_receipt

    receipt = audit_receipt(
        {
            "instance_id": "paper_x",
            "strategy_id": 44,
            "config": {"api_key": "must-not-copy"},
            "script_content": "private",
        },
        "h",
    )
    assert receipt["paper_instance_id"] == "paper_x"
    assert "private" not in str(receipt)
    assert "must-not-copy" not in str(receipt)


def test_continuation_migration_roundtrip_preserves_existing_tables():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = Path(__file__).parents[1] / "backend/alembic/versions/0044_evolution_continuation.py"
    spec = importlib.util.spec_from_file_location("continuation_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        conn.execute(text("CREATE TABLE existing_paper (id INTEGER)"))
        conn.execute(text("INSERT INTO existing_paper VALUES (501)"))
        module.upgrade()
        assert "arc_evolution_continuations" in inspect(conn).get_table_names()
        module.downgrade()
        assert inspect(conn).get_table_names() == ["existing_paper"]
        assert conn.execute(text("SELECT id FROM existing_paper")).scalar() == 501


@pytest.fixture
def accepted_chain(service, monkeypatch):
    from hypertrade.arc.contracts import ARCGoalV1, PaperFeedbackPolicyV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.feedback import collect_windows
    from hypertrade.arc.incubation import ARCPaperIncubationResolver
    from hypertrade.arc.paper_review import decide_paper_review, request_paper_review
    from test_arc_incubation import _RecordingClient, _validated

    class Guarded(_RecordingClient):
        def paper_configure_reviewed(self, **kwargs):
            value = self.paper_configure(**kwargs)
            value["paper"].update(
                guard_version="paper_review_binding.v1",
                review_hash=kwargs["review_hash"],
                code_sha256=kwargs["code_sha256"],
                config_version="config-bound",
            )
            return value

        def paper_start_reviewed(self, **kwargs):
            self.calls.append("start_reviewed")
            return {
                "status": "ok",
                "paper": {**kwargs, "started": True, "guard_version": "paper_review_binding.v1"},
            }

    paper = EvidencePaper()
    paper.started = "2026-08-01T00:00:00Z"
    feedback = collect_windows(
        paper, "paper-session", "44", datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1()
    )
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="audit",
            research_mode="avo",
            paper_review_required=True,
            paper_review_mode="agent",
            evolution_context={
                "source_strategy_id": 44,
                "source_instance_id": "paper-session",
                "paper_feedback": feedback,
            },
        )
    )
    attempt = _validated()
    attempt.bitpro_strategy_id = "42"
    ctrl.apply_event("candidate_proposed", {"attempt": attempt.model_dump(mode="json")})
    ctrl.apply_event("avo_baseline_result", {"backtest_id": "baseline-final"})
    ctrl.apply_event(
        "bitpro_self_tested",
        {
            "attempt_id": attempt.attempt_id,
            "passed": True,
            "backtest_id": "candidate-final",
            "validation_id": "validation",
            "metrics": {"baseline_comparison": {"passed": True, "backtest_id": "baseline-final"}},
        },
    )
    review = request_paper_review(ctrl)
    ctrl.apply_event(
        "paper_auto_review_evaluated",
        {"decision": "approve", "package_hash": review["package_hash"]},
    )
    client = Guarded()
    monkeypatch.setattr(
        "hypertrade.arc.paper_review.ARCPaperIncubationResolver",
        lambda **kwargs: ARCPaperIncubationResolver(client, **kwargs),
    )
    decide_paper_review(
        ctrl,
        package_hash=review["package_hash"],
        decision="approve",
        reason="test policy receipt",
        operator_id="test-policy",
        identity_source="agent_policy",
        idempotency_key="test-audit",
    )
    assert ctrl.projection.state == "paper_observing"
    events = [e.event_type for e in ctrl.projection.events]
    assert events.index("paper_review_configured") < events.index("paper_review_started")
    return ctrl, client


def test_real_review_receipt_protocol_replays_every_acceptance_stage(service, accepted_chain):
    from hypertrade.arc.evolution_continuation import ContinuationLedger

    ctrl, client = accepted_chain
    ledger = ContinuationLedger(service.db)
    ledger.refresh(datetime(2026, 8, 15, tzinfo=UTC))
    acceptance = ledger.view()[0]["acceptance"]
    assert acceptance["status"] == "accepted"
    assert acceptance["missing_stages"] == []
    reset_runtime()
    ledger.refresh(datetime(2026, 8, 15, 1, tzinfo=UTC))
    assert ledger.view()[0]["acceptance"]["event_cursor"] == acceptance["event_cursor"]
    assert client.calls.count("start_reviewed") == 1


def test_trigger_receipts_must_cover_one_contiguous_fourteen_day_window(service, accepted_chain):
    from hypertrade.arc.evolution_continuation import acceptance_entries

    ctrl, _ = accepted_chain
    feedback = ctrl.projection.goal.evolution_context["paper_feedback"]
    feedback["receipts"][17]["start_at"] = feedback["receipts"][16]["start_at"]
    entries = acceptance_entries(ctrl.projection, datetime(2026, 8, 15, tzinfo=UTC))
    trigger = next(item for item in entries if item["stage"] == "trigger_7_plus_7")
    assert trigger["result"] == "missing"


def test_concurrent_scanners_leave_one_check_and_no_child(service):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    original = service.client.paper_strategy_performance

    def inventory(**kwargs):
        entered.set()
        assert release.wait(5)
        return original(**kwargs)

    service.client.paper_strategy_performance = inventory
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.tick, now)
        assert entered.wait(5)
        assert EvolutionService(service.db, service.client).tick(now)["status"] == "busy"
        release.set()
        assert first.result()["status"] == "no_action"
    assert len(service.status()["continuations"]) == 1
    assert list_mission_ids() == []


def test_late_series_arrives_without_recreating_original_session(service, monkeypatch):
    service.client.trades = 60
    service.client.started = "2026-08-01T00:00:00Z"
    original_snapshot = service.client.paper_snapshot()
    calls = []
    available = False
    original_series = service.client.strategy_return_series

    def late(**kwargs):
        calls.append(kwargs)
        if not available:
            raise ValueError("real source not yet persisted")
        return original_series(**kwargs)

    monkeypatch.setattr(service.client, "strategy_return_series", late)
    monkeypatch.setattr(
        service.client,
        "strategy_trades",
        lambda **kw: [{"id": "fill", "strategy_id": 44, "timestamp": 1786406400000}],
    )
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    assert service.tick(now)["status"] == "no_action"
    assert service.status()["continuations"][0]["check_result"] == "unavailable"
    available = True
    result = service.tick(now + timedelta(hours=1))
    assert result["status"] == "research_created"
    assert service.status()["continuations"][0]["check_result"] == "opportunity"
    assert service.client.paper_snapshot() == original_snapshot
    assert len(list_mission_ids()) == 1
    assert all(c["source_id"] == "paper-session" for c in calls)


@pytest.mark.parametrize(
    "fault,stage",
    [
        ("other_instance", "reviewed_start"),
        ("other_config", "reviewed_start"),
        ("missing_strategy_version", "reviewed_start"),
        ("other_strategy_version", "reviewed_start"),
        ("other_review", "reviewed_start"),
        ("original_instance", "reviewed_start"),
        ("other_candidate", "final_validation"),
        ("partial_window", "trigger_7_plus_7"),
    ],
)
def test_acceptance_cannot_mix_sources_versions_or_candidates(accepted_chain, fault, stage):
    from hypertrade.arc.evolution_continuation import acceptance_entries

    ctrl, _ = accepted_chain
    event = next(e for e in ctrl.projection.events if e.event_type == "paper_review_started")
    if fault == "other_instance":
        event.payload["paper_instance_id"] = "paper_unrelated"
    elif fault == "other_config":
        event.payload["config_version"] = "wrong-version"
    elif fault == "missing_strategy_version":
        event.payload.pop("strategy_version")
    elif fault == "other_strategy_version":
        event.payload["strategy_version"] = "sha256:wrong-version"
    elif fault == "other_review":
        event.payload["package_hash"] = "wrong-review"
    elif fault == "original_instance":
        event.payload["paper_instance_id"] = "paper-session"
    elif fault == "other_candidate":
        next(e for e in ctrl.projection.events if e.event_type == "bitpro_self_tested").payload[
            "attempt_id"
        ] = "other-candidate"
    else:
        ctrl.projection.goal.evolution_context["paper_feedback"]["receipts"].pop()
    entries = acceptance_entries(ctrl.projection, datetime(2026, 8, 15, tzinfo=UTC))
    assert not any(e["stage"] == stage and e["result"] == "passed" for e in entries)


def test_budget_denial_and_cooldown_conditions_are_preserved_without_admission(service):
    from hypertrade.arc.evolution_continuation import ContinuationLedger, readiness
    from hypertrade.arc.research_budget import source_key

    ledger = ContinuationLedger(service.db)
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    diagnostic = {"strategy_id": 44, "status": "opportunity"}
    diagnostic["continuation"] = readiness(
        service.client.paper_snapshot(), diagnostic, EvolutionConfig(), now
    )
    budget = {
        "schema_version": "research_budget.v1",
        "reason": "period_limit",
        "next_run_at": "2026-09-13T00:00:00+00:00",
        "sources": {
            source_key("bitpro", 44, "paper-session"): {
                "reason": "source_cooldown",
                "next_run_at": "2026-09-14T12:00:00+00:00",
            }
        },
    }
    ledger.record_check("denied", [diagnostic], budget)
    item = ledger.view()[0]
    assert item["next_eligible_at"] == "2026-09-14T12:00:00+00:00"
    assert item["dispatch_condition"]["source_reason"] == "source_cooldown"
    assert item["dispatch_condition"]["source_next_run_at"] == "2026-09-14T12:00:00+00:00"
    assert {"period_limit", "source_cooldown"} <= {b["code"] for b in item["blockers"]}
    budget["sources"][source_key("bitpro", 44, "paper-session")] = {
        "reason": "source_active",
        "next_run_at": None,
    }
    ledger.record_check("held", [diagnostic], budget)
    assert ledger.view()[0]["dispatch_condition"]["source_next_run_at"] is None
    assert list_mission_ids() == []


def test_feedback_generation_uses_immediate_parent_not_inherited_ancestor(service, accepted_chain):
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_continuation import ContinuationLedger
    from hypertrade.arc.store import save_mission

    original, _ = accepted_chain
    child_goal = original.projection.goal.model_copy(deep=True)
    child_goal.feedback_parent = {
        "instance_id": "paper_9",
        "evidence": {"strategy_id": "42", "source_id": "paper_9"},
    }
    child = ARCController(goal=child_goal)
    save_mission(child)
    ledger = ContinuationLedger(service.db)
    ledger.refresh(datetime(2026, 8, 16, tzinfo=UTC))
    sources = {row["strategy_id"]: row for row in ledger.view()}
    assert sources[42]["evidence_cursor"]["instance_id"] == "paper_9"
    assert sources[42]["acceptance"]["mission_id"] == child.mission_id
    assert sources[44]["acceptance"]["mission_id"] == original.mission_id
