"""Persistent product scheduling and diagnostic receipts; ARC owns research execution."""

from typing import Any

from sqlalchemy import JSON, Integer, String
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
