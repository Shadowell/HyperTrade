"""Per-change ablation: development-window replay of a forward loser's changes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypertrade.arc import ablation
from hypertrade.arc.ablation import ablation_once, schedule_runs
from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionConfig
from hypertrade.arc.evolution_models import (
    ArcAblationRun,
    ArcAblationStep,
    ArcForwardOutcome,
    EvolutionControl,
)
from hypertrade.arc.forward_outcomes import outcome_id
from hypertrade.arc.research_budget import budget_status
from hypertrade.arc.store import configure_store, reset_store, save_mission
from hypertrade.db import ArcMission, Database
from sqlalchemy import func, select

M = "a" * 64
E = "b" * 64
DATA = "e" * 64
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    try:
        yield database
    finally:
        reset_store()


def _seed_loser(
    db: Database,
    *,
    challenger: str = "9101",
    parameter_changes: dict[str, Any] | None = None,
    structural_changes: dict[str, Any] | None = None,
    verdict: str = "lost_futility",
    lineage: str = "linked",
    variant: bool = True,
) -> str:
    parameters = (
        dict(parameter_changes) if parameter_changes is not None else {"fast": 12, "slow": 40}
    )
    structural = (
        dict(structural_changes)
        if structural_changes is not None
        else {"vol_filter": {"window": 20}}
    )
    baseline = ARCCandidateAttemptV1(
        attempt_id="baseline_443",
        candidate_id="baseline_443",
        hypothesis="不可变的原策略比较基线",
        strategy_code="class Parent: pass\n",
        strategy_spec={
            "symbol": "BTC-USDT-SWAP",
            "timeframe": "1H",
            "baseline_config": {"fast": 10, "slow": 30},
            "is_source_variant": True,
            "parent_strategy_id": 443,
            "parent_manifest_sha256": M,
            "parent_execution_identity_sha256": E,
        },
    )
    goal = ARCGoalV1(
        objective="evolve 443",
        research_mode="avo",
        paper_review_required=True,
        symbols=["BTC-USDT-SWAP"],
        timeframes=["1H"],
        paper_initial_equity=Decimal("100"),
        evolution_context={
            "source_strategy_id": 443,
            "baseline": baseline.model_dump(mode="json"),
        },
    )
    controller = ARCController(goal=goal)
    spec: dict[str, Any] = {
        **baseline.strategy_spec,
        "parameter_changes": parameters,
        "structural_changes": structural,
        "variation_operator": "avo",
    }
    if variant:
        spec.update(
            {
                "is_source_variant": True,
                "parent_strategy_id": 443,
                "parent_manifest_sha256": M,
                "parent_execution_identity_sha256": E,
            }
        )
    else:
        for key in (
            "is_source_variant",
            "parent_strategy_id",
            "parent_manifest_sha256",
            "parent_execution_identity_sha256",
        ):
            spec.pop(key, None)
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_901",
        candidate_id="cand_901",
        hypothesis="narrow the entry window",
        strategy_code=baseline.strategy_code,
        strategy_spec=spec,
        bitpro_strategy_id=challenger,
    )
    controller.projection.attempts.append(attempt)
    save_mission(controller)
    oid = outcome_id("bitpro", 443, challenger)
    with db.session() as session:
        session.add(
            ArcForwardOutcome(
                id=oid,
                target_id="bitpro",
                parent_strategy_id="443",
                challenger_strategy_id=challenger,
                verdict=verdict,
                lineage_status=lineage,
                mission_id=controller.mission_id,
                candidate_id=attempt.candidate_id,
                attempt_id=attempt.attempt_id,
                changes_json={
                    "parameter_changes": parameters,
                    "structural_changes": structural,
                },
                scope_json={},
                ended_at=NOW - timedelta(hours=1),
                metrics_json={},
            )
        )
    return oid


class FakeBitPro:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.relay: dict[str, Any] = {}
        self.policy_execution_identity = E
        self.default_status = "completed"
        self.status: dict[str, str] = {}
        self.fail_when: Callable[[dict[str, Any]], bool] | None = None
        self.cost_hash_when: Callable[[dict[str, Any]], str | None] | None = None
        self.created = 0
        self.jobs: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, str] = {}
        self.variants: dict[int, tuple[dict[str, int], dict[str, Any]]] = {}
        self.candidate_seq = 5000

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected BitPro call: {name}")

    def strategy_research_variant_policy(self, *, strategy_id: int) -> dict[str, Any]:
        self.calls.append(("policy", strategy_id))
        return {
            "contract_version": "strategy_research_variant_policy.v1",
            "parent_strategy_id": strategy_id,
            "variant_creation_supported": True,
            "authorized_parameters": [],
            "parent_manifest_sha256": M,
            "parent_execution_identity_sha256": self.policy_execution_identity,
            "relay": dict(self.relay),
        }

    def strategy_research_variant_create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("variant_create", kwargs))
        assert kwargs["purpose"] in {"candidate", "baseline"}
        key = kwargs["idempotency_key"]
        if key not in self.by_key:
            self.candidate_seq += 1
            self.by_key[key] = str(self.candidate_seq)
            self.variants[self.candidate_seq] = (
                dict(kwargs["parameter_changes"]),
                dict(kwargs.get("structural_changes") or {}),
            )
        candidate = int(self.by_key[key])
        return {
            "contract_version": "strategy_research_variant.v1",
            "candidate_strategy_id": candidate,
            "purpose": kwargs["purpose"],
            "status": "stopped",
            "parameter_changes": kwargs["parameter_changes"],
            "structural_changes": kwargs.get("structural_changes") or {},
            "parent_strategy_id": kwargs["strategy_id"],
        }

    def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("backtest_start", kwargs))
        key = kwargs["idempotency_key"]
        if key not in self.by_key:
            self.created += 1
            job_id = f"job-{self.created}"
            self.by_key[key] = job_id
            self.jobs[job_id] = dict(kwargs)
        job_id = self.by_key[key]
        return {
            "job": {
                "job_id": job_id,
                "input_snapshot_hash": "sha256:" + "c" * 64,
                "strategy_id": kwargs["strategy_id"],
                "status": "queued",
            }
        }

    def _metrics(self, strategy_id: int) -> dict[str, Any]:
        parameters, structural = self.variants.get(strategy_id, ({}, {}))
        if parameters == {"slow": 40} and not structural:
            return {
                "total_return_pct": 12.0,
                "max_drawdown_pct": 7.5,
                "trade_count": 41,
                "sharpe_ratio": 1.3,
            }
        if parameters == {"fast": 12} and not structural:
            return {
                "total_return_pct": 7.0,
                "max_drawdown_pct": 8.2,
                "trade_count": 38,
                "sharpe_ratio": 0.8,
            }
        if structural:
            return {
                "total_return_pct": 10.2,
                "max_drawdown_pct": 8.1,
                "trade_count": 36,
                "sharpe_ratio": 1.1,
            }
        return {
            "total_return_pct": 10.0,
            "max_drawdown_pct": 8.0,
            "trade_count": 40,
            "sharpe_ratio": 1.1,
        }

    def backtest_get_job(self, *, job_id: str) -> dict[str, Any]:
        self.calls.append(("backtest_get", job_id))
        request = self.jobs[job_id]
        status = self.status.get(job_id, self.default_status)
        if self.fail_when is not None and self.fail_when(request):
            status = "failed"
        cost_hash = "d" * 64
        if self.cost_hash_when is not None:
            cost_hash = self.cost_hash_when(request) or cost_hash
        return {
            "job": {
                "job_id": job_id,
                "strategy_id": request["strategy_id"],
                "status": status,
                "input_snapshot_hash": "sha256:" + "c" * 64,
                "updated_at": "2026-10-21T00:00:00Z",
                "strategy_input_snapshot": {
                    "runtime_sha256": "r" * 64,
                    "cost_policy_hash": cost_hash,
                    "initial_capital": 100.0,
                    "symbols": ["BTC-USDT-SWAP"],
                    "timeframes": ["1H"],
                    "start_date": request["start_date"],
                    "end_date": request["end_date"],
                },
                "verified_data_binding": {
                    "entries": [
                        {
                            "verified_snapshot_id": "vbs_" + DATA,
                            "manifest_sha256": DATA,
                        }
                    ]
                },
            },
            "backtest_result": (
                {
                    "id": f"bt-{job_id}",
                    "metrics": self._metrics(request["strategy_id"]),
                }
                if status == "completed"
                else None
            ),
        }

    def backtest_resume_job(self, *, job_id: str, idempotency_key: str) -> dict[str, Any]:
        self.calls.append(("backtest_resume", job_id))
        self.status[job_id] = "running"
        return {"job": self.backtest_get_job(job_id=job_id)["job"]}


def _runs(db: Database) -> list[ArcAblationRun]:
    with db.session() as session:
        return list(session.scalars(select(ArcAblationRun)))


def _run(db: Database, challenger: str) -> ArcAblationRun:
    with db.session() as session:
        row = session.scalars(
            select(ArcAblationRun).where(
                ArcAblationRun.challenger_strategy_id == challenger
            )
        ).one()
        return row


def _steps(db: Database, run_id: str) -> list[ArcAblationStep]:
    with db.session() as session:
        return list(
            session.scalars(
                select(ArcAblationStep)
                .where(ArcAblationStep.run_id == run_id)
                .order_by(ArcAblationStep.ordinal.asc())
            )
        )


def _charged(db: Database) -> int:
    with db.session() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(ArcAblationStep)
                .where(ArcAblationStep.charged_at.is_not(None))
            )
            or 0
        )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _run_until_done(
    db: Database, fake: FakeBitPro, challenger: str, *, start: datetime = NOW
) -> ArcAblationRun:
    moment = start
    for _ in range(12):
        ablation_once(db, now=moment, client=fake)
        run = _run(db, challenger)
        if run.status in {"completed", "failed", "skipped"}:
            return run
        moment += timedelta(minutes=5)
    raise AssertionError(f"run for {challenger} did not finish")


def _by_label(run: ArcAblationRun, label: str) -> dict[str, Any]:
    return next(effect for effect in run.result_json["effects"] if effect["label"] == label)


def test_only_linked_system_losers_with_two_or_more_changes_are_scheduled(db: Database) -> None:
    _seed_loser(db, challenger="9001", verdict="won")
    _seed_loser(
        db, challenger="9002", parameter_changes={"fast": 12}, structural_changes={}
    )
    _seed_loser(db, challenger="9003", verdict="lost_exam")
    _seed_loser(db, challenger="9004", verdict="cancelled_operator")
    _seed_loser(db, challenger="9005", verdict="expired_timeout")
    _seed_loser(db, challenger="9006", verdict="superseded")
    _seed_loser(db, challenger="9007", verdict="cancelled_unknown")
    _seed_loser(db, challenger="9008", lineage="no_lineage")
    fake = FakeBitPro()

    result = ablation_once(db, now=NOW, client=fake)

    assert result["scheduled"] == {
        "created": 1,
        "single_change": 1,
        "already_scheduled": 0,
    }
    assert [run.challenger_strategy_id for run in _runs(db)] == ["9003"]
    again = schedule_runs(db, EvolutionConfig(), NOW)
    assert again == {"created": 0, "single_change": 1, "already_scheduled": 1}
    ablation_once(db, now=NOW + timedelta(minutes=5), client=fake)
    assert len(_runs(db)) == 1


def test_full_run_backtests_baseline_and_each_change_on_the_development_window(
    db: Database,
) -> None:
    _seed_loser(db)
    fake = FakeBitPro()

    run = _run_until_done(db, fake, "9101")

    assert run.status == "completed"
    assert fake.created == 4
    creates = [call[1] for call in fake.calls if call[0] == "variant_create"]
    assert len(creates) == 4
    assert [entry["purpose"] for entry in creates].count("baseline") == 1
    start, end = ResearchWindowsV1(
        as_of=NOW.date() - timedelta(days=1)
    ).window("development")
    requests = [call[1] for call in fake.calls if call[0] == "backtest_start"]
    assert len(requests) == 4
    for request in requests:
        assert request["start_date"] == start.isoformat()
        assert request["end_date"] == end.isoformat()
    changed = {
        candidate
        for candidate, (parameters, structural) in fake.variants.items()
        if parameters or structural
    }
    for request in requests:
        if request["strategy_id"] in changed:
            assert request["verified_data_snapshot_id"] == "vbs_" + DATA
            assert request["verified_data_manifest_sha256"] == DATA

    effects = run.result_json["effects"]
    assert [effect["label"] for effect in effects] == [
        "fast=12",
        effects[1]["label"],
        "slow=40",
    ]
    assert effects[1]["label"].startswith("vol_filter:")
    assert [effect["class"] for effect in effects] == ["harmful", "neutral", "helpful"]
    assert run.result_json["harmful"] == ["fast=12"]
    assert run.result_json["helpful"] == ["slow=40"]
    assert run.result_json["neutral"] == [effects[1]["label"]]
    assert run.result_json["causal_claim_verified"] is False
    assert run.result_json["note"]
    assert _charged(db) == 4


def test_pending_job_resumes_without_new_job_or_second_charge(db: Database) -> None:
    _seed_loser(db)
    fake = FakeBitPro()
    fake.default_status = "running"

    ablation_once(db, now=NOW, client=fake)
    pending = _run(db, "9101")
    assert pending.reason == "backtest_pending"
    assert fake.created == 1
    assert _charged(db) == 1

    # Simulate a restart: the database survives, every in-process object does not.
    reset_store()
    configure_store(db)
    fake.default_status = "completed"

    moment = NOW + timedelta(hours=2)
    for _ in range(12):
        ablation_once(db, now=moment, client=fake)
        if _run(db, "9101").status == "completed":
            break
        moment += timedelta(minutes=10)

    finished = _run(db, "9101")
    assert finished.status == "completed"
    assert fake.created == 4
    assert _charged(db) == 4


def test_crash_after_job_created_before_checkpoint_does_not_double_create_or_charge(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_loser(db)
    fake = FakeBitPro()
    original = ablation._record_submitted
    calls = {"count": 0}

    class Crash(BaseException):
        pass

    def crash_once(
        database: Database, step_id: str, job: dict[str, Any], now: datetime
    ) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise Crash()
        original(database, step_id, job, now)

    monkeypatch.setattr(ablation, "_record_submitted", crash_once)
    with pytest.raises(Crash):
        ablation_once(db, now=NOW, client=fake)
    assert fake.created == 1
    assert _charged(db) == 0

    monkeypatch.setattr(ablation, "_record_submitted", original)
    run = _run_until_done(db, fake, "9101")

    assert run.status == "completed"
    assert fake.created == 4
    assert _charged(db) == 4
    assert not run.result_json.get("runtime_errors")


def test_daily_budget_cap_pauses_until_next_utc_midnight(db: Database) -> None:
    _seed_loser(db)
    with db.session() as session:
        session.add(
            EvolutionControl(
                id="global", config_json={"ablation_max_backtests_per_day": 2}
            )
        )
    fake = FakeBitPro()

    ablation_once(db, now=NOW, client=fake)
    assert fake.created == 2
    ablation_once(db, now=NOW, client=fake)
    paused = _run(db, "9101")
    assert paused.reason == "daily_budget_exhausted"
    assert _aware(paused.next_check_at) == datetime(2026, 10, 22, 0, tzinfo=UTC)
    assert fake.created == 2

    tomorrow = NOW + timedelta(days=1)
    for _ in range(6):
        ablation_once(db, now=tomorrow, client=fake)
        if _run(db, "9101").status == "completed":
            break
        tomorrow += timedelta(minutes=5)

    assert _run(db, "9101").status == "completed"
    assert fake.created == 4


def test_loser_needing_more_backtests_than_the_per_loser_cap_is_skipped_without_bitpro_calls(
    db: Database,
) -> None:
    _seed_loser(
        db,
        parameter_changes={f"p{index}": index + 1 for index in range(6)},
        structural_changes={},
    )
    fake = FakeBitPro()

    ablation_once(db, now=NOW, client=fake)

    run = _run(db, "9101")
    assert run.status == "skipped"
    assert run.reason == "too_many_changes"
    assert "7" in run.message and "6" in run.message
    assert fake.calls == []


def test_parent_change_skips_and_seat_hold_waits_with_visible_reasons(db: Database) -> None:
    _seed_loser(db, challenger="9101")
    changed = FakeBitPro()
    changed.policy_execution_identity = "c" * 64

    ablation_once(db, now=NOW, client=changed)
    run = _run(db, "9101")
    assert run.status == "skipped"
    assert run.reason == "parent_changed_since_race"
    assert len(changed.calls) == 1

    _seed_loser(db, challenger="9102")
    held = FakeBitPro()
    held.relay = {"blocks_evolution": True, "reason": "3 个变体位已占满"}

    ablation_once(db, now=NOW, client=held)
    waiting = _run(db, "9102")
    assert waiting.status == "pending"
    assert waiting.reason == "parent_relay_hold"
    assert "3 个变体位已占满" in waiting.message
    assert _aware(waiting.next_check_at) == NOW + timedelta(hours=1)

    ablation_once(db, now=NOW + timedelta(days=8), client=held)
    timed_out = _run(db, "9102")
    assert timed_out.status == "failed"
    assert timed_out.reason == "parent_relay_hold_timeout"


def test_baseline_failure_fails_run_and_single_failure_is_unknown_not_zero(
    db: Database,
) -> None:
    _seed_loser(db, challenger="9101")
    fake = FakeBitPro()
    fake.default_status = "failed"

    ablation_once(db, now=NOW, client=fake)
    failed = _run(db, "9101")
    assert failed.status == "failed"
    assert failed.reason
    assert fake.created == 1

    # A fresh store keeps the first scenario's failed jobs out of the cross-run reuse map.
    second = Database("sqlite:///:memory:")
    second.create_all()
    configure_store(second)
    try:
        _seed_loser(second, challenger="9102")
        other = FakeBitPro()

        def fail_fast(request: dict[str, Any]) -> bool:
            parameters, structural = other.variants.get(request["strategy_id"], ({}, {}))
            return parameters == {"fast": 12} and not structural

        other.fail_when = fail_fast
        _run_until_done(second, other, "9102")
        finished = _run(second, "9102")
    finally:
        configure_store(db)
    assert finished.status == "completed"
    fast = _by_label(finished, "fast=12")
    assert fast["class"] == "unknown"
    assert fast["delta_net_return"] is None
    assert fast["delta_max_drawdown"] is None
    assert fast["delta_trade_count"] is None
    assert fast["reason"]


def test_mismatched_execution_evidence_is_incomparable(db: Database) -> None:
    _seed_loser(db)
    fake = FakeBitPro()

    def slow_cost(request: dict[str, Any]) -> str | None:
        parameters, structural = fake.variants.get(request["strategy_id"], ({}, {}))
        return "f" * 64 if parameters == {"slow": 40} and not structural else None

    fake.cost_hash_when = slow_cost
    _run_until_done(db, fake, "9101")

    run = _run(db, "9101")
    slow = _by_label(run, "slow=40")
    assert slow["class"] == "incomparable"
    assert slow["reason"]
    assert slow["delta_net_return"] is None
    assert "slow=40" in run.result_json["incomparable"]


def test_same_change_across_two_losers_of_the_same_parent_reuses_jobs_without_charge(
    db: Database,
) -> None:
    _seed_loser(
        db,
        challenger="9101",
        parameter_changes={"fast": 12, "slow": 40},
        structural_changes={},
    )
    fake = FakeBitPro()
    first = _run_until_done(db, fake, "9101")
    assert first.status == "completed"
    assert fake.created == 3

    _seed_loser(
        db,
        challenger="9102",
        parameter_changes={"fast": 12},
        structural_changes={"vol_filter": {"window": 20}},
    )
    second = _run_until_done(db, fake, "9102")
    assert second.status == "completed"
    assert fake.created == 4
    assert _charged(db) == 4

    first_steps = {step.step_key: step for step in _steps(db, first.id)}
    second_steps = {step.step_key: step for step in _steps(db, second.id)}
    for key in ("baseline", "param:fast"):
        reused = second_steps[key]
        assert reused.charged_at is None
        assert reused.checkpoint_json["reused_from"] == first_steps[key].id
    assert second_steps["struct:vol_filter"].charged_at is not None


def test_ablation_never_touches_paper_incubation_missions_or_research_budget(
    db: Database,
) -> None:
    _seed_loser(db)
    fake = FakeBitPro()
    with db.session() as session:
        missions_before = int(session.scalar(select(func.count()).select_from(ArcMission)) or 0)
    budget_before = budget_status(db, EvolutionConfig(), NOW)["period_used"]

    run = _run_until_done(db, fake, "9101")

    assert run.status == "completed"
    assert not run.result_json.get("runtime_errors")
    with db.session() as session:
        missions_after = int(session.scalar(select(func.count()).select_from(ArcMission)) or 0)
    assert missions_after == missions_before
    assert budget_status(db, EvolutionConfig(), NOW)["period_used"] == budget_before
    assert {call[0] for call in fake.calls} <= {
        "policy",
        "variant_create",
        "backtest_start",
        "backtest_get",
    }
    purposes = [call[1]["purpose"] for call in fake.calls if call[0] == "variant_create"]
    assert purposes and set(purposes) <= {"candidate", "baseline"}


@pytest.mark.parametrize(
    "config",
    [
        {"ablation_enabled": False},
        {"enabled": False},
        {"target_id": "quantlab"},
    ],
)
def test_disabled_or_non_bitpro_config_does_nothing(
    db: Database, config: dict[str, Any]
) -> None:
    _seed_loser(db)
    with db.session() as session:
        session.add(EvolutionControl(id="global", config_json=config))
    fake = FakeBitPro()

    result = ablation_once(db, now=NOW, client=fake)

    assert result == {"status": "disabled"}
    assert _runs(db) == []
    assert fake.calls == []


def test_missing_lineage_fails_and_non_variant_is_skipped(db: Database) -> None:
    oid = _seed_loser(db, challenger="9101")
    with db.session() as session:
        row = session.get(ArcForwardOutcome, oid)
        assert row is not None
        row.mission_id = "missing-mission"
    fake = FakeBitPro()

    ablation_once(db, now=NOW, client=fake)
    failed = _run(db, "9101")
    assert failed.status == "failed"
    assert failed.reason == "lineage_unavailable"
    assert fake.calls == []

    _seed_loser(db, challenger="9102", variant=False)
    other = FakeBitPro()
    ablation_once(db, now=NOW, client=other)
    skipped = _run(db, "9102")
    assert skipped.status == "skipped"
    assert skipped.reason == "not_source_variant"
    assert other.calls == []
