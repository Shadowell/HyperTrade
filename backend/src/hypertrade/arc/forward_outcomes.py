"""Forward outcome ledger for finished BitPro race lanes.

Only finished lanes are recorded here. ``won``, ``lost_futility`` and ``lost_exam`` are
the only verdicts that count as evidence of a win or a loss; every other verdict is
neutral bookkeeping (a timeout, a seat handed to a sibling, an operator cancel, or a
state BitPro did not explain) and must never be read as negative evidence. One race is a
noisy observation about one challenger, not a causal conclusion about its strategy
family.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.evolution_models import ArcForwardOutcome
from hypertrade.arc.store import load_projection
from hypertrade.db import ArcMission, Database

logger = logging.getLogger("hypertrade.arc.forward_outcomes")

EVIDENCE_VERDICTS = ("won", "lost_futility", "lost_exam")
NEUTRAL_VERDICTS = (
    "expired_timeout",
    "superseded",
    "cancelled_operator",
    "cancelled_unknown",
    "ended_unknown",
)
# Only these two mean "the lane ended, but we do not know why"; a concrete verdict may
# replace them. Every other verdict is final so a later noisy observation cannot rewrite it.
UPGRADABLE_VERDICTS = ("cancelled_unknown", "ended_unknown")

_NUMERIC_METRIC_KEYS = (
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
)
_METRIC_KEYS = (*_NUMERIC_METRIC_KEYS, "cancellation_reason", "cancellation_metrics")
_CANCELLATION_KINDS = {
    "futility": "lost_futility",
    "exam": "lost_exam",
    "timeout": "expired_timeout",
    "superseded": "superseded",
    "operator": "cancelled_operator",
}


def outcome_id(target_id: str, parent_strategy_id: object, challenger_strategy_id: object) -> str:
    """Stable id for one (target, parent, challenger) lane; str() keeps 41 and "41" equal."""
    body = json.dumps(
        [target_id, str(parent_strategy_id), str(challenger_strategy_id)],
        separators=(",", ":"),
    )
    return "fo_" + hashlib.sha256(body.encode()).hexdigest()[:32]


def verdict_for(state: str | None, cancellation_kind: str | None) -> str | None:
    """Map a race judge state to a ledger verdict; None means the lane has not finished."""
    if state == "completed":
        return "won"
    if state == "cancelled":
        # BitPro's cancellation kind is the only source of truth for who ended the lane;
        # an unrecognized kind must stay unknown rather than being guessed as negative.
        kind = cancellation_kind if isinstance(cancellation_kind, str) else ""
        return _CANCELLATION_KINDS.get(kind, "cancelled_unknown")
    if state == "ended":
        return "ended_unknown"
    return None


def _finite_number(value: Any) -> int | float | None:
    """Evidence keeps its original value; bools and non-finite floats are not results."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def metrics_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Project a ``RacePairRecord.to_dict()`` into the bounded metrics the ledger keeps."""
    metrics: dict[str, Any] = {
        key: _finite_number(record.get(key)) for key in _NUMERIC_METRIC_KEYS
    }
    # The judge initializes the day counters to 0 when it has no proof yet, so a zero
    # non-tie count means "unknown", not "observed zero wins".
    if not metrics["paired_non_tie_days"]:
        metrics["positive_days"] = None
        metrics["paired_non_tie_days"] = None
    reason = record.get("cancellation_reason")
    metrics["cancellation_reason"] = reason if isinstance(reason, str) else None
    raw_metrics = record.get("cancellation_metrics")
    metrics["cancellation_metrics"] = (
        dict(raw_metrics) if isinstance(raw_metrics, dict) else None
    )
    return {key: metrics[key] for key in _METRIC_KEYS}


