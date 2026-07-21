from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MarketTicker(Base, TimestampMixin):
    __tablename__ = "market_tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inst_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    inst_type: Mapped[str] = mapped_column(String(32), default="SWAP", index=True)
    last: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    volume_ccy_24h: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    change_utc0_pct: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("run"))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    report_markdown: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class TraceEvent(Base, TimestampMixin):
    __tablename__ = "trace_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("evt"))
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentSession(Base, TimestampMixin):
    """Durable operator context; secrets and private reasoning never belong here."""

    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ses"))
    title: Mapped[str] = mapped_column(String(200), default="Agent Session")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    surface: Mapped[str] = mapped_column(String(32), default="api", index=True)
    provider_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_markdown: Mapped[str] = mapped_column(Text, default="")
    last_event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(128), default="operator", index=True)


class AgentTask(Base, TimestampMixin):
    """Canonical durable state for one bounded Agent task."""

    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("task"))
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), default="chat_run", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    objective: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    resource_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    control_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checkpoint_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    error_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TaskNodeRun(Base, TimestampMixin):
    """One auditable attempt of a task graph node."""

    __tablename__ = "task_node_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tnode"))
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    node_key: Mapped[str] = mapped_column(String(96), index=True)
    role_key: Mapped[str] = mapped_column(String(96), default="", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    depends_on_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TaskCheckpoint(Base, TimestampMixin):
    """Minimal resumable state; external artifacts remain referenced, not copied."""

    __tablename__ = "task_checkpoints"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_checkpoint_sequence"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tcp"))
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    node_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state_hash: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    resume_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class TaskEvent(Base, TimestampMixin):
    """Append-only, cursor-addressable task event safe for operator surfaces."""

    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_task_event_sequence"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tevt"))
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(96), index=True)
    actor: Mapped[str] = mapped_column(String(128), default="system", index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    redaction_version: Mapped[int] = mapped_column(Integer, default=1)


class AgentMission(Base, TimestampMixin):
    """Canonical projection for the Professional Agent Runtime.

    New missions never dual-write AgentTask or AgentRun.  The append-only event
    stream below is the audit source; this row is a rebuildable read model.
    """

    __tablename__ = "agent_missions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mis"))
    objective: Mapped[str] = mapped_column(Text)
    original_objective: Mapped[str] = mapped_column(Text)
    success_criteria_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    constraints_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    permission_profile_ref: Mapped[str] = mapped_column(String(128), index=True)
    context_policy_ref: Mapped[str] = mapped_column(String(128), index=True)
    active_plan_version: Mapped[int] = mapped_column(Integer, default=0)
    current_step_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    event_protocol_version: Mapped[int] = mapped_column(Integer, default=1)
    replay_status: Mapped[str] = mapped_column(
        String(32), default="legacy_non_replayable", index=True
    )
    projection_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    quarantine_reason: Mapped[str] = mapped_column(Text, default="")
    completion_proof_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lease_fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    control_requested: Mapped[str] = mapped_column(String(32), default="", index=True)
    terminal_summary: Mapped[str] = mapped_column(Text, default="")
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(128), default="operator", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class AgentThread(Base):
    """Rebuildable projection for one server-owned conversation Thread."""

    __tablename__ = "agent_threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), default="default", index=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Agent Thread")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    retention: Mapped[str] = mapped_column(String(32), default="durable")
    active_turn_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    event_cursor: Mapped[int] = mapped_column(Integer, default=0)
    projection_hash: Mapped[str] = mapped_column(String(64), index=True)
    quarantine_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentTurn(Base):
    """Rebuildable Turn projection; uniqueness binds a client message to content."""

    __tablename__ = "agent_turns"
    __table_args__ = (
        UniqueConstraint("thread_id", "client_message_id", name="uq_agent_turn_client_message"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    client_message_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_item_id: Mapped[str] = mapped_column(String(32))
    response_item_id: Mapped[str] = mapped_column(String(32), default="")
    mission_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    resolved_context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentThreadItem(Base):
    """Public, bounded Item projection produced only by the Thread reducer."""

    __tablename__ = "agent_thread_items"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence", "id", name="uq_agent_thread_item_sequence"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(32), index=True)
    turn_id: Mapped[str] = mapped_column(String(32), index=True)
    item_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentThreadEvent(Base):
    """Append-only canonical event envelope for Thread/Turn/Item replay."""

    __tablename__ = "agent_thread_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "thread_sequence", name="uq_agent_thread_event_sequence"),
        UniqueConstraint("thread_id", "aggregate_version", name="uq_agent_thread_event_version"),
        UniqueConstraint("thread_id", "idempotency_key", name="uq_agent_thread_event_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), default="thread")
    aggregate_version: Mapped[int] = mapped_column(Integer)
    thread_sequence: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    reducer_version: Mapped[int] = mapped_column(Integer, default=1)
    tenant_id: Mapped[str] = mapped_column(String(128), default="default", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    causation_id: Mapped[str] = mapped_column(String(64), default="")
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    actor: Mapped[str] = mapped_column(String(128), default="runtime", index=True)
    policy_snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentThreadLease(Base):
    """Operational fencing state kept outside event-reduced public projections."""

    __tablename__ = "agent_thread_leases"

    thread_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(128), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentMissionEvent(Base):
    """Append-only, cursor-addressable Mission event without private reasoning."""

    __tablename__ = "agent_mission_events"
    __table_args__ = (
        UniqueConstraint("mission_id", "sequence", name="uq_agent_mission_event_sequence"),
        UniqueConstraint(
            "mission_id", "aggregate_version", name="uq_agent_mission_event_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mevt"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), default="mission")
    aggregate_version: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    reducer_version: Mapped[int] = mapped_column(Integer, default=0)
    causation_id: Mapped[str] = mapped_column(String(64), default="")
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    actor: Mapped[str] = mapped_column(String(128), default="runtime", index=True)
    policy_snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    payload_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentPolicyDecision(Base):
    __tablename__ = "agent_policy_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentApproval(Base):
    __tablename__ = "agent_approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), index=True)
    mission_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    grant_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentDispatchIntent(Base):
    __tablename__ = "agent_dispatch_intents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    intent_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mission_id: Mapped[str] = mapped_column(String(64), index=True)
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    call_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentEffectAuditEvent(Base):
    __tablename__ = "agent_effect_audit_events"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "sequence", name="uq_agent_effect_event_sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentEffectCircuit(Base):
    __tablename__ = "agent_effect_circuits"

    capability_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentPlanVersion(Base):
    """Immutable plan version; replans append and never overwrite history."""

    __tablename__ = "agent_plan_versions"
    __table_args__ = (UniqueConstraint("mission_id", "version", name="uq_agent_plan_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("plan"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentStepAttempt(Base):
    """Append-only execution attempt for one immutable Mission plan step."""

    __tablename__ = "agent_step_attempts"
    __table_args__ = (
        UniqueConstraint(
            "mission_id",
            "plan_version",
            "step_id",
            "attempt",
            name="uq_agent_step_attempt",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sat"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    plan_version: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String(64), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    observation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentSteeringEvent(Base):
    """Immutable operator steer; applying it creates a new Plan version."""

    __tablename__ = "agent_steering_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("steer"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    plan_version_before: Mapped[int] = mapped_column(Integer, default=0)
    instruction: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentCapabilitySnapshot(Base, TimestampMixin):
    """Versioned reviewed capability; discovery cannot write this table directly."""

    __tablename__ = "agent_capability_snapshots"
    __table_args__ = (
        UniqueConstraint("capability_id", "version", name="uq_agent_capability_version"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("caps"))
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(32))
    review_status: Mapped[str] = mapped_column(String(32), index=True)
    health: Mapped[str] = mapped_column(String(32), index=True)
    contract_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_hash: Mapped[str] = mapped_column(String(64), index=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    reviewed_by: Mapped[str] = mapped_column(String(128), default="")
    review_reason: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fresh_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class AgentCapabilityProposal(Base, TimestampMixin):
    """Untrusted discovered capability pending an explicit administrator decision."""

    __tablename__ = "agent_capability_proposals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("capp"))
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(32))
    discovered_from: Mapped[str] = mapped_column(Text)
    discovery_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(128), default="discovery", index=True)


class AgentCapabilityReview(Base):
    """Append-only idempotent review fact for one proposal."""

    __tablename__ = "agent_capability_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("capr"))
    proposal_id: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentToolObservation(Base):
    """Bounded validated tool outcome; raw results and credentials are excluded."""

    __tablename__ = "agent_tool_observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tobs"))
    request_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    step_id: Mapped[str] = mapped_column(String(64), index=True)
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    capability_version: Mapped[str] = mapped_column(String(32))
    contract_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    result_preview_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_category: Mapped[str] = mapped_column(String(32), default="", index=True)
    retry_action: Mapped[str] = mapped_column(String(32), default="none", index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentCapabilityCircuit(Base, TimestampMixin):
    """Persistent circuit projection for restart-safe connector protection."""

    __tablename__ = "agent_capability_circuits"

    capability_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="closed", index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class AgentContextPack(Base):
    """Immutable, replayable per-step context manifest; no raw transcript is stored."""

    __tablename__ = "agent_context_packs"
    __table_args__ = (
        UniqueConstraint(
            "mission_id",
            "plan_version",
            "step_id",
            "attempt",
            name="uq_agent_context_attempt",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ctxp"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    plan_version: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String(64), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    policy_ref: Mapped[str] = mapped_column(String(128), index=True)
    budget_tokens: Mapped[int] = mapped_column(Integer)
    used_tokens: Mapped[int] = mapped_column(Integer)
    manifest_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    decisions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentMissionArtifact(Base):
    """Mission-owned artifact metadata; large or raw data remains at a stable external ref."""

    __tablename__ = "agent_mission_artifacts"
    __table_args__ = (
        UniqueConstraint("mission_id", "content_hash", name="uq_agent_mission_artifact_hash"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mart"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(240))
    media_type: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    external_ref: Mapped[str] = mapped_column(Text, default="")
    inline_preview_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    producer_ref: Mapped[str] = mapped_column(String(300), index=True)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    supersedes_artifact_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="current", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentArtifactRelation(Base):
    """Immutable source/supersede edge used by artifact lineage and completion validation."""

    __tablename__ = "agent_artifact_relations"
    __table_args__ = (
        UniqueConstraint(
            "from_artifact_id",
            "to_ref",
            "relation_type",
            name="uq_agent_artifact_relation",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("arel"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    from_artifact_id: Mapped[str] = mapped_column(String(32), index=True)
    to_ref: Mapped[str] = mapped_column(Text)
    relation_type: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentAssignment(Base, TimestampMixin):
    """Bounded supervisor work item; role and budget are immutable after dispatch."""

    __tablename__ = "agent_assignments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("asgn"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    role_id: Mapped[str] = mapped_column(String(64), index=True)
    objective: Mapped[str] = mapped_column(Text)
    capability_id: Mapped[str] = mapped_column(String(160), index=True)
    depends_on_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    context_pack_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    reservation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")


class AgentBudgetReservation(Base, TimestampMixin):
    """Atomic reservation prevents parallel branches from oversubscribing Mission budget."""

    __tablename__ = "agent_budget_reservations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bres"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    assignment_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tokens: Mapped[int] = mapped_column(Integer)
    tool_calls: Mapped[int] = mapped_column(Integer)
    model_calls: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="reserved", index=True)


class AgentHandoff(Base):
    """Structured Agent output with refs and hash; hidden transcripts are never persisted."""

    __tablename__ = "agent_handoffs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("hndf"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    assignment_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    role_id: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text)
    claims_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentConflict(Base):
    """Contradictory claims remain explicit until an evidence-bound resolution is recorded."""

    __tablename__ = "agent_conflicts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("cnfl"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    claim_key: Mapped[str] = mapped_column(String(160), index=True)
    values_json: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="unresolved", index=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentSandboxRun(Base):
    """Auditable isolated run projection; workspace contents are not retained."""

    __tablename__ = "agent_sandbox_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sbox"))
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    assignment_ref: Mapped[str] = mapped_column(String(300), index=True)
    context_pack_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), index=True)
    patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    commands_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentSandboxArtifact(Base):
    """Content-addressed metadata for an ephemeral sandbox output."""

    __tablename__ = "agent_sandbox_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sandbox_run_id: Mapped[str] = mapped_column(String(32), index=True)
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(300), default="")
    media_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    preview: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentSandboxImportReview(Base):
    """Human review fact only; acceptance is not an external BitPro import operation."""

    __tablename__ = "agent_sandbox_import_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("srev"))
    sandbox_run_id: Mapped[str] = mapped_column(String(32), index=True)
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    patch_hash: Mapped[str] = mapped_column(String(64), index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), index=True)
    target_contract: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    external_write_performed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RagDocument(Base, TimestampMixin):
    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("doc"))
    source_path: Mapped[str] = mapped_column(Text, unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text, default="")


class RagChunk(Base, TimestampMixin):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("chk"))
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    source_path: Mapped[str] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    embedding_vector: Mapped[list[float]] = mapped_column(JSON, default=list)


class MemoryItem(Base, TimestampMixin):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mem"))
    kind: Mapped[str] = mapped_column(String(64), default="observation", index=True)
    content: Mapped[str] = mapped_column(Text)
    source_run_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    source_tool: Mapped[str] = mapped_column(String(128), default="")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    importance: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.50"))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.70"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


class MemoryAssertion(Base, TimestampMixin):
    """Source-bound claim whose lifecycle is governed separately from MemoryItem."""

    __tablename__ = "memory_assertions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("masr"))
    schema_version: Mapped[str] = mapped_column(
        String(64), default="memory_assertion.v1", index=True
    )
    claim: Mapped[str] = mapped_column(Text)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    linked_memory_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="agent", index=True)
    reviewed_by: Mapped[str] = mapped_column(String(128), default="")
    review_reason: Mapped[str] = mapped_column(Text, default="")
    audit_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class MemoryAssertionRelation(Base, TimestampMixin):
    """Immutable supports/conflicts/supersedes edge between assertions."""

    __tablename__ = "memory_assertion_relations"
    __table_args__ = (
        UniqueConstraint(
            "from_assertion_id",
            "to_assertion_id",
            "relation_type",
            name="uq_memory_assertion_relation",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mrel"))
    from_assertion_id: Mapped[str] = mapped_column(String(32), index=True)
    to_assertion_id: Mapped[str] = mapped_column(String(32), index=True)
    relation_type: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="operator", index=True)


class MemoryAssertionReview(Base, TimestampMixin):
    """Idempotent human decision over one proposed assertion."""

    __tablename__ = "memory_assertion_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mrev"))
    assertion_id: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)


class SkillProposal(Base, TimestampMixin):
    """Untrusted code-free skill candidate; never loaded directly by a role."""

    __tablename__ = "skill_proposals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("skp"))
    skill_key: Mapped[str] = mapped_column(String(96), index=True)
    base_release_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    definition_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    static_check_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diff_text: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    proposed_by: Mapped[str] = mapped_column(String(128), default="agent", index=True)
    audit_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class SkillEvaluation(Base, TimestampMixin):
    """Privacy-safe attestation imported from the isolated evaluation runtime."""

    __tablename__ = "skill_evaluations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("skev"))
    proposal_id: Mapped[str] = mapped_column(String(32), index=True)
    proposal_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    suite_version: Mapped[str] = mapped_column(String(96), index=True)
    baseline_id: Mapped[str] = mapped_column(String(128), index=True)
    case_count: Mapped[int] = mapped_column(Integer)
    passed_count: Mapped[int] = mapped_column(Integer)
    artifact_hash: Mapped[str] = mapped_column(String(64), index=True)
    runtime: Mapped[str] = mapped_column(String(64), index=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    evaluated_by: Mapped[str] = mapped_column(String(128), index=True)


class SkillApproval(Base, TimestampMixin):
    """Immutable administrator decision for approve/reject/rollback."""

    __tablename__ = "skill_approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("skap"))
    proposal_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    release_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    target_release_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)


class SkillRelease(Base, TimestampMixin):
    """Immutable approved definition; status changes only reflect active pointer history."""

    __tablename__ = "skill_releases"
    __table_args__ = (UniqueConstraint("skill_key", "version", name="uq_skill_release_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("skrel"))
    skill_key: Mapped[str] = mapped_column(String(96), index=True)
    version: Mapped[int] = mapped_column(Integer)
    proposal_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    definition_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    approved_by: Mapped[str] = mapped_column(String(128), index=True)
    approval_reason: Mapped[str] = mapped_column(Text)
    audit_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class SkillActivePointer(Base, TimestampMixin):
    """Mutable pointer; releases themselves remain immutable and recoverable."""

    __tablename__ = "skill_active_pointers"

    skill_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    active_release_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[str] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(Text)


class PortfolioAssessment(Base, TimestampMixin):
    """Immutable bounded portfolio lifecycle assessment; never an execution instruction."""

    __tablename__ = "portfolio_assessments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pasmt"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    world_state_ref: Mapped[str] = mapped_column(String(128), default="", index=True)
    input_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    strategy_assessments_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    pairwise_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommendations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)


class StrategyLifecycleReview(Base, TimestampMixin):
    """Human accept/reject/hold fact with no path to trading adapters."""

    __tablename__ = "strategy_lifecycle_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("slrev"))
    assessment_id: Mapped[str] = mapped_column(String(32), index=True)
    recommendation_id: Mapped[str] = mapped_column(String(96), index=True)
    strategy_card_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    recommendation_action: Mapped[str] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)


class PortfolioObservationWindow(Base, TimestampMixin):
    """Immutable bounded statistics; raw BitPro time series are never persisted here."""

    __tablename__ = "portfolio_observation_windows"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pwin"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, index=True)
    bucket_minutes: Mapped[int] = mapped_column(Integer, index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    strategy_summaries_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    pairwise_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(128), index=True)


class BitProStrategyEvidenceRecord(Base):
    """Validated BitPro evidence reference; source time-series remain external."""

    __tablename__ = "bitpro_strategy_evidence_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bpse"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    evidence_type: Mapped[str] = mapped_column(String(48), index=True)
    source_layer: Mapped[str] = mapped_column(String(24), default="", index=True)
    source_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    source_hash: Mapped[str] = mapped_column(String(80), default="", index=True)
    content_hash: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    refs_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PaperCohortSnapshot(Base, TimestampMixin):
    """Immutable comparability and label proposal projection over committed facts."""

    __tablename__ = "paper_cohort_snapshots"
    __table_args__ = (
        UniqueConstraint("cohort_key", "version_number", name="uq_paper_cohort_version"),
        UniqueConstraint("cohort_key", "source_hash", name="uq_paper_cohort_source"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pcoh"))
    cohort_key: Mapped[str] = mapped_column(String(64), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    observation_window_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    intake_count: Mapped[int] = mapped_column(Integer)
    comparable_count: Mapped[int] = mapped_column(Integer)
    proposal_count: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(128), index=True)


class PaperCohortLabelDecision(Base, TimestampMixin):
    """Human label review fact with no paper or execution authority."""

    __tablename__ = "paper_cohort_label_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pcld"))
    cohort_snapshot_id: Mapped[str] = mapped_column(String(32), index=True)
    proposal_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_card_id: Mapped[str] = mapped_column(String(64), index=True)
    proposed_label: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)


