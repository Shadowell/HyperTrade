from __future__ import annotations

from datetime import datetime

import hypertrade.arc.forward_outcomes as forward_outcomes
import pytest
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution_models import ArcForwardOutcome
from hypertrade.arc.forward_outcomes import (
    EVIDENCE_VERDICTS,
    NEUTRAL_VERDICTS,
    ForwardOutcomeLedger,
    metrics_from_record,
    outcome_id,
    verdict_for,
)
from hypertrade.arc.store import configure_store, reset_store, save_mission
from hypertrade.db import ArcMission, ArcMissionEvent, Database
from hypertrade.paper.race_judge import RacePairRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

METRIC_KEYS = {
    "excess_return_pct",
    "parent_net_return_pct",
    "challenger_net_return_pct",
    "parent_max_drawdown_pct",
    "challenger_max_drawdown_pct",
    "parent_trades",
    "challenger_trades",
    "observed_hours",
    "sign_test_p",
    "gate_alpha",
    "positive_days",
    "paired_non_tie_days",
    "slot_no",
    "cancellation_reason",
    "cancellation_metrics",
}


@pytest.fixture
def ledger():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield ForwardOutcomeLedger(db)
    reset_store()


def _save_mission(*challengers: str) -> ARCController:
    """One ARC mission whose attempts launched the given BitPro challengers."""
    ctrl = ARCController(goal=ARCGoalV1(objective="race outcomes", symbols=["BTC-USDT"]))
    for index, challenger in enumerate(challengers):
        ctrl.projection.attempts.append(
            ARCCandidateAttemptV1(
                attempt_id=f"attempt-{challenger}",
                candidate_id=f"candidate-{challenger}",
                hypothesis=f"variant {challenger}",
                strategy_code="class Variant: pass\n",
                strategy_spec={
                    "parameter_changes": {"fast_window": 10 + index},
                    "structural_changes": {},
                    "symbol": "BTC-USDT",
                    "symbols": ["BTC-USDT"],
                    "timeframe": "1H",
                    "parent_strategy_id": 107,
                },
                bitpro_strategy_id=challenger,
            )
        )
    save_mission(ctrl)
    return ctrl


def _race_record(**overrides) -> dict:
    fields: dict = {
        "observed_hours": 100,
        "parent_trades": 11,
        "challenger_trades": 13,
        "parent_net_return_pct": 1.0,
        "challenger_net_return_pct": 2.0,
        "excess_return_pct": 1.0,
        "parent_max_drawdown_pct": 3.0,
        "challenger_max_drawdown_pct": 4.0,
        "sign_test_p": 0.04,
        "positive_days": 8,
        "paired_non_tie_days": 12,
        "slot_no": 2,
        "gate_alpha": 0.025,
        "cancellation_reason": "too slow",
        "cancellation_metrics": {"common_hours": 100, "excess_pp": -2.0},
    }
    fields.update(overrides)
    return RacePairRecord(
        parent_strategy_id=107, challenger_strategy_id=9001, **fields
    ).to_dict()


def _record(
    ledger: ForwardOutcomeLedger,
    *,
    challenger: str,
    verdict: str,
    parent: int = 107,
    metrics: dict | None = None,
    ended_at: datetime | None = None,
    source: str = "race_judge",
    link: bool = True,
) -> dict:
    return ledger.record(
        target_id="bitpro",
        parent_strategy_id=parent,
        challenger_strategy_id=challenger,
        verdict=verdict,
        metrics=metrics or {},
        ended_at=ended_at,
        source=source,
        link=link,
    )


def test_outcome_id_is_stable_and_normalizes_ids() -> None:
    first = outcome_id("bitpro", 107, 9001)
    assert first == outcome_id("bitpro", "107", "9001")
    assert first.startswith("fo_")
    assert len(first) == 3 + 32
    assert first != outcome_id("bitpro", 107, 9002)


