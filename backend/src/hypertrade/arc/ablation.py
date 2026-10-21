"""Per-change ablation of forward losers on the development window.

For a challenger the race judge recorded as a loser (``lost_futility`` / ``lost_exam``)
this replays the parent, then the parent plus exactly one of the challenger's changes,
on the frozen development window. The goal is a neutral observation record for the next
research round: which single change looked harmful and which looked helpful.

Boundaries:
- Backtests only. No Paper, incubation or live call is reachable from this module.
- Variants are created as stopped research rows without Paper review bindings, so BitPro
  never enrolls them in the race.
- Only the development window is requested; the final window is never read.
- The daily budget is independent of the daily research quota.

The conclusion is a single-factor effect inside one development window. It contains no
interaction between changes and is not a causal claim.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, NoReturn

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from hypertrade.arc.backtest_recovery import (
    PENDING_BACKTEST_STATES,
    BacktestDeferred,
)
from hypertrade.arc.backtest_recovery import (
    digest as backtest_digest,
)
from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.evolution_models import (
    ArcAblationRun,
    ArcAblationStep,
    ArcForwardOutcome,
    EvolutionControl,
)
from hypertrade.arc.feedback import compare_backtests
from hypertrade.arc.runtime_journal import failure_text, record_runtime_error
from hypertrade.arc.self_test import ARCSelfTestService, _fraction, _number
from hypertrade.arc.store import research_lock
from hypertrade.db import ArcMission, Database

LOSER_VERDICTS = ("lost_futility", "lost_exam")
NEW_RUNS_PER_TICK = 5
STEPS_PER_TICK = 2
HOLD_LIMIT = timedelta(days=7)  # parent seat / policy hold, not a job failure
JOB_WAIT_LIMIT = timedelta(hours=24)  # one job from creation to a terminal state
MAX_RUNTIME_ERRORS = 5
# Descriptive noise band in return/drawdown fractions (0.005 = 0.5 percentage points).
# These are observation labels, not a significance test.
HELPFUL_RETURN = 0.005
HARMFUL_RETURN = -0.005
HELPFUL_DRAWDOWN_SLACK = 0.005
HARMFUL_DRAWDOWN = 0.01
NOTE = (
    "开发窗口内单因素效应：每次只把一处改动单独加到母体上测，"
    "不含改动之间的交互，不是因果结论"
)


class AblationBudgetDeferred(BacktestDeferred):
    """Today's ablation backtest allowance is used up; a wait, not a failure."""


def change_list(changes: Any) -> list[dict[str, Any]]:
    """Flatten ``parameter_changes``/``structural_changes`` into stable ordered rows."""
    source = changes if isinstance(changes, dict) else {}
    parameters = source.get("parameter_changes")
    structural = source.get("structural_changes")
    rows: list[dict[str, Any]] = []
    if isinstance(parameters, dict):
        for key in sorted(parameters, key=lambda item: str(item)):
            value = parameters[key]
            if value is None:
                continue
            rows.append({"kind": "parameter", "key": key, "value": value})
    if isinstance(structural, dict):
        for key in sorted(structural, key=lambda item: str(item)):
            rows.append({"kind": "structural", "key": key, "value": structural[key]})
    return rows


def change_count(changes: Any) -> int:
    return len(change_list(changes))


def run_id_for(target_id: str, challenger_strategy_id: object) -> str:
    body = json.dumps(
        [target_id, str(challenger_strategy_id)], separators=(",", ":")
    ).encode()
    return "abl_" + hashlib.sha256(body).hexdigest()[:32]


def step_key_for(change: dict[str, Any] | None) -> str:
    if change is None:
        return "baseline"
    kind = "param" if change.get("kind") == "parameter" else "struct"
    return f"{kind}:{change.get('key')}"


def step_id_for(run_id: str, step_key: str) -> str:
    body = json.dumps([run_id, step_key], separators=(",", ":")).encode()
    return "abs_" + hashlib.sha256(body).hexdigest()[:32]


def change_label(change: dict[str, Any]) -> str:
    key = change.get("key")
    if change.get("kind") == "parameter":
        return f"{key}={change.get('value')}"
    encoded = json.dumps(change.get("value"), sort_keys=True, ensure_ascii=False)
    return f"{key}:{encoded[:80]}"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def next_utc_midnight(now: datetime) -> datetime:
    moment = _utc(now)
    assert moment is not None
    return moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _spec_symbols(spec: dict[str, Any]) -> list[str]:
    declared = spec.get("symbols")
    if isinstance(declared, (list, tuple)):
        values = [
            value.strip() for value in declared if isinstance(value, str) and value.strip()
        ]
        if len(values) == len(declared) and values:
            return list(dict.fromkeys(values))
        return []
    single = spec.get("symbol")
    return [single.strip()] if isinstance(single, str) and single.strip() else []


def _write_run(db: Database, run_id: str, **values: Any) -> None:
    with db.session() as session:
        row = session.get(ArcAblationRun, run_id)
        if row is None:
            return
        for key, value in values.items():
            setattr(row, key, value)


def _write_step(db: Database, step_id: str, **values: Any) -> None:
    with db.session() as session:
        row = session.get(ArcAblationStep, step_id)
        if row is None:
            return
        for key, value in values.items():
            setattr(row, key, value)


def _get_run(db: Database, run_id: str) -> ArcAblationRun | None:
    with db.session() as session:
        return session.get(ArcAblationRun, run_id)


def _get_step(db: Database, step_id: str) -> ArcAblationStep | None:
    with db.session() as session:
        return session.get(ArcAblationStep, step_id)


def _step_checkpoint(db: Database, step_id: str) -> dict[str, Any]:
    step = _get_step(db, step_id)
    return dict(step.checkpoint_json or {}) if step is not None else {}