class ShadowPortfolioProposal(Base, TimestampMixin):
    """Immutable hypothetical allocation research; never an order instruction."""

    __tablename__ = "shadow_portfolio_proposals"
    __table_args__ = (
        UniqueConstraint("portfolio_key", "version_number", name="uq_shadow_portfolio_version"),
        UniqueConstraint("portfolio_key", "source_hash", name="uq_shadow_portfolio_source"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("shpf"))
    portfolio_key: Mapped[str] = mapped_column(String(64), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    cohort_snapshot_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    observation_window_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    intake_count: Mapped[int] = mapped_column(Integer)
    eligible_count: Mapped[int] = mapped_column(Integer)
    scenario_count: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(128), index=True)


class ShadowPortfolioReviewDecision(Base, TimestampMixin):
    """Human research review with no capital, paper, or execution authority."""

    __tablename__ = "shadow_portfolio_review_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("shrv"))
    proposal_id: Mapped[str] = mapped_column(String(32), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    template: Mapped[str] = mapped_column(String(48), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("job"))
    kind: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")


class PaperSession(Base, TimestampMixin):
    __tablename__ = "paper_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("paper"))
    name: Mapped[str] = mapped_column(String(128), default="Default Paper Session")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    equity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaperPosition(Base, TimestampMixin):
    __tablename__ = "paper_positions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pos"))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    mark_price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    notional: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)