def test_verdict_for_maps_every_finished_state() -> None:
    assert verdict_for("completed", None) == "won"
    assert verdict_for("cancelled", "futility") == "lost_futility"
    assert verdict_for("cancelled", "exam") == "lost_exam"
    assert verdict_for("cancelled", "timeout") == "expired_timeout"
    assert verdict_for("cancelled", "superseded") == "superseded"
    assert verdict_for("cancelled", "operator") == "cancelled_operator"
    assert verdict_for("cancelled", "system") == "cancelled_unknown"
    assert verdict_for("cancelled", None) == "cancelled_unknown"
    assert verdict_for("cancelled", "new_kind_from_the_future") == "cancelled_unknown"
    assert verdict_for("ended", None) == "ended_unknown"
    for state in ("observing", "draining", "transferred", "rejected", None):
        assert verdict_for(state, None) is None


def test_verdict_constants_classify_evidence_and_neutral_results() -> None:
    assert EVIDENCE_VERDICTS == ("won", "lost_futility", "lost_exam")
    assert set(NEUTRAL_VERDICTS).isdisjoint(EVIDENCE_VERDICTS)


def test_metrics_from_record_keeps_known_values() -> None:
    metrics = metrics_from_record(_race_record())
    assert set(metrics) == METRIC_KEYS
    assert metrics["excess_return_pct"] == 1.0
    assert metrics["parent_net_return_pct"] == 1.0
    assert metrics["challenger_net_return_pct"] == 2.0
    assert metrics["parent_trades"] == 11
    assert metrics["challenger_trades"] == 13
    assert metrics["observed_hours"] == 100
    assert metrics["sign_test_p"] == 0.04
    assert metrics["gate_alpha"] == 0.025
    assert metrics["positive_days"] == 8
    assert metrics["paired_non_tie_days"] == 12
    assert metrics["slot_no"] == 2
    assert metrics["cancellation_reason"] == "too slow"
    assert metrics["cancellation_metrics"] == {"common_hours": 100, "excess_pp": -2.0}


def test_metrics_from_record_leaves_unknown_as_none() -> None:
    metrics = metrics_from_record({})
    assert set(metrics) == METRIC_KEYS
    assert all(value is None for value in metrics.values())


def test_metrics_from_record_treats_missing_or_zero_non_tie_days_as_unknown() -> None:
    metrics = metrics_from_record(_race_record(positive_days=0, paired_non_tie_days=0))
    assert metrics["positive_days"] is None
    assert metrics["paired_non_tie_days"] is None

    record = _race_record()
    record.pop("paired_non_tie_days")
    metrics = metrics_from_record(record)
    assert metrics["positive_days"] is None
    assert metrics["paired_non_tie_days"] is None


def test_metrics_from_record_rejects_booleans_and_non_finite_numbers() -> None:
    metrics = metrics_from_record(
        _race_record(
            excess_return_pct=float("nan"),
            parent_trades=True,
            challenger_trades=float("inf"),
            sign_test_p=float("-inf"),
            cancellation_metrics="not a dict",
        )
    )
    assert metrics["excess_return_pct"] is None
    assert metrics["parent_trades"] is None
    assert metrics["challenger_trades"] is None
    assert metrics["sign_test_p"] is None
    assert metrics["cancellation_metrics"] is None


def test_record_is_idempotent_and_keeps_first_evidence(ledger: ForwardOutcomeLedger) -> None:
    first = _record(
        ledger,
        challenger="9001",
        verdict="lost_exam",
        metrics={"excess_return_pct": -1.0},
    )
    second = _record(
        ledger,
        challenger="9001",
        verdict="lost_exam",
        metrics={"excess_return_pct": -2.0},
    )
    assert second["id"] == first["id"]
    assert second["verdict"] == "lost_exam"
    assert second["metrics"] == {"excess_return_pct": -1.0}
    assert second["evidence_sha256"] == first["evidence_sha256"]
    with ledger.db.session() as session:
        assert len(session.scalars(select(ArcForwardOutcome)).all()) == 1


def test_concrete_verdict_is_never_rewritten(ledger: ForwardOutcomeLedger) -> None:
    first = _record(
        ledger,
        challenger="9001",
        verdict="lost_exam",
        metrics={"excess_return_pct": -1.0},
    )
    second = _record(
        ledger,
        challenger="9001",
        verdict="won",
        metrics={"excess_return_pct": 5.0},
    )
    assert second["verdict"] == "lost_exam"
    assert second["metrics"] == first["metrics"]
    assert second["evidence_sha256"] == first["evidence_sha256"]


