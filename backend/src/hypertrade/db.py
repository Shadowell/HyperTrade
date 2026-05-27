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
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[list[float]] = mapped_column(JSON, default=list)


class MemoryItem(Base, TimestampMixin):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mem"))
    kind: Mapped[str] = mapped_column(String(64), default="observation", index=True)
    content: Mapped[str] = mapped_column(Text)
    source_run_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    source_tool: Mapped[str] = mapped_column(String(128), default="")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("job"))
    kind: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")


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