class PaperOrder(Base, TimestampMixin):
    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ord"))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    target_notional: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class PaperFill(Base, TimestampMixin):
    __tablename__ = "paper_fills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("fill"))
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    fee: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source_ticker_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperEvent(Base, TimestampMixin):
    __tablename__ = "paper_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pevt"))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BitProPaperMonitorSnapshot(Base, TimestampMixin):
    __tablename__ = "bitpro_paper_monitor_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bpms"))
    scope_key: Mapped[str] = mapped_column(String(64), default="all", index=True)
    strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    previous_snapshot_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    dashboard_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    running_strategies_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    monitor_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    equity_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    drift_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class MonitorDefinition(Base, TimestampMixin):
    __tablename__ = "monitor_definitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mon"))
    name: Mapped[str] = mapped_column(String(160))
    monitor_type: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schedule_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notification_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MonitorRun(Base, TimestampMixin):
    __tablename__ = "monitor_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mrun"))
    monitor_id: Mapped[str] = mapped_column(String(32), index=True)
    monitor_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    previous_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_tools_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metric_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    drift_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    alerts_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    data_gaps_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_actions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class MonitorAlertEvent(Base, TimestampMixin):
    __tablename__ = "monitor_alert_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("alrt"))
    monitor_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(32), default="warning", index=True)
    code: Mapped[str] = mapped_column(String(96), index=True)
    message: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    threshold_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metric_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)