def test_unknown_ending_can_be_upgraded_to_a_concrete_verdict(
    ledger: ForwardOutcomeLedger,
) -> None:
    _record(ledger, challenger="9001", verdict="ended_unknown")
    upgraded = _record(
        ledger,
        challenger="9001",
        verdict="lost_futility",
        metrics={"excess_return_pct": -3.0},
        ended_at=datetime(2026, 1, 2, 3, 4),
        source="operator",
    )
    assert upgraded["verdict"] == "lost_futility"
    assert upgraded["verdict_source"] == "operator"
    assert upgraded["metrics"] == {"excess_return_pct": -3.0}
    assert upgraded["ended_at"] is not None
    assert upgraded["ended_at"].startswith("2026-01-02T03:04")


def test_one_unknown_verdict_does_not_replace_another(ledger: ForwardOutcomeLedger) -> None:
    _record(ledger, challenger="9001", verdict="ended_unknown")
    result = _record(ledger, challenger="9001", verdict="cancelled_unknown")
    assert result["verdict"] == "ended_unknown"


def test_unknown_verdict_is_rejected(ledger: ForwardOutcomeLedger) -> None:
    with pytest.raises(ValueError):
        _record(ledger, challenger="9001", verdict="handoff")


def test_record_links_matching_mission_attempt(ledger: ForwardOutcomeLedger) -> None:
    mission = _save_mission("9001")
    row = ledger.record(
        target_id="bitpro",
        parent_strategy_id=107,
        challenger_strategy_id="9001",
        verdict="won",
        metrics={"excess_return_pct": 2.5},
        ended_at=datetime(2026, 1, 1),
        slot_no=2,
    )
    assert row["lineage_status"] == "linked"
    assert row["mission_id"] == mission.mission_id
    assert row["candidate_id"] == "candidate-9001"
    assert row["attempt_id"] == "attempt-9001"
    assert row["changes"] == {
        "parameter_changes": {"fast_window": 10},
        "structural_changes": {},
    }
    assert row["scope"] == {
        "symbol": "BTC-USDT",
        "symbols": ["BTC-USDT"],
        "timeframe": "1H",
        "parent_strategy_id": 107,
    }
    assert row["slot_no"] == 2


def test_record_without_matching_attempt_is_no_lineage(
    ledger: ForwardOutcomeLedger,
) -> None:
    _save_mission("9001")
    row = _record(ledger, challenger="9999", verdict="won")
    assert row["lineage_status"] == "no_lineage"
    assert row["mission_id"] is None
    assert row["changes"] == {}
    assert row["scope"] == {}


def test_link_pending_links_rows_left_pending(ledger: ForwardOutcomeLedger) -> None:
    mission = _save_mission("9002")
    oid = outcome_id("bitpro", 107, "9002")
    with ledger.db.session() as session:
        session.add(
            ArcForwardOutcome(
                id=oid,
                target_id="bitpro",
                parent_strategy_id="107",
                challenger_strategy_id="9002",
                verdict="won",
                metrics_json={},
                lineage_status="pending",
            )
        )

    assert ledger.link_pending() == 1
    with ledger.db.session() as session:
        row = session.get(ArcForwardOutcome, oid)
        assert row is not None
        assert row.lineage_status == "linked"
        assert row.mission_id == mission.mission_id
    assert ledger.link_pending() == 0


