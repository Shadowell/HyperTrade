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
    previous_snapshot_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    dashboard_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    running_strategies_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    monitor_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    equity_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    drift_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


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