class StrategyResearch(Base, TimestampMixin):
    __tablename__ = "strategy_research"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("srch"))
    prompt: Mapped[str] = mapped_column(Text)
    strategy_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    report_markdown: Mapped[str] = mapped_column(Text)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BacktestRun(Base, TimestampMixin):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bt"))
    research_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    strategy_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    start_cash: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    end_value: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    total_return_pct: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    report_markdown: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class LiveOrderIntent(Base, TimestampMixin):
    __tablename__ = "live_order_intents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("loi"))
    environment: Mapped[str] = mapped_column(String(32), default="testnet", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_approval", index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    order_type: Mapped[str] = mapped_column(String(32), default="market")
    size: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    price: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64), default="operator")
    source_run_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    risk_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    risk_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    execution_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    exchange_order_id: Mapped[str] = mapped_column(String(128), default="")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrategyExperiment(Base, TimestampMixin):
    __tablename__ = "strategy_experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("exp"))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    research_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    backtest_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    report_markdown: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ResearchMandate(Base, TimestampMixin):
    """Operator-owned policy boundary for one autonomous research program."""

    __tablename__ = "research_mandates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rman"))
    name: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    market_type: Mapped[str] = mapped_column(String(32), default="SWAP", index=True)
    symbols_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeframes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    strategy_categories_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    paper_promotion_mode: Mapped[str] = mapped_column(
        String(32), default="manual_approval", index=True
    )
    live_mode: Mapped[str] = mapped_column(String(32), default="disabled", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    audit_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ResearchJob(Base, TimestampMixin):
    """Durable research-work record; later sprints add BitPro execution stages."""

    __tablename__ = "research_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rjob"))
    mandate_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    prompt: Mapped[str] = mapped_column(Text)
    strategy_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_run_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    transition_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    external_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default="")


