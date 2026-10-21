"""Persistent product scheduling and diagnostic receipts; ARC owns research execution."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hypertrade.db import Base, TimestampMixin


class EvolutionControl(Base, TimestampMixin):
    __tablename__ = "arc_evolution_control"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="global")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[str] = mapped_column(String(128), default="operator")


class EvolutionCycle(Base, TimestampMixin):
    __tablename__ = "arc_evolution_cycles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvolutionContinuation(Base, TimestampMixin):
    """Latest source-bound eligibility; historical checks live in acceptance entries."""

    __tablename__ = "arc_evolution_continuations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvolutionAcceptance(Base, TimestampMixin):
    __tablename__ = "arc_evolution_acceptance"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvolutionAlert(Base, TimestampMixin):
    """Operator-visible condition raised by the evolution loop; silent stalls are defects."""

    __tablename__ = "arc_evolution_alerts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning", index=True)
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message: Mapped[str] = mapped_column(String(512), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_result: Mapped[str] = mapped_column(String(64), default="")


class ArcRuntimeError(Base, TimestampMixin):
    """Redacted failure receipt; container logs do not survive a deploy."""

    __tablename__ = "arc_runtime_errors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(64), index=True)
    mission_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    exception_type: Mapped[str] = mapped_column(String(256), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    recent_messages_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    frames_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    traceback: Mapped[str] = mapped_column(Text, default="")
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ArcModelExchange(Base, TimestampMixin):
    """Append-only raw provider reply, bound to the request hash and context snapshot."""

    __tablename__ = "arc_model_exchanges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    context_record_id: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    reasoning_content: Mapped[str] = mapped_column(Text, default="")
    tool_calls_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    truncated_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ArcForwardOutcome(Base, TimestampMixin):
    """One finished BitPro race lane: what happened to a challenger against its parent."""

    __tablename__ = "arc_forward_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "parent_strategy_id",
            "challenger_strategy_id",
            name="uq_arc_forward_outcome_pair",
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(32))
    parent_strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    challenger_strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    slot_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    verdict_source: Mapped[str] = mapped_column(String(32), default="race_judge")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_sha256: Mapped[str] = mapped_column(String(64), default="")
    lineage_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    mission_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    changes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
