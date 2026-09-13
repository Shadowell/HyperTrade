"""Offline meta-tuning for evolution parameters (evolution_tuning.v1).

The tuner replays the persisted cycle ledger — every scan already froze its
config revision and the 7+7 window values it observed — so adjustments come
from settled history, not from a live re-read of the platform. The rule is
deliberately simple and auditable: the degradation threshold should sit at the
p90 of observed degradation magnitudes, so roughly the top decile of
historical events merits a research cycle and ordinary noise does not.

Advisory by default: reports land as ``meta_tuning`` ledger receipts and never
change behavior unless ``meta_tuning_auto_apply`` is on. Even then the applied
move is bounded (one step per run inside declared bounds), goes through the
audited ``EvolutionService.configure`` revision check, and is attributed to
``hypertrade:meta-tuner``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from hypertrade.arc.evolution_models import EvolutionCycle
from hypertrade.db import Database

META_TUNER_ACTOR = "hypertrade:meta-tuner"


class TuningBoundsV1(BaseModel):
    """Hard bounds the tuner may never leave, regardless of recommendations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_threshold_pp: Decimal = Field(default=Decimal("5"), gt=0)
    max_threshold_pp: Decimal = Field(default=Decimal("20"), gt=0)
    max_step_pp: Decimal = Field(default=Decimal("3"), gt=0)
    min_samples: int = Field(default=12, ge=4)


class EvolutionTuningV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "evolution_tuning.v1"
    generated_at: str
    sample_count: int
    observed_p50_pp: str | None = None
    observed_p90_pp: str | None = None
    observed_max_pp: str | None = None
    current_threshold_pp: str
    recommended_threshold_pp: str | None = None
    recommendation: str  # insufficient_data | keep | lower | raise | applied
    applied: bool = False
    applied_revision: int | None = None
    rationale: str


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def collect_observations(db: Database, *, max_cycles: int = 500) -> list[float]:
    """Max(return_drop_pp, drawdown_increase_pp) per settled 7+7 observation."""

    observations: list[float] = []
    with db.session() as session:
        rows = session.scalars(
            select(EvolutionCycle)
            .where(EvolutionCycle.status.in_(["no_action", "research_created", "deferred"]))
            .order_by(EvolutionCycle.created_at.desc())
            .limit(max_cycles)
        ).all()
        for row in rows:
            payload = row.payload_json if isinstance(row.payload_json, dict) else {}
            for diagnostic in payload.get("diagnostics", []):
                if not isinstance(diagnostic, dict):
                    continue
                window = diagnostic.get("window")
                if not isinstance(window, dict):
                    continue
                values = []
                for key in ("return_drop_pp", "drawdown_increase_pp"):
                    raw = window.get(key)
                    if raw is None:
                        continue
                    try:
                        values.append(abs(float(raw)))
                    except (TypeError, ValueError):
                        continue
                if values:
                    observations.append(max(values))
    return observations


def evaluate_tuning(
    db: Database,
    config_threshold_pp: Decimal,
    *,
    bounds: TuningBoundsV1 | None = None,
    now: datetime | None = None,
) -> EvolutionTuningV1:
    bounds = bounds or TuningBoundsV1()
    now = now or datetime.now(UTC)
    observations = collect_observations(db)
    common = {
        "generated_at": now.isoformat(),
        "sample_count": len(observations),
        "current_threshold_pp": str(config_threshold_pp),
    }
    if len(observations) < bounds.min_samples:
        return EvolutionTuningV1(
            **common,
            recommendation="insufficient_data",
            rationale=(
                f"仅 {len(observations)} 条已结算 7+7 观测，少于 {bounds.min_samples} 条门槛；"
                "不基于不足样本调参"
            ),
        )
    p50 = _percentile(observations, 0.50)
    p90 = _percentile(observations, 0.90)
    observed_max = max(observations)
    lower = max(float(bounds.min_threshold_pp), p50)
    upper = float(bounds.max_threshold_pp)
    recommended = min(max(p90, lower), upper)
    observed_fields = {
        "observed_p50_pp": f"{p50:.4f}",
        "observed_p90_pp": f"{p90:.4f}",
        "observed_max_pp": f"{observed_max:.4f}",
    }
    delta = recommended - float(config_threshold_pp)
    if abs(delta) < 0.5:
        return EvolutionTuningV1(
            **common,
            **observed_fields,
            recommended_threshold_pp=str(config_threshold_pp),
            recommendation="keep",
            rationale=(
                f"观测 p90={p90:.2f}pp 与当前阈值 {config_threshold_pp}pp"
                "差距不足一个调整步长，保持"
            ),
        )
    direction = "raise" if delta > 0 else "lower"
    rationale = (
        f"历史 {len(observations)} 条观测 p50={p50:.2f}pp、p90={p90:.2f}pp；"
        f"阈值定在 p90 使前 10% 幅度的事件触发研究、其余视为噪声；"
        f"建议 {direction} 至 {recommended:.1f}pp（上限 {bounds.max_threshold_pp}、"
        f"下限 max({bounds.min_threshold_pp}, p50)）"
    )
    return EvolutionTuningV1(
        **common,
        **observed_fields,
        recommended_threshold_pp=f"{recommended:.4f}",
        recommendation=direction,
        rationale=rationale,
    )