class ResearchExperimentEvidence(Base, TimestampMixin):
    """Bounded HyperTrade ledger references for BitPro-owned research artifacts."""

    __tablename__ = "research_experiment_evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rexp"))
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    mandate_id: Mapped[str] = mapped_column(String(32), index=True)
    variant_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    strategy_key: Mapped[str] = mapped_column(String(128), index=True)
    bitpro_strategy_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    result_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    windows_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gate_results_json: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    rejection_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    tool_calls_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ResearchEvidence(Base, TimestampMixin):
    """Append-only evidence content; only lifecycle fields may transition."""

    __tablename__ = "research_evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("evi"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    claim: Mapped[str] = mapped_column(Text)
    task_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    node_run_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    role_key: Mapped[str] = mapped_column(String(96), default="", index=True)
    symbols_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeframes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    market_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sources_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[Decimal] = mapped_column(Numeric(10, 8))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supersedes_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    lifecycle_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(128), default="evidence_service", index=True)


class ResearchEvidenceRelation(Base, TimestampMixin):
    """Typed immutable edge between two evidence records."""

    __tablename__ = "research_evidence_relations"
    __table_args__ = (
        UniqueConstraint(
            "from_evidence_id",
            "to_evidence_id",
            "relation_type",
            name="uq_research_evidence_relation",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("erel"))
    from_evidence_id: Mapped[str] = mapped_column(String(32), index=True)
    to_evidence_id: Mapped[str] = mapped_column(String(32), index=True)
    relation_type: Mapped[str] = mapped_column(String(32), index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="evidence_service", index=True)


class ExperimentManifest(Base, TimestampMixin):
    """Immutable semantic inputs for a reproducible research experiment."""

    __tablename__ = "experiment_manifests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("expm"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    strategy_key: Mapped[str] = mapped_column(String(128), index=True)
    mandate_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    research_job_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    canonical_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), default="experiment_ledger", index=True)