def _step_rows(db: Database, run_id: str) -> list[ArcAblationStep]:
    with db.session() as session:
        return list(
            session.scalars(
                select(ArcAblationStep)
                .where(ArcAblationStep.run_id == run_id)
                .order_by(ArcAblationStep.ordinal.asc())
            )
        )


def _baseline_step(db: Database, run_id: str) -> ArcAblationStep | None:
    return next((step for step in _step_rows(db, run_id) if step.kind == "baseline"), None)


def _daily_charged(db: Database, now: datetime) -> int:
    moment = _utc(now)
    assert moment is not None
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    with db.session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ArcAblationStep)
            .where(
                ArcAblationStep.charged_at.is_not(None),
                ArcAblationStep.charged_at >= start,
                ArcAblationStep.charged_at < end,
            )
        )
    return int(count or 0)


def _find_reusable(
    db: Database, step_id: str, request_hash: str | None
) -> dict[str, Any] | None:
    """Another step's job for the same request is free; identity is the request hash."""
    if not request_hash:
        return None
    with db.session() as session:
        rows = list(
            session.scalars(
                select(ArcAblationStep)
                .where(
                    ArcAblationStep.request_hash == request_hash,
                    ArcAblationStep.id != step_id,
                )
                .order_by(ArcAblationStep.created_at.asc())
                .limit(50)
            )
        )
    for row in rows:
        checkpoint = dict(row.checkpoint_json or {})
        if checkpoint.get("job_id") and checkpoint.get("input_snapshot_hash"):
            return {
                "id": row.id,
                "job_id": checkpoint["job_id"],
                "input_snapshot_hash": checkpoint["input_snapshot_hash"],
                "created_at": checkpoint.get("created_at"),
            }
    return None


def schedule_runs(db: Database, config: Any, now: datetime) -> dict[str, int]:
    """Create one pending run per new linked loser; one bad row never rolls back the batch."""
    counts = {"created": 0, "single_change": 0, "already_scheduled": 0}
    with db.session() as session:
        rows = list(
            session.scalars(
                select(ArcForwardOutcome)
                .where(
                    ArcForwardOutcome.target_id == config.target_id,
                    ArcForwardOutcome.verdict.in_(LOSER_VERDICTS),
                    ArcForwardOutcome.lineage_status == "linked",
                )
                .order_by(
                    case((ArcForwardOutcome.ended_at.is_(None), 1), else_=0),
                    ArcForwardOutcome.ended_at.desc(),
                    ArcForwardOutcome.created_at.desc(),
                )
                .limit(200)
            )
        )
        outcome_rows: list[dict[str, Any]] = [
            {
                "id": row.id,
                "outcome_id": row.id,
                "target_id": row.target_id,
                "parent_strategy_id": row.parent_strategy_id,
                "challenger_strategy_id": row.challenger_strategy_id,
                "changes": dict(row.changes_json or {}),
            }
            for row in rows
        ]
        existing = {
            (target_id, str(challenger))
            for target_id, challenger in session.execute(
                select(
                    ArcAblationRun.target_id, ArcAblationRun.challenger_strategy_id
                ).where(ArcAblationRun.target_id == config.target_id)
            ).all()
        }
    for row in outcome_rows:
        pair = (row["target_id"], str(row["challenger_strategy_id"]))
        if pair in existing:
            counts["already_scheduled"] += 1
            continue
        if change_count(row["changes"]) < 2:
            counts["single_change"] += 1
            continue
        if counts["created"] >= NEW_RUNS_PER_TICK:
            break
        run_id = run_id_for(row["target_id"], row["challenger_strategy_id"])
        try:
            with db.session() as session:
                session.add(
                    ArcAblationRun(
                        id=run_id,
                        outcome_id=row["outcome_id"],
                        target_id=row["target_id"],
                        parent_strategy_id=row["parent_strategy_id"],
                        challenger_strategy_id=str(row["challenger_strategy_id"]),
                        status="pending",
                        next_check_at=_utc(now),
                    )
                )
                session.flush()
        except IntegrityError:
            # A concurrent scheduler inserted this pair first; the unique pair wins.
            existing.add(pair)
            counts["already_scheduled"] += 1
            continue
        existing.add(pair)
        counts["created"] += 1
    return counts


def _finish(
    db: Database,
    run_id: str,
    status: str,
    reason: str,
    *,
    message: str = "",
    now: datetime | None = None,
    **extra: Any,
) -> None:
    values: dict[str, Any] = {
        "status": status,
        "reason": reason[:64],
        "message": message[:2000],
        "next_check_at": None,
    }
    if now is not None:
        values["finished_at"] = now
    values.update(extra)
    _write_run(db, run_id, **values)


def _skipped(
    db: Database, run_id: str, reason: str, message: str, now: datetime
) -> None:
    _finish(db, run_id, "skipped", reason, message=message, now=now)


def _ensure_steps(db: Database, run_id: str, changes: list[dict[str, Any]]) -> None:
    entries: list[dict[str, Any] | None] = [None, *changes]
    for ordinal, change in enumerate(entries):
        key = step_key_for(change)
        step_id = step_id_for(run_id, key)
        try:
            with db.session() as session:
                if session.get(ArcAblationStep, step_id) is not None:
                    continue
                session.add(
                    ArcAblationStep(
                        id=step_id,
                        run_id=run_id,
                        step_key=key,
                        ordinal=ordinal,
                        kind="baseline" if change is None else "single",
                        change_json=change or {},
                        status="pending",
                    )
                )
                session.flush()
        except IntegrityError:
            continue


