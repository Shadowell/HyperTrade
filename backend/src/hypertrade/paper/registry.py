"""Dynamic Strategy Registry and Factory for Autonomous Strategy Lifecycles.

Maintains persistent registry records for running and evolved strategies,
instantiating ExecutionStrategy objects on the fly and enabling dynamic
injection into MultiStrategySignalEngine.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypertrade.paper.stage_gate import StrategyStage
from hypertrade.paper.strategies import (
    ExecutionStrategy,
    FallbackUtc0Strategy,
    MacdTrendExecutionStrategy,
    MomentumBreakoutExecutionStrategy,
    RsiReversalExecutionStrategy,
)


@dataclass
class StrategyRecord:
    """Persistent entity representing an execution strategy variant."""

    strategy_id: str
    strategy_type: str  # "rsi_reversal", "momentum_breakout", "macd_trend", "utc0_momentum"
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    stage: StrategyStage = StrategyStage.PAPER_OBSERVING
    generation: int = 1
    parent_strategy_id: str | None = None
    reflexion_constraints: list[str] = field(default_factory=list)
    performance_metrics: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now_iso = datetime.now(UTC).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = now_iso

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage"] = (
            self.stage.value if isinstance(self.stage, StrategyStage) else str(self.stage)
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyRecord:
        raw_stage = data.get("stage", StrategyStage.PAPER_OBSERVING.value)
        try:
            stage_enum = StrategyStage(raw_stage)
        except ValueError:
            stage_enum = StrategyStage.PAPER_OBSERVING

        return cls(
            strategy_id=data["strategy_id"],
            strategy_type=data.get("strategy_type", "rsi_reversal"),
            name=data.get("name", data["strategy_id"]),
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            stage=stage_enum,
            generation=int(data.get("generation", 1)),
            parent_strategy_id=data.get("parent_strategy_id"),
            reflexion_constraints=data.get("reflexion_constraints", []),
            performance_metrics=data.get("performance_metrics", {}),
            is_active=bool(data.get("is_active", True)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class StrategyFactory:
    """Instantiates concrete ExecutionStrategy instances from StrategyRecords."""

    @staticmethod
    def build(record: StrategyRecord) -> ExecutionStrategy:
        st = record.strategy_type.lower()
        p = record.parameters

        if st == "rsi_reversal":
            return RsiReversalExecutionStrategy(
                strategy_key=record.strategy_id,
                rsi_period=int(p.get("rsi_period", 14)),
                oversold_threshold=float(p.get("oversold_threshold", 30.0)),
                overbought_threshold=float(p.get("overbought_threshold", 70.0)),
                stop_loss_pct=Decimal(str(p.get("stop_loss_pct", "0.04"))),
                take_profit_pct=Decimal(str(p.get("take_profit_pct", "0.08"))),
                enabled=record.is_active,
            )
        elif st == "momentum_breakout":
            return MomentumBreakoutExecutionStrategy(
                strategy_key=record.strategy_id,
                breakout_threshold_pct=Decimal(str(p.get("breakout_threshold_pct", "2.0"))),
                stop_loss_pct=Decimal(str(p.get("stop_loss_pct", "0.03"))),
                take_profit_pct=Decimal(str(p.get("take_profit_pct", "0.06"))),
                enabled=record.is_active,
            )
        elif st == "macd_trend":
            return MacdTrendExecutionStrategy(
                strategy_key=record.strategy_id,
                fast_period=int(p.get("fast_period", 12)),
                slow_period=int(p.get("slow_period", 26)),
                signal_period=int(p.get("signal_period", 9)),
                stop_loss_pct=Decimal(str(p.get("stop_loss_pct", "0.035"))),
                take_profit_pct=Decimal(str(p.get("take_profit_pct", "0.075"))),
                enabled=record.is_active,
            )
        elif st in ("utc0_momentum", "utc0_momentum_legacy"):
            return FallbackUtc0Strategy(
                threshold_pct=Decimal(str(p.get("threshold_pct", "3.0"))),
                enabled=record.is_active,
            )
        else:
            # Fallback to UTC-0 baseline if unrecognized type
            return FallbackUtc0Strategy(
                threshold_pct=Decimal("3.0"),
                enabled=record.is_active,
            )


class StrategyRegistry:
    """Thread-safe persistent strategy registry."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._lock = threading.Lock()
        if storage_path is None:
            self._storage_path = Path("data/paper_strategy_registry.json")
        else:
            self._storage_path = Path(storage_path)

        self._records: dict[str, StrategyRecord] = {}
        self._load_or_initialize()

    def _load_or_initialize(self) -> None:
        with self._lock:
            if self._storage_path.exists():
                try:
                    raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        for item in raw:
                            rec = StrategyRecord.from_dict(item)
                            self._records[rec.strategy_id] = rec
                        if self._records:
                            return
                except Exception:
                    pass

            # Pre-populate default production baselines
            self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        defaults = [
            StrategyRecord(
                strategy_id="rsi_reversal",
                strategy_type="rsi_reversal",
                name="RSI Mean Reversion Baseline",
                description=(
                    "Counter-trend execution on overbought/oversold boundaries with EMA filter"
                ),
                parameters={
                    "rsi_period": 14,
                    "oversold_threshold": 30.0,
                    "overbought_threshold": 70.0,
                    "stop_loss_pct": "0.04",
                    "take_profit_pct": "0.08",
                },
                stage=StrategyStage.PAPER_OBSERVING,
                generation=1,
            ),
            StrategyRecord(
                strategy_id="momentum_breakout_v1",
                strategy_type="momentum_breakout",
                name="Momentum Breakout Baseline",
                description="Trend continuation breakout execution across 24h momentum shifts",
                parameters={
                    "breakout_threshold_pct": "2.0",
                    "stop_loss_pct": "0.03",
                    "take_profit_pct": "0.06",
                },
                stage=StrategyStage.PAPER_OBSERVING,
                generation=1,
            ),
            StrategyRecord(
                strategy_id="macd_trend",
                strategy_type="macd_trend",
                name="MACD Trend Expansion",
                description="Dual-EMA divergence tracking on fast/slow momentum expansion",
                parameters={
                    "fast_period": 12,
                    "slow_period": 26,
                    "signal_period": 9,
                    "stop_loss_pct": "0.035",
                    "take_profit_pct": "0.075",
                },
                stage=StrategyStage.PAPER_OBSERVING,
                generation=1,
            ),
            StrategyRecord(
                strategy_id="utc0_momentum_legacy",
                strategy_type="utc0_momentum",
                name="UTC-0 Momentum Baseline",
                description="Legacy benchmark momentum threshold rule",
                parameters={
                    "threshold_pct": "3.0",
                },
                stage=StrategyStage.PAPER_OBSERVING,
                generation=1,
            ),
        ]
        for rec in defaults:
            self._records[rec.strategy_id] = rec
        self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            serialized = [rec.to_dict() for rec in self._records.values()]
            self._storage_path.write_text(
                json.dumps(serialized, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            # File system errors must not crash execution in memory
            pass

    def register(self, record: StrategyRecord) -> StrategyRecord:
        """Register or update a strategy record and persist."""
        with self._lock:
            record.updated_at = datetime.now(UTC).isoformat()
            self._records[record.strategy_id] = record
            self._persist_unlocked()
            return record

    def get(self, strategy_id: str) -> StrategyRecord | None:
        with self._lock:
            return self._records.get(strategy_id)

    def list_all(self) -> list[StrategyRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: (r.generation, r.strategy_id))

    def list_active(self) -> list[StrategyRecord]:
        with self._lock:
            return [
                r for r in self._records.values()
                if r.is_active and r.stage != StrategyStage.DEGRADED
            ]

    def update_stage(
        self, strategy_id: str, stage: StrategyStage, reason: str = ""
    ) -> StrategyRecord | None:
        with self._lock:
            record = self._records.get(strategy_id)
            if not record:
                return None
            record.stage = stage
            record.updated_at = datetime.now(UTC).isoformat()
            if reason:
                record.performance_metrics["last_stage_reason"] = reason
            self._persist_unlocked()
            return record

    def update_metrics(self, strategy_id: str, metrics: dict[str, Any]) -> StrategyRecord | None:
        with self._lock:
            record = self._records.get(strategy_id)
            if not record:
                return None
            record.performance_metrics.update(metrics)
            record.updated_at = datetime.now(UTC).isoformat()
            self._persist_unlocked()
            return record

    def deactivate(self, strategy_id: str) -> StrategyRecord | None:
        with self._lock:
            record = self._records.get(strategy_id)
            if not record:
                return None
            record.is_active = False
            record.updated_at = datetime.now(UTC).isoformat()
            self._persist_unlocked()
            return record

    def build_active_strategies(self) -> list[ExecutionStrategy]:
        """Instantiate all active and non-degraded execution strategies."""
        with self._lock:
            active_records = [
                r for r in self._records.values()
                if r.is_active and r.stage != StrategyStage.DEGRADED
            ]
        return [StrategyFactory.build(rec) for rec in active_records]


_REGISTRY_LOCK = threading.Lock()
_GLOBAL_REGISTRY: StrategyRegistry | None = None


def get_strategy_registry() -> StrategyRegistry:
    """Global singleton accessor for StrategyRegistry."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        with _REGISTRY_LOCK:
            if _GLOBAL_REGISTRY is None:
                _GLOBAL_REGISTRY = StrategyRegistry()
    return _GLOBAL_REGISTRY