class ExperimentExecution(Base, TimestampMixin):
    """Append-only attempts for one immutable experiment manifest."""

    __tablename__ = "experiment_executions"
    __table_args__ = (
        UniqueConstraint("manifest_id", "attempt", name="uq_experiment_execution_attempt"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("exex"))
    manifest_id: Mapped[str] = mapped_column(String(32), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    task_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    research_job_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    retry_of_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    force_reason: Mapped[str] = mapped_column(Text, default="")
    external_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), default="experiment_ledger", index=True)


class ExperimentEvidenceLink(Base, TimestampMixin):
    """Immutable association from an execution to bounded evidence references."""

    __tablename__ = "experiment_evidence_links"
    __table_args__ = (
        UniqueConstraint("execution_id", "evidence_id", name="uq_experiment_evidence_link"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("exel"))
    execution_id: Mapped[str] = mapped_column(String(32), index=True)
    evidence_id: Mapped[str] = mapped_column(String(32), index=True)
    evidence_kind: Mapped[str] = mapped_column(String(32), default="evidence_v2", index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="experiment_ledger", index=True)


class StrategyOutcome(Base):
    """Immutable settled strategy result bound to canonical source facts."""

    __tablename__ = "strategy_outcomes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sout"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    outcome_type: Mapped[str] = mapped_column(String(48), index=True)
    strategy_lineage_id: Mapped[str] = mapped_column(String(32), index=True)
    strategy_version_id: Mapped[str] = mapped_column(String(32), index=True)
    strategy_card_id: Mapped[str] = mapped_column(String(64), index=True)
    manifest_id: Mapped[str] = mapped_column(String(32), index=True)
    experiment_execution_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    mission_id: Mapped[str] = mapped_column(String(32), index=True)
    observation_window_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    corrects_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    supersedes_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StrategyLessonCandidate(Base):
    """Review-gated lesson projection; proposed lessons are never prompt-usable."""

    __tablename__ = "strategy_lesson_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("lesn"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    stance: Mapped[str] = mapped_column(String(24), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lesson_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    reviewed_by: Mapped[str] = mapped_column(String(128), default="", index=True)
    review_reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class StrategyLessonReview(Base):
    """Append-only human review fact for one lesson candidate."""

    __tablename__ = "strategy_lesson_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("lrev"))
    lesson_id: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StrategyEvolutionRun(Base):
    """Auditable bounded proposal run; it grants no execution authority."""

    __tablename__ = "strategy_evolution_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("evol"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    parent_version_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mandate_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    assessment_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StrategyEvolutionCandidate(Base):
    """Immutable accepted/rejected candidate; no BitPro or trading payload is stored."""

    __tablename__ = "strategy_evolution_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ecand"))
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    parent_version_id: Mapped[str] = mapped_column(String(32), index=True)
    candidate_version_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    manifest_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    experiment_execution_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    proposal_kind: Mapped[str] = mapped_column(String(24), index=True)
    candidate_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StrategyDiscoveryRun(Base):
    """Auditable new-strategy discovery run with no trading authority."""

    __tablename__ = "strategy_discovery_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("disc"))
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    research_mandate_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mandate_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StrategyDiscoveryCandidate(Base):
    """Immutable phenomenon, hypothesis, novelty and candidate terminal fact."""

    __tablename__ = "strategy_discovery_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("dcand"))
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phenomenon_hash: Mapped[str] = mapped_column(String(64), index=True)
    hypothesis_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    strategy_family: Mapped[str] = mapped_column(String(48), index=True)
    bitpro_strategy_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    manifest_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    experiment_execution_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    strategy_version_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    phenomenon_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    hypothesis_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    novelty_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StrategyLineage(Base, TimestampMixin):
    """Stable mandate-scoped strategy identity; never stores mutable evidence."""

    __tablename__ = "strategy_lineages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sline"))
    lineage_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mandate_id: Mapped[str] = mapped_column(String(32), index=True)
    strategy_key: Mapped[str] = mapped_column(String(128), index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="strategy_card_v2", index=True)


