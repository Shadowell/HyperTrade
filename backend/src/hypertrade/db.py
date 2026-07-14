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