def _evidence_sha256(verdict: str, metrics: dict[str, Any]) -> str:
    body = json.dumps({"verdict": verdict, "metrics": metrics}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _apply_lineage(
    row: ArcForwardOutcome,
    match: tuple[ArcMission, ARCCandidateAttemptV1] | None,
) -> None:
    """Write the lineage verdict once; an unmatched challenger is never inferred."""
    if match is None:
        row.lineage_status = "no_lineage"
        return
    mission, attempt = match
    spec = attempt.strategy_spec
    row.lineage_status = "linked"
    row.mission_id = mission.mission_id
    row.candidate_id = attempt.candidate_id
    row.attempt_id = attempt.attempt_id
    row.changes_json = {
        "parameter_changes": spec.get("parameter_changes") or {},
        "structural_changes": spec.get("structural_changes") or {},
    }
    row.scope_json = {
        "symbol": spec.get("symbol"),
        "symbols": spec.get("symbols"),
        "timeframe": spec.get("timeframe"),
        "parent_strategy_id": spec.get("parent_strategy_id"),
    }


class ForwardOutcomeLedger:
    """Write-once outcome rows plus best-effort lineage back to the research attempt."""

    def __init__(self, db: Database, *, mission_scan_limit: int = 500) -> None:
        self.db = db
        self.mission_scan_limit = mission_scan_limit

    def record(
        self,
        *,
        target_id: str,
        parent_strategy_id: object,
        challenger_strategy_id: object,
        verdict: str,
        metrics: dict[str, Any],
        ended_at: datetime | None = None,
        slot_no: int | None = None,
        generation: int = 1,
        source: str = "race_judge",
        link: bool = True,
    ) -> dict[str, Any]:
        """Record one finished lane; ``link=False`` leaves it pending for a batched pass."""
        if verdict not in EVIDENCE_VERDICTS and verdict not in NEUTRAL_VERDICTS:
            raise ValueError(f"unknown forward outcome verdict: {verdict}")
        oid = outcome_id(target_id, parent_strategy_id, challenger_strategy_id)
        digest = _evidence_sha256(verdict, metrics)

        with self.db.session() as session:
            row = session.get(ArcForwardOutcome, oid)
            if row is None:
                row = ArcForwardOutcome(
                    id=oid,
                    target_id=target_id,
                    parent_strategy_id=str(parent_strategy_id),
                    challenger_strategy_id=str(challenger_strategy_id),
                    slot_no=slot_no,
                    generation=generation,
                    verdict=verdict,
                    verdict_source=source,
                    ended_at=ended_at,
                    metrics_json=metrics,
                    evidence_sha256=digest,
                    lineage_status="pending",
                    changes_json={},
                    scope_json={},
                )
                session.add(row)
                try:
                    session.flush()
                except IntegrityError:
                    # Another writer inserted this lane first: the unique pair wins, and
                    # this call reconciles against the row that actually landed.
                    session.rollback()
                    row = session.get(ArcForwardOutcome, oid)
                    if row is None:
                        raise
            self._reconcile(
                row,
                verdict=verdict,
                metrics=metrics,
                digest=digest,
                ended_at=ended_at,
                source=source,
            )

        if link:
            linked = None
            try:
                linked = self.link(oid)
            except Exception:  # Lineage is research plumbing; outcome capture must not fail.
                logger.warning("Forward outcome lineage link failed for %s", oid, exc_info=True)
            if linked is not None:
                return linked
        with self.db.session() as session:
            row = session.get(ArcForwardOutcome, oid)
            if row is None:
                raise RuntimeError(f"forward outcome disappeared after record: {oid}")
            return self.view(row)

    @staticmethod
    def _reconcile(
        row: ArcForwardOutcome,
        *,
        verdict: str,
        metrics: dict[str, Any],
        digest: str,
        ended_at: datetime | None,
        source: str,
    ) -> None:
        """Keep the first concrete verdict; only an unknown ending may be refined later."""
        if row.verdict == verdict:
            return
        if row.verdict in UPGRADABLE_VERDICTS and verdict not in UPGRADABLE_VERDICTS:
            row.verdict = verdict
            row.metrics_json = metrics
            row.evidence_sha256 = digest
            row.ended_at = ended_at
            row.verdict_source = source

    def _lineage_index(
        self,
        session: Session,
        wanted: set[str],
    ) -> dict[str, tuple[ArcMission, ARCCandidateAttemptV1]]:
        """Newest mission per wanted challenger; stop loading projections once all are found."""
        found: dict[str, tuple[ArcMission, ARCCandidateAttemptV1]] = {}
        if not wanted:
            return found
        missions = session.scalars(
            select(ArcMission)
            .order_by(ArcMission.updated_at.desc())
            .limit(self.mission_scan_limit)
        ).yield_per(20)
        for mission in missions:
            projection = load_projection(session, mission)
            for attempt in projection.attempts:
                challenger = str(attempt.bitpro_strategy_id)
                if challenger in wanted and challenger not in found:
                    found[challenger] = (mission, attempt)
                    if len(found) == len(wanted):
                        return found
        return found

    def link(self, outcome_id: str) -> dict[str, Any] | None:
        """Attach one pending outcome to the ARC attempt that launched its challenger."""
        with self.db.session() as session:
            row = session.get(ArcForwardOutcome, outcome_id)
            if row is None:
                return None
            if row.lineage_status != "pending":
                return self.view(row)

            challenger = str(row.challenger_strategy_id)
            match = self._lineage_index(session, {challenger}).get(challenger)
            _apply_lineage(row, match)
            session.flush()
            return self.view(row)

    def link_pending(self, limit: int = 20) -> int:
        """Match up to ``limit`` pending rows with one mission scan for the whole batch."""
        with self.db.session() as session:
            rows = list(
                session.scalars(
                    select(ArcForwardOutcome)
                    .where(ArcForwardOutcome.lineage_status == "pending")
                    .order_by(ArcForwardOutcome.created_at.asc())
                    .limit(max(0, limit))
                )
            )
            if not rows:
                return 0
            wanted = {str(row.challenger_strategy_id) for row in rows}
            index = self._lineage_index(session, wanted)
            for row in rows:
                _apply_lineage(row, index.get(str(row.challenger_strategy_id)))
            session.flush()
            return len(rows)

    def evidence_for_lineage(
        self,
        *,
        target_id: str,
        strategy_id: object,
        ancestors: int = 3,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Concrete, lineage-linked races of this strategy and the champions it replaced.

        A challenger that wins becomes the new champion under a new strategy id, while its
        winning race (and its predecessors' races) stay recorded under the old id. Walking
        the ``won`` rows backwards is the only way research on the current champion can see
        the races that made it and its ancestors. Neutral records never qualify, and
        ``ancestors=0`` reads only the races recorded under this id.
        """
        ordering = (
            case((ArcForwardOutcome.ended_at.is_(None), 1), else_=0),
            ArcForwardOutcome.ended_at.desc(),
            ArcForwardOutcome.created_at.desc(),
        )
        chain = [str(strategy_id)]
        with self.db.session() as session:
            for _ in range(max(0, ancestors)):
                won = session.scalars(
                    select(ArcForwardOutcome)
                    .where(
                        ArcForwardOutcome.target_id == target_id,
                        ArcForwardOutcome.challenger_strategy_id == chain[-1],
                        ArcForwardOutcome.verdict == "won",
                    )
                    .order_by(*ordering)
                    .limit(1)
                ).first()
                if won is None:
                    break
                parent = str(won.parent_strategy_id)
                if parent in chain:
                    break  # A cycle is operator-visible corruption, not more history.
                chain.append(parent)
            statement = (
                select(ArcForwardOutcome)
                .where(
                    ArcForwardOutcome.target_id == target_id,
                    ArcForwardOutcome.parent_strategy_id.in_(chain),
                    ArcForwardOutcome.verdict.in_(EVIDENCE_VERDICTS),
                    ArcForwardOutcome.lineage_status == "linked",
                )
                .order_by(*ordering)
                .limit(max(0, limit))
            )
            rows = list(session.scalars(statement).all())
        results = []
        for row in rows:
            item = self.view(row)
            generations_back = chain.index(row.parent_strategy_id)
            item["generations_back"] = generations_back
            item["relation"] = self._relation(row, chain, generations_back)
            results.append(item)
        return results

    @staticmethod
    def _relation(row: ArcForwardOutcome, chain: list[str], generations_back: int) -> str:
        """Why this row matters to the strategy under research, never a causal claim."""
        if row.verdict == "won":
            if row.challenger_strategy_id == chain[0]:
                return "made_current"
            if row.challenger_strategy_id in chain:
                return "made_ancestor"
        if generations_back == 0:
            return "variant_of_current"
        return "variant_of_ancestor"

    def summary(self) -> dict[str, Any]:
        """Aggregate in the database: this is polled by pages that do not need the metrics."""
        with self.db.session() as session:
            verdict_counts = session.execute(
                select(ArcForwardOutcome.verdict, func.count()).group_by(
                    ArcForwardOutcome.verdict
                )
            ).all()
            lineage_counts = session.execute(
                select(ArcForwardOutcome.lineage_status, func.count()).group_by(
                    ArcForwardOutcome.lineage_status
                )
            ).all()
            last_recorded_at = session.scalar(select(func.max(ArcForwardOutcome.created_at)))
        by_verdict = {str(verdict): int(count) for verdict, count in verdict_counts}
        by_lineage = {str(status): int(count) for status, count in lineage_counts}
        return {
            "total": sum(by_verdict.values()),
            "by_verdict": by_verdict,
            "by_lineage": by_lineage,
            "evidence": sum(
                count for verdict, count in by_verdict.items() if verdict in EVIDENCE_VERDICTS
            ),
            "last_recorded_at": _iso(last_recorded_at),
        }

    @staticmethod
    def view(row: ArcForwardOutcome) -> dict[str, Any]:
        return {
            "id": row.id,
            "target_id": row.target_id,
            "parent_strategy_id": row.parent_strategy_id,
            "challenger_strategy_id": row.challenger_strategy_id,
            "slot_no": row.slot_no,
            "generation": row.generation,
            "verdict": row.verdict,
            "verdict_source": row.verdict_source,
            "ended_at": _iso(row.ended_at),
            "metrics": dict(row.metrics_json or {}),
            "evidence_sha256": row.evidence_sha256,
            "lineage_status": row.lineage_status,
            "mission_id": row.mission_id,
            "candidate_id": row.candidate_id,
            "attempt_id": row.attempt_id,
            "changes": dict(row.changes_json or {}),
            "scope": dict(row.scope_json or {}),
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