def _prepare(
    db: Database, run: ArcAblationRun, config: Any, client: Any, now: datetime
) -> None:
    moment = _utc(now)
    assert moment is not None
    run_id = run.id
    created_at = _utc(run.created_at)
    with db.session() as session:
        outcome = session.get(ArcForwardOutcome, run.outcome_id)
        if outcome is None:
            _finish(
                db,
                run_id,
                "failed",
                "outcome_missing",
                message="forward outcome missing",
                now=moment,
            )
            return
        mission_id = outcome.mission_id
        attempt_id = outcome.attempt_id
        candidate_id = outcome.candidate_id
        verdict = outcome.verdict
        mission = session.get(ArcMission, mission_id) if mission_id else None
        if mission is None:
            _finish(
                db,
                run_id,
                "failed",
                "lineage_unavailable",
                message="mission row missing for the recorded outcome",
                now=moment,
            )
            return
        try:
            projection = ARCMissionProjection.model_validate(
                {**dict(mission.projection_json or {}), "events": []}
            )
        except Exception as exc:
            _finish(
                db,
                run_id,
                "failed",
                "lineage_unavailable",
                message=f"mission projection unreadable: {failure_text(exc)[:300]}",
                now=moment,
            )
            return
        goal = projection.goal
        context = goal.evolution_context if goal is not None else None
        baseline = context.get("baseline") if isinstance(context, dict) else None
        candidate = next(
            (
                attempt
                for attempt in projection.attempts
                if attempt_id is not None and attempt.attempt_id == attempt_id
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (
                    attempt
                    for attempt in projection.attempts
                    if candidate_id is not None and attempt.candidate_id == candidate_id
                ),
                None,
            )
        if (
            goal is None
            or not isinstance(baseline, dict)
            or not isinstance(baseline.get("strategy_spec"), dict)
            or not isinstance(baseline.get("strategy_code"), str)
        ):
            _finish(
                db,
                run_id,
                "failed",
                "lineage_unavailable",
                message="mission goal, baseline or candidate is missing",
                now=moment,
            )
            return
        if candidate is None:
            _finish(
                db,
                run_id,
                "failed",
                "lineage_unavailable",
                message="candidate attempt is missing from the mission projection",
                now=moment,
            )
            return
        spec = dict(candidate.strategy_spec or {})

    # The candidate must still be the same source-bound variant the race judged.
    if spec.get("is_source_variant") is not True:
        _skipped(db, run_id, "not_source_variant", "candidate is not a source variant", moment)
        return
    missing: list[str] = []
    parent = spec.get("parent_strategy_id")
    if parent is None or str(parent) != str(run.parent_strategy_id):
        missing.append("parent_strategy_id")
    manifest = spec.get("parent_manifest_sha256")
    execution_identity = spec.get("parent_execution_identity_sha256")
    if not _is_sha256(manifest):
        missing.append("parent_manifest_sha256")
    if not _is_sha256(execution_identity):
        missing.append("parent_execution_identity_sha256")
    timeframe = spec.get("timeframe")
    if not isinstance(timeframe, str) or not timeframe:
        missing.append("timeframe")
    symbols = _spec_symbols(spec)
    if not symbols:
        missing.append("symbol")
    if not goal.paper_initial_equity > 0:
        missing.append("paper_initial_equity")
    if missing:
        _skipped(
            db,
            run_id,
            "lineage_incomplete",
            "candidate spec missing: " + ", ".join(missing),
            moment,
        )
        return

    changes = change_list(spec)
    if len(changes) < 2:
        _skipped(db, run_id, "single_change", "candidate carries fewer than two changes", moment)
        return
    required = len(changes) + 1
    if required > config.ablation_max_backtests_per_loser:
        _skipped(
            db,
            run_id,
            "too_many_changes",
            f"需要 {required} 次回测，超过每个输家上限 "
            f"{config.ablation_max_backtests_per_loser}",
            moment,
        )
        return

    try:
        parent_id = int(str(parent))
    except (TypeError, ValueError):
        _skipped(db, run_id, "lineage_incomplete", "parent_strategy_id is not numeric", moment)
        return
    try:
        policy = client.strategy_research_variant_policy(strategy_id=parent_id)
    except Exception as exc:
        if created_at is not None and moment - created_at > HOLD_LIMIT:
            _finish(
                db,
                run_id,
                "failed",
                "parent_policy_unavailable",
                message=failure_text(exc)[:500],
                now=moment,
            )
        else:
            _write_run(
                db,
                run_id,
                reason="parent_policy_unavailable",
                message=failure_text(exc)[:500],
                next_check_at=moment + timedelta(hours=1),
            )
        return
    if policy.get("variant_creation_supported") is not True:
        _skipped(
            db,
            run_id,
            "parent_variant_creation_unsupported",
            "parent does not support source variants",
            moment,
        )
        return
    if (
        policy.get("parent_manifest_sha256") != manifest
        or policy.get("parent_execution_identity_sha256") != execution_identity
    ):
        # The parent was redeployed after the race; the parent+change experiment moved.
        _skipped(
            db,
            run_id,
            "parent_changed_since_race",
            "parent manifest or execution identity changed since the race",
            moment,
        )
        return
    relay = policy.get("relay")
    if isinstance(relay, dict) and relay.get("blocks_evolution") is True:
        reason = str(relay.get("reason") or "parent relay seat is held")
        if created_at is not None and moment - created_at > HOLD_LIMIT:
            _finish(
                db,
                run_id,
                "failed",
                "parent_relay_hold_timeout",
                message=reason,
                now=moment,
            )
        else:
            _write_run(
                db,
                run_id,
                reason="parent_relay_hold",
                message=reason[:500],
                next_check_at=moment + timedelta(hours=1),
            )
        return

    as_of = moment.date() - timedelta(days=1)
    windows = ResearchWindowsV1(as_of=as_of)
    development = windows.window("development")
    capital = str(goal.paper_initial_equity)
    research_id = "abl_" + hashlib.sha256(
        json.dumps(
            [
                run.target_id,
                parent,
                manifest,
                execution_identity,
                str(development[0]),
                str(development[1]),
                capital,
                symbols,
                timeframe,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:24]
    window_json = {
        "windows": windows.model_dump(mode="json"),
        "development": [str(development[0]), str(development[1])],
    }
    plan_json = {
        "parent_strategy_id": parent,
        "parent_manifest_sha256": manifest,
        "parent_execution_identity_sha256": execution_identity,
        "symbols": symbols,
        "timeframe": timeframe,
        "capital": capital,
        "changes": changes,
        "source_mission_id": mission_id,
        "source_attempt_id": attempt_id,
        "source_candidate_id": candidate_id,
        "verdict": verdict,
        "baseline": baseline,
        "success_criteria": goal.success_criteria.model_dump(mode="json"),
    }
    _write_run(
        db,
        run_id,
        window_json=window_json,
        plan_json=plan_json,
        research_id=research_id,
    )
    _ensure_steps(db, run_id, changes)
    _write_run(
        db,
        run_id,
        status="running",
        started_at=moment,
        reason="",
        message="",
        next_check_at=moment,
    )


def _goal_for(run: ArcAblationRun, plan: dict[str, Any]) -> ARCGoalV1:
    windows = ResearchWindowsV1.model_validate((run.window_json or {})["windows"])
    return ARCGoalV1(
        objective="ablation: development-window single-change backtests of a forward loser",
        research_mode="avo",
        paper_review_required=True,
        research_id=run.research_id,
        research_windows=windows,
        symbols=list(plan["symbols"]),
        timeframes=[plan["timeframe"]],
        paper_initial_equity=Decimal(str(plan["capital"])),
        success_criteria=ARCSuccessCriteriaV1.model_validate(plan["success_criteria"]),
    )


def _attempt_for(
    run: ArcAblationRun, plan: dict[str, Any], step: ArcAblationStep
) -> ARCCandidateAttemptV1:
    baseline = plan["baseline"]
    base_spec = dict(baseline.get("strategy_spec") or {})
    identity = {
        "is_source_variant": True,
        "parent_strategy_id": plan["parent_strategy_id"],
        "parent_manifest_sha256": plan["parent_manifest_sha256"],
        "parent_execution_identity_sha256": plan["parent_execution_identity_sha256"],
    }
    change = dict(step.change_json or {})
    if step.kind == "baseline":
        spec = {
            **base_spec,
            **identity,
            "parameter_changes": {},
            "structural_changes": {},
        }
        attempt_id = candidate_id = f"baseline_{run.id}"
        hypothesis = "ablation baseline: unchanged parent"
    else:
        parameters: dict[str, Any] = {}
        structural: dict[str, Any] = {}
        if change.get("kind") == "parameter":
            parameters = {str(change.get("key")): change.get("value")}
        else:
            structural = {str(change.get("key")): change.get("value")}
        spec = {
            **base_spec,
            **identity,
            "parameter_changes": parameters,
            "structural_changes": structural,
            "tunable_parameters": {
                **(base_spec.get("tunable_parameters") or {}),
                **parameters,
            },
            "baseline_config": {**(base_spec.get("baseline_config") or {}), **parameters},
            "variation_operator": "ablation",
        }
        attempt_id = candidate_id = f"abl_{run.id[4:20]}_{step.ordinal}"
        hypothesis = f"ablation: {change_label(change)}"
    return ARCCandidateAttemptV1(
        attempt_id=attempt_id,
        candidate_id=candidate_id,
        hypothesis=hypothesis,
        strategy_code=baseline["strategy_code"],
        strategy_spec=spec,
    )


def _summary(metrics: dict[str, Any]) -> dict[str, Any]:
    drawdown = _fraction(
        metrics, fractions=("max_drawdown",), percentages=("max_drawdown_pct",)
    )
    return {
        "net_return": _fraction(
            metrics,
            fractions=("net_return", "total_return"),
            percentages=("total_return_pct", "return_pct"),
        ),
        "max_drawdown": None if drawdown is None else abs(drawdown),
        "trade_count": _number(metrics, "trade_count", "trades"),
        "sharpe": _number(metrics, "sharpe", "sharpe_ratio"),
    }


def _bounded_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(metrics, default=str, ensure_ascii=False)) <= 20_000:
        return metrics
    kept: dict[str, Any] = {
        key: value
        for key, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    for key in (
        "comparison_evidence",
        "evaluation_window",
        "cost_policy_hash",
        "config_sha256",
    ):
        if key in metrics:
            kept[key] = metrics[key]
    return kept


def _record_submitted(
    db: Database, step_id: str, job: dict[str, Any], now: datetime
) -> None:
    """Charge once, in the same transaction that persists the frozen job identity.

    Replaying the same idempotency key returns the same job, so a crash before this
    write can be retried without creating a second experiment or a second charge.
    """
    with db.session() as session:
        step = session.get(ArcAblationStep, step_id)
        if step is None:
            raise ValueError("ablation step missing")
        checkpoint = dict(step.checkpoint_json or {})
        checkpoint.update(
            job_id=job["job_id"],
            input_snapshot_hash=job["input_snapshot_hash"],
            phase="submitted",
            charged_at=now.isoformat(),
        )
        step.checkpoint_json = checkpoint
        step.charged_at = now


class AblationBacktestRunner:
    """Resumable backtest driver whose checkpoint lives on ``ArcAblationStep``."""

    def __init__(
        self,
        db: Database,
        step_id: str,
        *,
        budget_ok: Callable[[], bool],
        now: Callable[[], datetime],
    ) -> None:
        self.db = db
        self.step_id = step_id
        self.budget_ok = budget_ok
        self.now = now

    def _moment(self) -> datetime:
        moment = _utc(self.now())
        assert moment is not None
        return moment

    def _load(self) -> dict[str, Any]:
        with self.db.session() as session:
            step = session.get(ArcAblationStep, self.step_id)
            if step is None:
                raise ValueError("ablation step missing")
            return dict(step.checkpoint_json or {})

    def _save(self, **changes: Any) -> None:
        with self.db.session() as session:
            step = session.get(ArcAblationStep, self.step_id)
            if step is None:
                raise ValueError("ablation step missing")
            checkpoint = dict(step.checkpoint_json or {})
            checkpoint.update(changes)
            step.checkpoint_json = checkpoint
            if isinstance(changes.get("request_hash"), str):
                step.request_hash = changes["request_hash"]

    def defer_prerequisite(self, exc: Exception) -> None:
        """Bound transient preflight retries; the step is retried, never re-charged."""
        from hypertrade.bitpro.mcp import BitProMcpError

        if not isinstance(exc, BitProMcpError) or exc.status_code not in {
            None,
            408,
            429,
            502,
            503,
            504,
        }:
            return
        failures = self._load().get("preflight_failures", 0) + 1
        message = failure_text(exc)
        if failures >= MAX_RUNTIME_ERRORS:
            self._save(phase="blocked", preflight_failures=failures, last_error=message)
            raise ValueError("ablation prerequisite recovery limit reached") from exc
        self._save(
            preflight_failures=failures,
            last_error=message,
            next_check_at=(
                self._moment() + timedelta(seconds=min(300, 60 * failures))
            ).isoformat(),
        )
        raise BacktestDeferred(
            "ablation prerequisite temporarily unavailable", transient_error=True
        ) from exc

    def run(self, client: Any, **parameters: Any) -> dict[str, Any]:
        request = {
            key: value
            for key, value in parameters.items()
            if key not in {"wait_for_result", "timeout_sec", "poll_interval_sec"}
        }
        request_key = request.get("idempotency_key")
        if not isinstance(request_key, str) or not request_key:
            raise ValueError("durable backtest request key required")
        request_hash = backtest_digest(request)
        stored = self._load()
        if stored.get("request_hash") and stored["request_hash"] != request_hash:
            raise ValueError("ablation backtest request changed")
        entry = dict(stored)
        entry.setdefault("read_failures", 0)
        entry.setdefault("resume_attempts", 0)

        def save(**changes: Any) -> None:
            entry.update(changes)
            self._save(**changes)

        def failed_read(exc: Exception) -> NoReturn:
            status = getattr(exc, "status_code", None)
            message = f"{type(exc).__name__}: {failure_text(exc)}"
            if isinstance(exc, (ValueError, PermissionError, KeyError)) or (
                status is not None and 400 <= status < 500 and status not in (408, 429)
            ):
                save(phase="blocked", last_error=message)
                raise ValueError("ablation backtest recovery rejected: " + message) from exc
            failures = entry.get("read_failures", 0) + 1
            if failures >= MAX_RUNTIME_ERRORS:
                save(phase="blocked", read_failures=failures, last_error=message)
                raise ValueError("backtest read recovery limit reached") from exc
            save(
                read_failures=failures,
                last_error=message,
                next_check_at=(
                    self._moment() + timedelta(seconds=min(300, 60 * failures))
                ).isoformat(),
            )
            raise BacktestDeferred(message, transient_error=True) from exc

        if not entry.get("job_id"):
            reused = _find_reusable(self.db, self.step_id, request_hash)
            if reused is not None:
                save(
                    request=request,
                    request_hash=request_hash,
                    job_id=reused["job_id"],
                    input_snapshot_hash=reused["input_snapshot_hash"],
                    phase="submitted",
                    reused_from=reused["id"],
                    created_at=entry.get("created_at")
                    or reused.get("created_at")
                    or self._moment().isoformat(),
                )
            else:
                if not self.budget_ok():
                    raise AblationBudgetDeferred("daily ablation backtest budget exhausted")
                save(
                    request=request,
                    request_hash=request_hash,
                    phase="planned",
                    created_at=self._moment().isoformat(),
                    read_failures=0,
                    resume_attempts=0,
                )
                try:
                    created = client.backtest_start_job(
                        **request, wait_for_result=False
                    )
                except Exception as exc:
                    failed_read(exc)
                job = created.get("job") or {}
                if not job.get("job_id") or not job.get("input_snapshot_hash"):
                    save(phase="blocked")
                    raise ValueError(
                        "backtest creation receipt missing frozen job identity"
                    )
                _record_submitted(self.db, self.step_id, job, self._moment())
                entry.update(
                    job_id=job["job_id"],
                    input_snapshot_hash=job["input_snapshot_hash"],
                    phase="submitted",
                    charged_at=self._moment().isoformat(),
                )

        try:
            response = client.backtest_get_job(job_id=entry["job_id"])
        except Exception as exc:
            failed_read(exc)
        job = response.get("job") or {}
        if (
            job.get("job_id") != entry["job_id"]
            or job.get("input_snapshot_hash") != entry["input_snapshot_hash"]
            or str(job.get("strategy_id")) != str(request["strategy_id"])
        ):
            save(phase="blocked")
            raise ValueError("backtest frozen job identity mismatch")
        status = job.get("status")
        if status == "interrupted":
            attempts = int(entry.get("resume_attempts", 0))
            if attempts >= 2:
                save(phase="blocked")
                raise ValueError("backtest resume limit reached")
            save(phase="resume_requested", resume_attempts=attempts + 1)
            try:
                client.backtest_resume_job(
                    job_id=entry["job_id"],
                    idempotency_key=request_key + f"-resume-{attempts + 1}",
                )
            except Exception as exc:
                if getattr(
                    exc, "status_code", None
                ) == 409 and "backtest_source_or_deployment_changed" in str(exc):
                    save(phase="blocked")
                    raise ValueError("ablation backtest execution version changed") from exc
                failed_read(exc)
            save(
                phase="waiting",
                next_check_at=(self._moment() + timedelta(seconds=60)).isoformat(),
            )
            raise BacktestDeferred("backtest resumed")
        if status in PENDING_BACKTEST_STATES:
            started = entry.get("charged_at") or entry.get("created_at")
            started_at = (
                _utc(datetime.fromisoformat(started.replace("Z", "+00:00")))
                if isinstance(started, str)
                else None
            )
            if started_at is not None and self._moment() - started_at > JOB_WAIT_LIMIT:
                save(phase="blocked")
                raise ValueError("backtest wait limit reached")
            save(
                phase="waiting",
                next_check_at=(self._moment() + timedelta(seconds=60)).isoformat(),
            )
            raise BacktestDeferred(f"backtest {status}")
        if status not in {"completed", "failed", "cancelled"}:
            save(phase="blocked")
            raise ValueError("unknown backtest state")
        save(phase="terminal", status=status, next_check_at=None, read_failures=0)
        return dict(response)


def _execute_step(
    db: Database,
    run: ArcAblationRun,
    step: ArcAblationStep,
    client: Any,
    config: Any,
    now: datetime,
) -> None:
    moment = _utc(now)
    assert moment is not None
    limit = config.ablation_max_backtests_per_day
    checkpoint = dict(step.checkpoint_json or {})
    if not checkpoint.get("job_id"):
        request_hash = checkpoint.get("request_hash")
        reusable = _find_reusable(
            db, step.id, request_hash if isinstance(request_hash, str) else None
        )
        if reusable is None and _daily_charged(db, moment) >= limit:
            _write_run(
                db,
                run.id,
                reason="daily_budget_exhausted",
                next_check_at=next_utc_midnight(moment),
            )
            return
    _write_step(db, step.id, status="running")

    data_reference: dict[str, str] | None = None
    if step.kind != "baseline":
        base = _baseline_step(db, run.id)
        reference = (base.result_json or {}).get("data_reference") if base else None
        if (
            not isinstance(reference, dict)
            or not reference.get("verified_data_snapshot_id")
            or not reference.get("verified_data_manifest_sha256")
        ):
            _write_step(
                db, step.id, status="failed", reason="baseline_data_reference_unavailable"
            )
            _write_run(db, run.id, reason="", message="", next_check_at=moment)
            return
        data_reference = {
            str(key): str(value) for key, value in reference.items()
        }

    plan = dict(run.plan_json or {})
    service = ARCSelfTestService(
        client,
        backtest_runner=AblationBacktestRunner(
            db,
            step.id,
            budget_ok=lambda: _daily_charged(db, moment) < limit,
            now=lambda: moment,
        ),
    )
    try:
        result = service.run(
            _attempt_for(run, plan, step),
            _goal_for(run, plan),
            purpose="development",
            data_reference=data_reference,
        )
    except AblationBudgetDeferred:
        _write_step(db, step.id, status="pending")
        _write_run(
            db,
            run.id,
            reason="daily_budget_exhausted",
            next_check_at=next_utc_midnight(moment),
        )
        return
    except BacktestDeferred:
        saved = _step_checkpoint(db, step.id)
        next_check = saved.get("next_check_at")
        try:
            next_at = _utc(datetime.fromisoformat(str(next_check).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            next_at = None
        _write_step(db, step.id, status="running")
        _write_run(
            db,
            run.id,
            reason="backtest_pending",
            next_check_at=next_at or (moment + timedelta(seconds=60)),
        )
        return

    if result.terminal_failure or not result.backtest_id:
        reason = (result.reasons[0] if result.reasons else "backtest_failed")[:128]
        _write_step(
            db,
            step.id,
            status="failed",
            reason=reason,
            result_json={
                "reasons": list(result.reasons[:10]),
                "message": result.message[:500],
                "terminal_failure": result.terminal_failure,
                "bitpro_strategy_id": result.bitpro_strategy_id,
            },
        )
        _write_run(db, run.id, reason="", message="", next_check_at=moment)
        return

    metrics = dict(result.metrics or {})
    result_json: dict[str, Any] = {
        "backtest_id": result.backtest_id,
        "bitpro_strategy_id": result.bitpro_strategy_id,
        "metrics": _bounded_metrics(metrics),
        "summary": _summary(metrics),
        "criteria_reasons": list(result.reasons[:10]),
    }
    if step.kind == "baseline":
        evidence = metrics.get("comparison_evidence")
        manifests = (
            evidence.get("data_manifests") if isinstance(evidence, dict) else None
        )
        digest = manifests[0] if isinstance(manifests, list) and len(manifests) == 1 else None
        if not isinstance(digest, str) or not _is_sha256(digest):
            _write_step(
                db,
                step.id,
                status="failed",
                reason="baseline_data_snapshot_unavailable",
                result_json=result_json,
            )
            _write_run(db, run.id, reason="", message="", next_check_at=moment)
            return
        result_json["data_reference"] = {
            "verified_data_snapshot_id": "vbs_" + digest,
            "verified_data_manifest_sha256": digest,
        }
    _write_step(db, step.id, status="completed", reason="", result_json=result_json)
    _write_run(db, run.id, reason="", message="", next_check_at=moment)


def _result_skeleton(run: ArcAblationRun, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ablation_result.v1",
        "outcome_id": run.outcome_id,
        "verdict": plan.get("verdict"),
        "parent_strategy_id": run.parent_strategy_id,
        "challenger_strategy_id": run.challenger_strategy_id,
        "window": (run.window_json or {}).get("development"),
        "capital": plan.get("capital"),
        "baseline": {},
        "effects": [],
        "harmful": [],
        "helpful": [],
        "neutral": [],
        "unknown": [],
        "incomparable": [],
        "scope": "development_window_single_factor",
        "note": NOTE,
        "causal_claim_verified": False,
    }


def _summarize(
    run: ArcAblationRun, steps: list[ArcAblationStep]
) -> tuple[str, str, dict[str, Any]]:
    plan = dict(run.plan_json or {})
    result = _result_skeleton(run, plan)
    base = next((step for step in steps if step.kind == "baseline"), None)
    if base is None or base.status == "failed":
        reason = (base.reason if base is not None and base.reason else "baseline_backtest_failed")
        result["baseline"] = {
            "status": base.status if base is not None else "missing",
            "reason": reason,
            "backtest_id": (base.result_json or {}).get("backtest_id") if base else None,
        }
        return "failed", reason[:64], result

    base_result = dict(base.result_json or {})
    base_metrics = dict(base_result.get("metrics") or {})
    base_summary = dict(base_result.get("summary") or {})
    result["baseline"] = {
        "backtest_id": base_result.get("backtest_id"),
        **base_summary,
    }
    ordinal = {step.step_key: step.ordinal for step in steps}
    effects: list[dict[str, Any]] = []
    for step in steps:
        if step.kind != "single":
            continue
        change = dict(step.change_json or {})
        effect: dict[str, Any] = {
            "step_key": step.step_key,
            "change": change,
            "label": change_label(change),
            "status": step.status,
            "backtest_id": (step.result_json or {}).get("backtest_id"),
            "reason": step.reason or "",
            "delta_net_return": None,
            "delta_max_drawdown": None,
            "delta_trade_count": None,
            "class": "unknown",
        }
        if step.status == "failed":
            effect["reason"] = step.reason or "backtest_failed"
            effects.append(effect)
            continue
        if step.status != "completed":
            effect["reason"] = "step_not_terminal"
            effects.append(effect)
            continue
        step_result = dict(step.result_json or {})
        summary = dict(step_result.get("summary") or {})
        if (
            summary.get("net_return") is None
            or summary.get("max_drawdown") is None
            or base_summary.get("net_return") is None
            or base_summary.get("max_drawdown") is None
        ):
            effect["reason"] = "metric_missing"
            effects.append(effect)
            continue
        comparison = compare_backtests(
            dict(step_result.get("metrics") or {}),
            {
                "metrics": base_metrics,
                "backtest_id": base_result.get("backtest_id"),
            },
        )
        if "reason" in comparison:
            effect["class"] = "incomparable"
            effect["reason"] = str(comparison["reason"])
            effects.append(effect)
            continue
        delta_return = float(summary["net_return"]) - float(base_summary["net_return"])
        delta_drawdown = float(summary["max_drawdown"]) - float(base_summary["max_drawdown"])
        effect["delta_net_return"] = delta_return
        effect["delta_max_drawdown"] = delta_drawdown
        if summary.get("trade_count") is not None and base_summary.get("trade_count") is not None:
            effect["delta_trade_count"] = float(summary["trade_count"]) - float(
                base_summary["trade_count"]
            )
        if delta_return >= HELPFUL_RETURN and delta_drawdown <= HELPFUL_DRAWDOWN_SLACK:
            effect["class"] = "helpful"
        elif delta_return <= HARMFUL_RETURN or delta_drawdown >= HARMFUL_DRAWDOWN:
            effect["class"] = "harmful"
        else:
            effect["class"] = "neutral"
        effects.append(effect)

    def order(effect: dict[str, Any]) -> tuple[int, float, int]:
        delta = effect["delta_net_return"]
        step_ordinal = ordinal.get(effect["step_key"], 0)
        if delta is None:
            return (1, 0.0, step_ordinal)
        return (0, float(delta), step_ordinal)

    effects.sort(key=order)
    result["effects"] = effects
    for label in ("harmful", "helpful", "neutral", "unknown", "incomparable"):
        result[label] = [effect["label"] for effect in effects if effect["class"] == label]
    if any(effect["class"] in {"helpful", "harmful", "neutral"} for effect in effects):
        return "completed", "", result
    return "failed", "all_single_changes_failed", result


def _advance(
    db: Database, run: ArcAblationRun, config: Any, client: Any, now: datetime
) -> None:
    executed = 0
    for step in _step_rows(db, run.id):
        if step.status in {"completed", "failed"}:
            continue
        if step.kind != "baseline":
            base = _baseline_step(db, run.id)
            if base is not None and base.status == "failed":
                break
        _execute_step(db, run, step, client, config, now)
        fresh = _get_step(db, step.id)
        if fresh is None or fresh.status not in {"completed", "failed"}:
            return
        executed += 1
        if fresh.kind == "baseline" and fresh.status == "failed":
            break
        if executed >= STEPS_PER_TICK:
            return
    steps = _step_rows(db, run.id)
    base = next((step for step in steps if step.kind == "baseline"), None)
    if base is not None and base.status == "failed":
        status, reason, result = _summarize(run, steps)
        _finish(db, run.id, status, reason, now=now, result_json=result)
        return
    if steps and all(step.status in {"completed", "failed"} for step in steps):
        status, reason, result = _summarize(run, steps)
        _finish(db, run.id, status, reason, now=now, result_json=result)


def _record_runtime_failure(
    db: Database, run: ArcAblationRun, exc: Exception, now: datetime
) -> None:
    record_runtime_error(
        "evolution.ablation", exc, context={"run_id": run.id}, db=db
    )
    current = _get_run(db, run.id)
    result = dict(current.result_json or {}) if current is not None else {}
    errors = int(result.get("runtime_errors") or 0) + 1
    result["runtime_errors"] = errors
    values: dict[str, Any] = {
        "reason": "runtime_error",
        "message": failure_text(exc)[:500],
        "result_json": result,
        "next_check_at": now + timedelta(minutes=10),
    }
    if errors >= MAX_RUNTIME_ERRORS:
        values.update(status="failed", finished_at=now, next_check_at=None)
    _write_run(db, run.id, **values)


def _due_run(db: Database, now: datetime) -> ArcAblationRun | None:
    moment = _utc(now)
    assert moment is not None
    with db.session() as session:
        return session.scalars(
            select(ArcAblationRun)
            .where(
                ArcAblationRun.status.in_(("pending", "running")),
                (ArcAblationRun.next_check_at.is_(None))
                | (ArcAblationRun.next_check_at <= moment),
            )
            .order_by(ArcAblationRun.created_at.asc())
            .limit(1)
        ).one_or_none()


def ablation_budget_view(db: Database, config: Any, now: datetime) -> dict[str, Any]:
    """Read-only ledger view for budget status and the effectiveness report.

    Counts are observations over persisted rows, not causal claims. It opens its own short
    session and never writes, so the caller may degrade to an "unavailable" section.
    """
    moment = _utc(now)
    assert moment is not None
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    with db.session() as session:
        period_used = int(
            session.scalar(
                select(func.count())
                .select_from(ArcAblationStep)
                .where(
                    ArcAblationStep.charged_at.is_not(None),
                    ArcAblationStep.charged_at >= start,
                    ArcAblationStep.charged_at < end,
                )
            )
            or 0
        )
        runs = {
            str(status): int(count)
            for status, count in session.execute(
                select(ArcAblationRun.status, func.count()).group_by(ArcAblationRun.status)
            ).all()
        }
        reasons = {
            str(reason): int(count)
            for reason, count in session.execute(
                select(ArcAblationRun.reason, func.count())
                .where(ArcAblationRun.reason.is_not(None), ArcAblationRun.reason != "")
                .group_by(ArcAblationRun.reason)
            ).all()
        }
        scheduled = {
            (target_id, str(challenger))
            for target_id, challenger in session.execute(
                select(ArcAblationRun.target_id, ArcAblationRun.challenger_strategy_id)
            ).all()
        }
        next_at = session.scalar(
            select(func.min(ArcAblationRun.next_check_at)).where(
                ArcAblationRun.status.in_(("pending", "running"))
            )
        )
        losers = list(
            session.scalars(
                select(ArcForwardOutcome)
                .where(
                    ArcForwardOutcome.target_id == config.target_id,
                    ArcForwardOutcome.verdict.in_(LOSER_VERDICTS),
                )
                .order_by(
                    case((ArcForwardOutcome.ended_at.is_(None), 1), else_=0),
                    ArcForwardOutcome.ended_at.desc(),
                    ArcForwardOutcome.created_at.desc(),
                )
                .limit(500)
            )
        )
    loser_counts = {"eligible": 0, "single_change": 0, "unlinked": 0, "scheduled": 0}
    for row in losers:
        if (row.target_id, str(row.challenger_strategy_id)) in scheduled:
            loser_counts["scheduled"] += 1
        if row.lineage_status != "linked":
            loser_counts["unlinked"] += 1
        elif change_count(row.changes_json) >= 2:
            loser_counts["eligible"] += 1
        else:
            loser_counts["single_change"] += 1
    enabled = bool(
        config.enabled and config.ablation_enabled and config.target_id == "bitpro"
    )
    reason: str | None = None
    if not enabled:
        reason = "disabled"
    elif period_used >= config.ablation_max_backtests_per_day:
        reason = "period_budget_exhausted"
    next_moment = _utc(next_at)
    return {
        "schema_version": "ablation_budget.v1",
        "enabled": enabled,
        "unit": "backtests",
        "period": start.date().isoformat(),
        "period_used": period_used,
        "period_limit": config.ablation_max_backtests_per_day,
        "per_loser_limit": config.ablation_max_backtests_per_loser,
        "runs": runs,
        "reasons": reasons,
        "losers": loser_counts,
        "next_run_at": next_moment.isoformat() if next_moment is not None else None,
        "reason": reason,
        "rule": "消融回测独立计账，不占用每日研究名额；只在开发窗口回测，不碰 Paper／实盘",
    }


def ablation_once(
    db: Database, *, now: datetime | None = None, client: Any = None
) -> dict[str, Any]:
    """Advance at most one loser run; expected waits never surface as runtime errors."""
    from hypertrade.arc.evolution import EvolutionConfig

    moment = _utc(now) if now is not None else datetime.now(UTC)
    assert moment is not None
    with db.session() as session:
        control = session.get(EvolutionControl, "global")
        config = EvolutionConfig.model_validate(
            dict(control.config_json or {}) if control is not None else {}
        )
    if (
        not config.enabled
        or not config.ablation_enabled
        or config.target_id != "bitpro"
    ):
        return {"status": "disabled"}
    with research_lock("evolution-ablation") as owner:
        if owner is None:
            return {"status": "busy"}
        scheduled = schedule_runs(db, config, moment)
        run = _due_run(db, moment)
        if run is None:
            return {"status": "idle", "scheduled": scheduled}
        run_id = run.id
        adapter = client or _default_client()
        try:
            if run.status == "pending":
                _prepare(db, run, config, adapter, moment)
                prepared = _get_run(db, run_id)
                if prepared is not None and prepared.status == "running":
                    _advance(db, prepared, config, adapter, moment)
            else:
                _advance(db, run, config, adapter, moment)
        except Exception as exc:
            _record_runtime_failure(db, run, exc, moment)
        fresh = _get_run(db, run_id)
        return {
            "status": "advanced",
            "run_id": run_id,
            "run_status": fresh.status if fresh is not None else "missing",
            "reason": fresh.reason if fresh is not None else "",
            "scheduled": scheduled,
        }


def _default_client() -> Any:
    from hypertrade.bitpro.mcp import BitProToolAdapter

    return BitProToolAdapter()