def test_link_pending_matches_a_whole_batch_with_one_scan(
    ledger: ForwardOutcomeLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    missions = [_save_mission("9101"), _save_mission("9102"), _save_mission("9103")]
    for challenger in ("9101", "9102", "9103"):
        row = _record(ledger, challenger=challenger, verdict="won", link=False)
        assert row["lineage_status"] == "pending"

    loads: list[str] = []
    real_load = forward_outcomes.load_projection

    def counting_load(session, mission):
        loads.append(mission.mission_id)
        return real_load(session, mission)

    monkeypatch.setattr(forward_outcomes, "load_projection", counting_load)

    assert ledger.link_pending() == 3
    assert len(loads) <= 3
    with ledger.db.session() as session:
        rows = {
            row.challenger_strategy_id: row
            for row in session.scalars(select(ArcForwardOutcome)).all()
        }
    for mission, challenger in zip(missions, ("9101", "9102", "9103"), strict=True):
        assert rows[challenger].lineage_status == "linked"
        assert rows[challenger].mission_id == mission.mission_id


def test_link_stops_scanning_after_the_newest_match(
    ledger: ForwardOutcomeLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    missions = [_save_mission("9101"), _save_mission("9102"), _save_mission("9103")]
    with ledger.db.session() as session:
        for minutes, mission in enumerate(missions):
            stored = session.get(ArcMission, mission.mission_id)
            assert stored is not None
            stored.updated_at = datetime(2026, 1, 1, 0, minutes)

    row = _record(ledger, challenger="9103", verdict="won", link=False)
    loads: list[str] = []
    real_load = forward_outcomes.load_projection

    def counting_load(session, mission):
        loads.append(mission.mission_id)
        return real_load(session, mission)

    monkeypatch.setattr(forward_outcomes, "load_projection", counting_load)

    linked = ledger.link(row["id"])
    assert linked is not None
    assert linked["mission_id"] == missions[2].mission_id
    assert loads == [missions[2].mission_id]


def test_record_recovers_when_another_writer_inserted_first(
    ledger: ForwardOutcomeLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    oid = outcome_id("bitpro", 107, "9201")
    with ledger.db.session() as session:
        session.add(
            ArcForwardOutcome(
                id=oid,
                target_id="bitpro",
                parent_strategy_id="107",
                challenger_strategy_id="9201",
                verdict="ended_unknown",
                metrics_json={},
                evidence_sha256="stale",
                lineage_status="no_lineage",
            )
        )

    real_get = Session.get
    first = {"pending": True}

    def get_once_none(self, entity, ident, **kwargs):
        if first["pending"]:
            first["pending"] = False
            return None
        return real_get(self, entity, ident, **kwargs)

    monkeypatch.setattr(Session, "get", get_once_none)

    result = _record(
        ledger,
        challenger="9201",
        verdict="lost_exam",
        metrics={"excess_return_pct": -0.5},
    )
    assert result["verdict"] == "lost_exam"
    assert result["metrics"] == {"excess_return_pct": -0.5}
    with ledger.db.session() as session:
        rows = session.scalars(select(ArcForwardOutcome)).all()
    assert len(rows) == 1
    assert rows[0].verdict == "lost_exam"


def test_evidence_for_lineage_ancestors_zero_filters_sorts_and_limits(
    ledger: ForwardOutcomeLedger,
) -> None:
    _save_mission("9001", "9002", "9003", "9004", "9006")
    _record(
        ledger,
        challenger="9001",
        verdict="won",
        ended_at=datetime(2026, 1, 1),
    )
    _record(
        ledger,
        challenger="9002",
        verdict="lost_exam",
        ended_at=datetime(2026, 1, 3),
    )
    _record(
        ledger,
        challenger="9003",
        verdict="expired_timeout",
        ended_at=datetime(2026, 1, 4),
    )
    _record(
        ledger,
        challenger="9004",
        parent=108,
        verdict="lost_futility",
        ended_at=datetime(2026, 1, 2),
    )
    # Launched outside ARC research: concrete, but not lineage-linked evidence.
    _record(
        ledger,
        challenger="9005",
        verdict="won",
        ended_at=datetime(2026, 1, 5),
    )
    _record(ledger, challenger="9006", verdict="won", ended_at=None)

    results = ledger.evidence_for_lineage(target_id="bitpro", strategy_id=107, ancestors=0)
    assert [row["challenger_strategy_id"] for row in results] == ["9002", "9001", "9006"]
    assert all(row["verdict"] in EVIDENCE_VERDICTS for row in results)
    assert all(row["lineage_status"] == "linked" for row in results)
    # 9001 won, but it is not the id under research, so it is still a variant of it.
    assert all(row["relation"] == "variant_of_current" for row in results)
    assert all(row["generations_back"] == 0 for row in results)

    limited = ledger.evidence_for_lineage(
        target_id="bitpro", strategy_id=107, ancestors=0, limit=2
    )
    assert [row["challenger_strategy_id"] for row in limited] == ["9002", "9001"]


def test_evidence_for_lineage_walks_the_champion_chain(ledger: ForwardOutcomeLedger) -> None:
    _save_mission("101", "102", "1001", "1011", "1021", "9991", "1012")
    races = (
        (100, "1001", "lost_exam", datetime(2026, 1, 1)),
        (100, "101", "won", datetime(2026, 1, 2)),
        (101, "1011", "lost_futility", datetime(2026, 1, 3)),
        (101, "102", "won", datetime(2026, 1, 4)),
        (102, "1021", "lost_exam", datetime(2026, 1, 5)),
        # Other lineage, neutral ending and unlinked loss: never evidence here.
        (999, "9991", "won", datetime(2026, 1, 6)),
        (101, "1012", "superseded", datetime(2026, 1, 7)),
        (102, "1022", "lost_exam", datetime(2026, 1, 8)),
    )
    for parent, challenger, verdict, ended_at in races:
        _record(
            ledger,
            parent=parent,
            challenger=challenger,
            verdict=verdict,
            ended_at=ended_at,
        )

    results = ledger.evidence_for_lineage(target_id="bitpro", strategy_id="102", ancestors=3)
    assert [row["challenger_strategy_id"] for row in results] == [
        "1021",
        "102",
        "1011",
        "101",
        "1001",
    ]
    assert [
        (row["challenger_strategy_id"], row["relation"], row["generations_back"])
        for row in results
    ] == [
        ("1021", "variant_of_current", 0),
        ("102", "made_current", 1),
        ("1011", "variant_of_ancestor", 1),
        ("101", "made_ancestor", 2),
        ("1001", "variant_of_ancestor", 2),
    ]

    near = ledger.evidence_for_lineage(target_id="bitpro", strategy_id="102", ancestors=1)
    assert [row["challenger_strategy_id"] for row in near] == ["1021", "102", "1011"]

    # A corrupted won link back to the current champion must not loop forever.
    _record(
        ledger,
        parent=102,
        challenger="100",
        verdict="won",
        ended_at=datetime(2026, 1, 9),
    )
    cyclic = ledger.evidence_for_lineage(target_id="bitpro", strategy_id="102", ancestors=10)
    assert len(cyclic) == len({row["id"] for row in cyclic}) == 5


def test_summary_counts_verdicts_lineage_and_evidence(ledger: ForwardOutcomeLedger) -> None:
    _save_mission("9001", "9002", "9003", "9004")
    _record(ledger, challenger="9001", verdict="won")
    _record(ledger, challenger="9002", verdict="lost_futility")
    _record(ledger, challenger="9003", verdict="expired_timeout")
    _record(ledger, challenger="9004", verdict="ended_unknown")

    summary = ledger.summary()
    assert summary["total"] == 4
    assert summary["by_verdict"] == {
        "won": 1,
        "lost_futility": 1,
        "expired_timeout": 1,
        "ended_unknown": 1,
    }
    assert summary["by_lineage"] == {"linked": 4}
    assert summary["evidence"] == 2
    assert summary["last_recorded_at"] is not None


def test_summary_of_empty_ledger(ledger: ForwardOutcomeLedger) -> None:
    assert ledger.summary() == {
        "total": 0,
        "by_verdict": {},
        "by_lineage": {},
        "evidence": 0,
        "last_recorded_at": None,
    }


def _event_mission(db: Database, *challengers: str) -> ARCController:
    """A mission whose BitPro ids are bound by journalled events, not inline projection."""
    ctrl = ARCController(goal=ARCGoalV1(objective="race outcomes", symbols=["BTC-USDT"]))
    save_mission(ctrl)
    for index, challenger in enumerate(challengers):
        attempt = ARCCandidateAttemptV1(
            attempt_id=f"attempt-{challenger}",
            candidate_id=f"candidate-{challenger}",
            hypothesis=f"variant {challenger}",
            strategy_code="class Variant: pass\n",
            strategy_spec={
                "parameter_changes": {"fast_window": 10 + index},
                "structural_changes": {},
                "symbol": "BTC-USDT",
                "symbols": ["BTC-USDT"],
                "timeframe": "1H",
                "parent_strategy_id": 107,
            },
        )
        ctrl.apply_event("candidate_proposed", {"attempt": attempt.model_dump(mode="json")})
        ctrl.apply_event(
            "bitpro_self_tested",
            {
                "attempt_id": attempt.attempt_id,
                "bitpro_strategy_id": challenger,
                "backtest_id": "bt-1",
                "passed": False,
            },
        )
    with db.session() as session:
        event_types = set(
            session.scalars(
                select(ArcMissionEvent.event_type).where(
                    ArcMissionEvent.mission_id == ctrl.mission_id
                )
            ).all()
        )
    assert {"candidate_proposed", "bitpro_self_tested"} <= event_types
    return ctrl


def test_lineage_finds_a_mission_that_fell_out_of_the_scan_window(
    ledger: ForwardOutcomeLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _event_mission(ledger.db, "9301")
    newer = [_save_mission("9401"), _save_mission("9402"), _save_mission("9403")]
    with ledger.db.session() as session:
        stored = session.get(ArcMission, old.mission_id)
        assert stored is not None
        stored.updated_at = datetime(2026, 1, 1)
        for hour, mission in enumerate(newer, start=1):
            row = session.get(ArcMission, mission.mission_id)
            assert row is not None
            row.updated_at = datetime(2026, 2, 1, hour)

    loads: list[str] = []
    real_load = forward_outcomes.load_projection

    def counting_load(session: Session, mission: ArcMission):
        loads.append(mission.mission_id)
        return real_load(session, mission)

    monkeypatch.setattr(forward_outcomes, "load_projection", counting_load)

    narrow = ForwardOutcomeLedger(ledger.db, mission_scan_limit=2)
    row = _record(narrow, challenger="9301", verdict="won")
    assert row["lineage_status"] == "linked"
    assert row["mission_id"] == old.mission_id
    assert row["changes"] == {
        "parameter_changes": {"fast_window": 10},
        "structural_changes": {},
    }
    assert loads == [old.mission_id]


def test_lineage_prefers_the_newest_mission_for_a_reused_challenger_id(
    ledger: ForwardOutcomeLedger,
) -> None:
    _event_mission(ledger.db, "9302")
    newest = _event_mission(ledger.db, "9302")

    row = _record(ledger, challenger="9302", verdict="won")
    assert row["lineage_status"] == "linked"
    assert row["mission_id"] == newest.mission_id
    assert row["attempt_id"] == "attempt-9302"


def test_event_scan_can_be_disabled_and_falls_back_to_mission_scan(
    ledger: ForwardOutcomeLedger,
) -> None:
    mission = _event_mission(ledger.db, "9303")
    blind = ForwardOutcomeLedger(ledger.db, event_scan_limit=0)

    row = _record(blind, challenger="9303", verdict="won")
    assert row["lineage_status"] == "linked"
    assert row["mission_id"] == mission.mission_id


def test_malformed_event_payload_never_breaks_lineage(
    ledger: ForwardOutcomeLedger,
) -> None:
    with ledger.db.session() as session:
        session.add(
            ArcMissionEvent(
                mission_id="arc_malformed",
                seq=1,
                event_id="evt_malformed",
                event_type="bitpro_self_tested",
                event_json={"payload": "not a dict"},
            )
        )

    row = _record(ledger, challenger="9399", verdict="won")
    assert row["lineage_status"] == "no_lineage"


def test_lineage_links_a_numeric_event_challenger_id(
    ledger: ForwardOutcomeLedger,
) -> None:
    # Some payloads carry BitPro ids as JSON numbers. The attempt projection only accepts
    # strings, so it is persisted inline and the number exists only in the event journal.
    ctrl = _save_mission("9401")
    ctrl.apply_event(
        "bitpro_self_tested",
        {"bitpro_strategy_id": 9401, "backtest_id": "bt-1", "passed": False},
    )

    # Disable the fallback mission scan so only the event-index lookup can match.
    event_only = ForwardOutcomeLedger(ledger.db, mission_scan_limit=0)
    row = _record(event_only, challenger="9401", verdict="won")
    assert row["lineage_status"] == "linked"
    assert row["mission_id"] == ctrl.mission_id
    assert row["attempt_id"] == "attempt-9401"
