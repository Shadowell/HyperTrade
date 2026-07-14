"""Durable Agent sessions shared by CLI, Web, API, and background tasks."""

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from hypertrade.db import AgentSession, Database


class AgentSessionCreate(BaseModel):
    title: str = Field(default="Agent Session", min_length=1, max_length=200)
    surface: Literal["cli", "tui", "web", "api", "background"] = "api"
    provider_config: dict[str, Any] = Field(default_factory=dict)
    context_policy: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(default="operator", min_length=1, max_length=128)


class AgentSessionService:
    """Own session persistence; model context remains bounded by context_policy."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, payload: AgentSessionCreate) -> AgentSession:
        with self.db.session() as session:
            row = AgentSession(
                title=payload.title.strip(),
                surface=payload.surface,
                provider_config_json=_safe_provider_config(payload.provider_config),
                context_policy_json=dict(payload.context_policy),
                created_by=payload.created_by.strip(),
            )
            session.add(row)
            session.flush()
            session.expunge(row)
            return row

    def get(self, session_id: str) -> AgentSession:
        with self.db.session() as session:
            row = session.get(AgentSession, session_id)
            if row is None:
                raise KeyError(session_id)
            session.expunge(row)
            return row

    def list(self, *, limit: int = 50) -> list[AgentSession]:
        bounded = max(1, min(limit, 200))
        with self.db.session() as session:
            rows = session.scalars(
                select(AgentSession).order_by(desc(AgentSession.created_at)).limit(bounded)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)


def session_to_dict(row: AgentSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "surface": row.surface,
        "provider_config": dict(row.provider_config_json or {}),
        "context_policy": dict(row.context_policy_json or {}),
        "summary_markdown": row.summary_markdown,
        "last_event_sequence": row.last_event_sequence,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _safe_provider_config(value: dict[str, Any]) -> dict[str, Any]:
    forbidden = {"api_key", "access_token", "authorization", "password", "secret"}
    return {key: item for key, item in value.items() if key.lower() not in forbidden}