def _bounded_step(current: Decimal, target: Decimal, bounds: TuningBoundsV1) -> Decimal:
    delta = target - current
    if abs(delta) > bounds.max_step_pp:
        delta = bounds.max_step_pp if delta > 0 else -bounds.max_step_pp
    stepped = current + delta
    stepped = max(bounds.min_threshold_pp, min(bounds.max_threshold_pp, stepped))
    return stepped.quantize(Decimal("0.1"))


def tune_once(
    service: Any,
    *,
    bounds: TuningBoundsV1 | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate history and, when authorized, apply one bounded threshold step.

    Never raises for policy reasons: every outcome is a report, and applied
    changes are written through ``EvolutionService.configure`` so the audit
    trail (revision + updated_by) is the same as an operator edit.
    """
    from hypertrade.arc.evolution import EvolutionConfig

    bounds = bounds or TuningBoundsV1()
    now = now or datetime.now(UTC)
    receipt_id = f"tune_{now.strftime('%Y%m%d')}"
    if _receipt_exists(service.db, receipt_id):
        # At most one tuning action per day: callers may poll hourly without
        # ever compounding bounded steps into a runaway adjustment.
        return {"status": "already_tuned_today"}
    state = service.status()
    config = EvolutionConfig.model_validate(state["config"])
    if not config.meta_tuning_enabled:
        return {"status": "disabled"}
    report = evaluate_tuning(service.db, config.threshold_pp, bounds=bounds, now=now)
    payload: dict[str, Any] = {"status": report.recommendation, "report": report.model_dump()}
    if (
        report.recommendation in {"lower", "raise"}
        and config.meta_tuning_auto_apply
        and report.recommended_threshold_pp is not None
    ):
        stepped = _bounded_step(
            config.threshold_pp, Decimal(report.recommended_threshold_pp), bounds
        )
        if stepped != config.threshold_pp:
            applied = service.configure(
                config.model_copy(update={"threshold_pp": stepped}),
                revision=state["revision"],
                actor=META_TUNER_ACTOR,
            )
            report = report.model_copy(
                update={
                    "recommendation": "applied",
                    "applied": True,
                    "applied_revision": applied["revision"],
                    "recommended_threshold_pp": str(stepped),
                }
            )
            payload = {"status": "applied", "report": report.model_dump()}
    _record_receipt(service.db, report, now, payload["status"], receipt_id)
    return payload


def _receipt_exists(db: Database, receipt_id: str) -> bool:
    with db.session() as session:
        return session.get(EvolutionCycle, receipt_id) is not None


def _record_receipt(
    db: Database,
    report: EvolutionTuningV1,
    now: datetime,
    status: str,
    receipt_id: str,
) -> None:
    with db.session() as session:
        if session.get(EvolutionCycle, receipt_id) is not None:
            return
        session.add(
            EvolutionCycle(
                id=receipt_id,
                status="meta_tuning",
                payload_json={"tuning_status": status, "report": report.model_dump()},
            )
        )