class StrategyVersion(Base, TimestampMixin):
    """Immutable version identity bound one-to-one to an ExperimentManifest."""

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("lineage_id", "version_number", name="uq_strategy_version_number"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sver"))
    lineage_id: Mapped[str] = mapped_column(String(32), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    manifest_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    manifest_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    strategy_spec_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="strategy_card_v2", index=True)


class StrategyCardSnapshot(Base, TimestampMixin):
    """Immutable, rebuildable projection over authoritative research facts."""

    __tablename__ = "strategy_card_snapshots"
    __table_args__ = (
        UniqueConstraint("version_id", "content_hash", name="uq_strategy_card_content"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("scsnap"))
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    lineage_id: Mapped[str] = mapped_column(String(32), index=True)
    version_id: Mapped[str] = mapped_column(String(32), index=True)
    schema_version: Mapped[str] = mapped_column(String(64), index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), index=True)
    completeness_score: Mapped[Decimal] = mapped_column(Numeric(6, 5))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    card_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(128), default="strategy_card_v2", index=True)


class StrategyCardLifecycleDecision(Base, TimestampMixin):
    """Human review fact; it cannot authorize paper, live, order, or capital actions."""

    __tablename__ = "strategy_card_lifecycle_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("scdec"))
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    lineage_id: Mapped[str] = mapped_column(String(32), index=True)
    version_id: Mapped[str] = mapped_column(String(32), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(32), index=True)
    target_status: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    decided_by: Mapped[str] = mapped_column(String(128), index=True)


