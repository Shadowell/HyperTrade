"""Durable runtime receipts for the evolution loop.

Worker containers are rebuilt on every deploy, so stdout is not evidence. Failures and
raw model replies are written here, redacted with the provider-context policy, and
survive restarts. Repeated identical failures fold into one row (occurrence count and
a bounded list of recent distinct messages) so a loop failing every minute cannot grow
the table without bound.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from hypertrade.agent.compaction import digest, sanitize_context
from hypertrade.arc.evolution_models import ArcModelExchange, ArcRuntimeError
from hypertrade.db import Database

logger = logging.getLogger(__name__)

_MESSAGE_CHARS = 2_000
_TRACEBACK_CHARS = 64_000
_FRAMES = 20
_RECENT_MESSAGES = 20
_REPLY_CHARS = 512_000


def _store_database() -> Database | None:
    from hypertrade.arc import store

    return store._database


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return "…[head truncated]\n" + text[-limit:], True


def _redacted_text(value: Any) -> str:
    return str(sanitize_context(str(value)))


def describe_exception(exc: BaseException) -> dict[str, Any]:
    """Redacted, bounded description; the traceback keeps its tail, where the cause is."""
    frames = traceback.extract_tb(exc.__traceback__)
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    trace, truncated = _bounded(_redacted_text(formatted), _TRACEBACK_CHARS)
    return {
        "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": _redacted_text(exc)[:_MESSAGE_CHARS],
        "frames": [f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in frames[-_FRAMES:]],
        "traceback": trace,
        "traceback_truncated": truncated,
    }


def record_runtime_error(
    component: str,
    exc: BaseException,
    *,
    mission_id: str | None = None,
    context: dict[str, Any] | None = None,
    db: Database | None = None,
) -> dict[str, Any]:
    """Persist one failure. Never raises: recording must not replace the original error.

    Returns the redacted description with ``error_id`` (``None`` when no durable
    store is configured or the write itself failed).
    """
    described = describe_exception(exc)
    described["error_id"] = None
    database = db or _store_database()
    if database is None:
        return described
    try:
        safe_context = sanitize_context(dict(context or {}))
        fingerprint = hashlib.sha256(
            "\n".join(
                [component, mission_id or "", described["exception_type"], *described["frames"]]
            ).encode()
        ).hexdigest()
        now = datetime.now(UTC)
        with database.session() as session:
            row = session.scalars(
                select(ArcRuntimeError)
                .where(ArcRuntimeError.fingerprint == fingerprint)
                .order_by(ArcRuntimeError.created_at)
                .limit(1)
                .with_for_update()
            ).first()
            if row is None:
                row = ArcRuntimeError(
                    id="err_" + digest([fingerprint, now.isoformat()])[:24],
                    fingerprint=fingerprint,
                    component=component,
                    mission_id=mission_id,
                    exception_type=described["exception_type"],
                    first_seen_at=now,
                    occurrences=0,
                    recent_messages_json=[],
                )
                session.add(row)
            recent = [m for m in (row.recent_messages_json or []) if m != described["message"]]
            row.recent_messages_json = [*recent, described["message"]][-_RECENT_MESSAGES:]
            row.message = described["message"]
            row.frames_json = described["frames"]
            row.traceback = described["traceback"]
            row.context_json = safe_context
            row.occurrences = int(row.occurrences or 0) + 1
            row.last_seen_at = now
            session.flush()
            described["error_id"] = row.id
    except Exception:  # noqa: BLE001 - the journal must not mask the failure it records
        logger.exception("runtime error journal write failed component=%s", component)
    return described


def record_model_exchange(
    mission_id: str,
    *,
    provider: str,
    model: str,
    request_hash: str,
    context_record_id: str,
    content: str,
    reasoning_content: str,
    tool_calls: list[dict[str, Any]],
    usage: dict[str, Any],
    db: Database | None = None,
) -> str:
    """Append-only raw reply. Write failures raise: a dispatch without receipt is not done."""
    reply, reply_truncated = _bounded(_redacted_text(content or ""), _REPLY_CHARS)
    reasoning, reasoning_truncated = _bounded(
        _redacted_text(reasoning_content or ""), _REPLY_CHARS
    )
    record = {
        "mission_id": mission_id,
        "provider": provider,
        "model": model,
        "request_hash": request_hash,
        "context_record_id": context_record_id,
        "content": reply,
        "reasoning_content": reasoning,
        "tool_calls": sanitize_context(tool_calls),
        "usage": sanitize_context(usage),
        "truncated": {"content": reply_truncated, "reasoning_content": reasoning_truncated},
    }
    exchange_id = "mx_" + digest(record)[:24]
    database = db or _store_database()
    if database is None:
        return "ephemeral:" + exchange_id
    with database.session() as session:
        if session.get(ArcModelExchange, exchange_id) is None:
            session.add(
                ArcModelExchange(
                    id=exchange_id,
                    mission_id=mission_id,
                    provider=provider,
                    model=model,
                    request_hash=request_hash,
                    context_record_id=context_record_id,
                    content=reply,
                    reasoning_content=reasoning,
                    tool_calls_json=record["tool_calls"],
                    usage_json=record["usage"],
                    truncated_json=record["truncated"],
                )
            )
    return exchange_id