class RobustnessValidationRun(Base, TimestampMixin):
    """Versioned fail-closed validation over one immutable experiment execution."""

    __tablename__ = "robustness_validation_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rvld"))
    experiment_execution_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), index=True)
    policy_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    final_status: Mapped[str] = mapped_column(String(32), index=True)
    gate_results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(
        String(128), default="robustness_validation", index=True
    )


class RobustnessScenarioResult(Base, TimestampMixin):
    """Bounded BitPro result projection for one robustness scenario."""

    __tablename__ = "robustness_scenario_results"
    __table_args__ = (
        UniqueConstraint("validation_run_id", "scenario_id", name="uq_robustness_scenario"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rscn"))
    validation_run_id: Mapped[str] = mapped_column(String(32), index=True)
    scenario_id: Mapped[str] = mapped_column(String(96), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    window_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    costs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    regime: Mapped[str] = mapped_column(String(64), default="", index=True)
    result_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gate_results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaperPromotion(Base, TimestampMixin):
    """Human-approved bridge from validated research evidence to BitPro paper only."""

    __tablename__ = "paper_promotions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ppr"))
    mandate_id: Mapped[str] = mapped_column(String(32), index=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    evidence_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    strategy_key: Mapped[str] = mapped_column(String(128), index=True)
    bitpro_strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_paper_approval", index=True)
    request_reason: Mapped[str] = mapped_column(Text, default="")
    approval_reason: Mapped[str] = mapped_column(Text, default="")
    approval_idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    approved_by: Mapped[str] = mapped_column(String(128), default="")
    paper_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    observation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    transition_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class PaperReviewRequest(Base, TimestampMixin):
    """Operator queue item derived from read-only paper observation evidence."""

    __tablename__ = "paper_review_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prr"))
    promotion_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ResearchTrigger(Base, TimestampMixin):
    """Disabled-by-default rule that may create only a bounded Agent Task."""

    __tablename__ = "research_triggers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rtrg"))
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(48), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    mandate_id: Mapped[str] = mapped_column(String(32), index=True)
    objective_template: Mapped[str] = mapped_column(Text)
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schedule_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task_budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    daily_quota: Mapped[int] = mapped_column(Integer, default=2)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    audit_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(128), default="operator", index=True)


class ResearchTriggerFire(Base, TimestampMixin):
    """Immutable trigger decision and optional Task reference."""

    __tablename__ = "research_trigger_fires"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rfire"))
    trigger_id: Mapped[str] = mapped_column(String(32), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_type: Mapped[str] = mapped_column(String(48), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    event_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task_id: Mapped[str] = mapped_column(String(32), default="", index=True)


class ResearchTriggerControl(Base, TimestampMixin):
    """Singleton persistent global kill switch for background Task creation."""

    __tablename__ = "research_trigger_control"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="global")
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(128), default="operator")


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        connect_args: dict[str, Any] = {}
        engine_kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            if url == "sqlite:///:memory:":
                engine_kwargs["poolclass"] = StaticPool
        self.engine = create_engine(
            url, echo=echo, future=True, connect_args=connect_args, **engine_kwargs
        )
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
