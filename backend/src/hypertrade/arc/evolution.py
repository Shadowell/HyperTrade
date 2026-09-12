"""Hourly Paper diagnostics -> evidence-bound AVO work, with durable scheduling and memory."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
    PaperFeedbackPolicyV1,
)
from hypertrade.arc.controller import ARCController, ARCMissionProjection
from hypertrade.arc.evolution_models import EvolutionControl, EvolutionCycle
from hypertrade.arc.feedback import _feedback_child_active, collect_windows
from hypertrade.arc.observation import _snapshot_body
from hypertrade.arc.store import get_controller, research_lock, save_mission
from hypertrade.arc.universe import normalize_symbols
from hypertrade.bitpro.mcp import BitProToolAdapter
from hypertrade.db import ArcMission, Database


class EvolutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    strategy_ids: list[int] = Field(default_factory=list, max_length=50)
    threshold_pp: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    min_trades: int = Field(default=30, ge=1, le=10000)
    cooldown_hours: int = Field(default=24, ge=24, le=720)
    max_active_research: int = Field(default=2, ge=1, le=5)
    max_candidates: int = Field(default=3, ge=1, le=10)
    max_model_calls: int = Field(default=20, ge=3, le=50)
    max_backtests: int = Field(default=8, ge=3, le=30)
    paper_capital: Decimal = Field(default=Decimal("100"), gt=0, le=10000)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def baseline_config(source: dict[str, Any], capital: Decimal) -> dict[str, Any]:
    config = source.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("原策略配置格式不可复现")

    def check(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if any(
                    word in str(key).lower()
                    for word in ("secret", "password", "token", "api_key", "credential", "cookie")
                ):
                    raise ValueError("原策略配置含认证字段，不能送入研究上下文")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    operational = {
        "paper_instance_id",
        "paper_strategy_version",
        "paper_config_version",
        "paper_configured_at",
        "initial_capital",
        "initial_equity",
    }
    result = {k: v for k, v in config.items() if not k.startswith("_") and k not in operational}
    check(result)
    if len(json.dumps(result, allow_nan=False)) > 20000:
        raise ValueError("原策略配置超过可审计上下文范围")
    result.update(
        is_paper_trading=True,
        initial_capital=float(capital),
        _prefer_db_script=True,
        _db_script=True,
        strategy_source="db_script",
        script_content_source="db",
        ai_generated=True,
    )
    return result


def cycle_view(row: EvolutionCycle) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "payload": dict(row.payload_json),
    }


class EvolutionService:
    def __init__(self, db: Database, client: Any = None):
        self.db = db
        self.client = client

    def status(self) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(EvolutionControl, "global")
            cycles = session.scalars(
                select(EvolutionCycle).order_by(EvolutionCycle.created_at.desc()).limit(20)
            ).all()
            return {
                "config": EvolutionConfig.model_validate(row.config_json if row else {}).model_dump(
                    mode="json"
                ),
                "revision": row.revision if row else 0,
                "cycles": [cycle_view(c) for c in cycles],
            }

    def configure(self, config: EvolutionConfig, *, revision: int, actor: str) -> dict[str, Any]:
        if any(x <= 0 for x in config.strategy_ids):
            raise ValueError("策略ID必须为正整数")
        with research_lock("evolution-control") as owner:
            if owner is None:
                raise ValueError("配置正在更新，请刷新后重试")
            with self.db.session() as session:
                row = session.get(EvolutionControl, "global", with_for_update=True)
                if revision != (row.revision if row else 0):
                    raise ValueError("配置已变化，请刷新后重试")
                if row is None:
                    row = EvolutionControl(id="global", revision=0)
                    session.add(row)
                row.config_json = config.model_dump(mode="json")
                row.revision += 1
                row.updated_by = actor
        return self.status()

    def queue_preview(self) -> dict[str, Any]:
        state = self.status()
        with self.db.session() as session:
            row = EvolutionCycle(
                id="preview_" + uuid4().hex[:24],
                status="queued",
                payload_json={
                    "preview": True,
                    "revision": state["revision"],
                    "config": state["config"],
                },
            )
            session.add(row)
            session.flush()
            return cycle_view(row)

    def _save_cycle(self, cycle_id: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(EvolutionCycle, cycle_id, with_for_update=True)
            assert row is not None
            row.status, row.payload_json = status, payload
            session.flush()
            return cycle_view(row)

    def tick(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        with research_lock("evolution-scanner") as owner:
            if owner is None:
                return {"status": "busy"}
            state = self.status()
            config = EvolutionConfig.model_validate(state["config"])
            if config.enabled:
                bucket = int(now.timestamp()) // (config.interval_minutes * 60)
                cycle_id = f"evo_{state['revision']}_{bucket}"
                with self.db.session() as session:
                    if session.get(EvolutionCycle, cycle_id) is None:
                        session.add(
                            EvolutionCycle(
                                id=cycle_id,
                                status="queued",
                                payload_json={
                                    "preview": False,
                                    "revision": state["revision"],
                                    "config": state["config"],
                                },
                            )
                        )
            with self.db.session() as session:
                row = session.scalar(
                    select(EvolutionCycle)
                    .where(EvolutionCycle.status.in_(["queued", "scanning"]))
                    .order_by(EvolutionCycle.created_at)
                    .limit(1)
                )
                if row is None:
                    return {"status": "idle" if config.enabled else "disabled"}
                cycle_id, payload = row.id, dict(row.payload_json)
            mission_id = "arc_evo_" + digest(cycle_id)[:16]
            existing = get_controller(mission_id)
            if existing:
                payload["mission_id"] = mission_id
                return self._save_cycle(cycle_id, "research_created", payload)
            self._save_cycle(cycle_id, "scanning", payload)
            try:
                config = EvolutionConfig.model_validate(payload["config"])
                diagnostics, chosen = self._scan(config, now)
                payload["diagnostics"] = diagnostics
                owner()
                latest = self.status()
                if payload["preview"]:
                    return self._save_cycle(cycle_id, "preview_complete", payload)
                if not latest["config"]["enabled"] or latest["revision"] != payload["revision"]:
                    return self._save_cycle(cycle_id, "cancelled_by_config", payload)
                if chosen is None:
                    return self._save_cycle(cycle_id, "no_action", payload)
                context = chosen
                memory, active, blocked_source = self._memory(context, config, now)
                payload["memory_count"] = len(memory)
                if active >= config.max_active_research or blocked_source:
                    payload["skip_reason"] = "已有研究/待审核版本、同源观察版本或仍在冷却期"
                    return self._save_cycle(cycle_id, "deferred", payload)
                context["memory"] = memory
                context["cycle_id"] = cycle_id
                goal = ARCGoalV1(
                    objective="依据原模拟盘的真实7+7退化、历史成交样本及长期研究记忆，自主判断改进方向并提出候选；保留原策略，通过同窗比较和最终门槛后提交人工审核。",
                    symbols=[context["baseline"]["strategy_spec"]["symbol"]],
                    timeframes=[context["baseline"]["strategy_spec"]["timeframe"]],
                    research_mode="avo",
                    provider_name="codex",
                    paper_review_required=True,
                    paper_initial_equity=config.paper_capital,
                    evolution_context=context,
                    feedback=PaperFeedbackPolicyV1(enabled=True, threshold_pp=config.threshold_pp),
                    budget=ARCBudgetV1(
                        max_candidates=config.max_candidates,
                        max_model_calls=config.max_model_calls,
                        max_backtests=config.max_backtests,
                    ),
                    success_criteria=ARCSuccessCriteriaV1(
                        min_oos_net_return=Decimal("1E-8"),
                        min_oos_sharpe=Decimal(0),
                        max_drawdown=Decimal(".2"),
                        min_trades=30,
                        required_validation_policy="arc_windowed_v1",
                    ),
                )
                ctrl = ARCController(mission_id=mission_id, goal=goal)
                ctrl.projection.created_by = "paper-evolution-worker"
                owner()
                # Config and source identity are rechecked immediately before creating new work.
                current = self.status()
                if current["revision"] != payload["revision"] or not current["config"]["enabled"]:
                    return self._save_cycle(cycle_id, "cancelled_by_config", payload)
                fresh = _snapshot_body(
                    self._client().paper_snapshot(
                        strategy_id=context["source_strategy_id"],
                        instance_id=context["source_instance_id"],
                    )
                )
                if any(
                    fresh.get(k) != context["source_snapshot"].get(k)
                    for k in ["instance_id", "strategy_version", "config_version", "status"]
                ):
                    payload["skip_reason"] = "原模拟盘身份或版本在诊断期间发生变化"
                    return self._save_cycle(cycle_id, "source_changed", payload)
                source_now = (
                    self._client()
                    .strategy_get(strategy_id=context["source_strategy_id"])
                    .get("strategy", {})
                )
                if (
                    hashlib.sha256(str(source_now.get("script_content") or "").encode()).hexdigest()
                    != context["source_code_sha256"]
                ):
                    return self._save_cycle(cycle_id, "source_changed", payload)
                if (
                    baseline_config(source_now, config.paper_capital)
                    != context["baseline"]["strategy_spec"]["baseline_config"]
                ):
                    return self._save_cycle(cycle_id, "source_changed", payload)
                with self.db.session() as session:
                    control = session.get(EvolutionControl, "global", with_for_update=True)
                    if (
                        control is None
                        or control.revision != payload["revision"]
                        or not control.config_json.get("enabled")
                    ):
                        return self._save_cycle(cycle_id, "cancelled_by_config", payload)
                    # Serialize task creation against the product switch, not merely a prior read.
                    save_mission(ctrl)
                payload["mission_id"] = mission_id
                payload["source_strategy_id"] = context["source_strategy_id"]
                return self._save_cycle(cycle_id, "research_created", payload)
            except Exception as exc:
                payload["error"] = type(exc).__name__
                return self._save_cycle(cycle_id, "error", payload)

    def _client(self) -> Any:
        if self.client is None:
            self.client = BitProToolAdapter()
        return self.client

    def _scan(
        self, config: EvolutionConfig, now: datetime
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        client = self._client()
        inventory = client.paper_strategy_performance(limit=50)
        rows = inventory.get("strategies", [])
        diagnostics = [
            {
                "strategy_id": r.get("strategy_id"),
                "status": "unavailable",
                "reason": r.get("reason"),
            }
            for r in inventory.get("unavailable_strategies", [])
        ]
        total = inventory.get("performance_summary", {}).get("reported_total", len(rows))
        if total > 50:
            diagnostics.append(
                {
                    "status": "partial_coverage",
                    "reason": "本轮最多扫描50个运行策略，未扫描部分不作结论",
                }
            )
        chosen = None
        end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        for row in rows:
            sid = int(row["strategy_id"])
            if config.strategy_ids and sid not in config.strategy_ids:
                continue
            diagnostic: dict[str, Any] = {"strategy_id": sid, "name": row.get("strategy_name")}
            diagnostics.append(diagnostic)
            try:
                snapshot = _snapshot_body(client.paper_snapshot(strategy_id=sid))
                if (
                    row.get("mode") != "paper"
                    or snapshot.get("status") != "running"
                    or str(snapshot.get("strategy_id")) != str(sid)
                ):
                    raise ValueError("模拟盘身份或运行状态不满足诊断条件")
                if int(snapshot.get("trade_count") or 0) < config.min_trades:
                    raise ValueError("成交样本不足")
                feedback = collect_windows(
                    client,
                    str(snapshot["instance_id"]),
                    str(sid),
                    end,
                    PaperFeedbackPolicyV1(enabled=True, threshold_pp=config.threshold_pp),
                )
                diagnostic.update(
                    status="stable", window={k: v for k, v in feedback.items() if k != "receipts"}
                )
                if not feedback["triggered"]:
                    continue
                diagnostic["status"] = "opportunity"
                symbols = normalize_symbols(snapshot.get("strategy", {}).get("symbols", []))
                if len(symbols) != 1:
                    raise ValueError(
                        "组合策略已识别退化；当前同窗比较引擎仅支持单标的候选，不能冒充组合优化"
                    )
                source = client.strategy_get(strategy_id=sid).get("strategy", {})
                code = source.get("script_content")
                if not isinstance(code, str) or not code.strip():
                    raise ValueError("无法读取原策略源码，不能建立可复现的比较基线")
                orders = client.strategy_trades(strategy_id=sid, limit=200)
                start = datetime.fromisoformat(
                    snapshot["session"]["started_at"].replace("Z", "+00:00")
                )
                fills = []
                for trade in orders:
                    if str(trade.get("strategy_id")) != str(sid):
                        raise ValueError("成交记录策略身份不一致")
                    stamp = datetime.fromtimestamp(float(trade["timestamp"]) / 1000, UTC)
                    if start <= stamp <= now:
                        fills.append(
                            {
                                k: trade.get(k)
                                for k in [
                                    "id",
                                    "timestamp",
                                    "symbol",
                                    "side",
                                    "type",
                                    "price",
                                    "quantity",
                                    "fee",
                                    "pnl",
                                ]
                            }
                        )
                if not fills:
                    raise ValueError("当前模拟会话没有可读取的历史成交样本")
                timeframe = str(
                    (source.get("config") or {}).get("timeframe") or row.get("timeframe") or ""
                )
                if not timeframe:
                    raise ValueError("原策略周期未明确")
                baseline = ARCCandidateAttemptV1(
                    attempt_id="baseline_" + str(sid),
                    candidate_id="baseline_" + str(sid),
                    hypothesis="不可变的原策略比较基线",
                    strategy_code=code,
                    strategy_spec={
                        "symbol": symbols[0],
                        "timeframe": timeframe,
                        "baseline_config": baseline_config(source, config.paper_capital),
                    },
                )
                context = {
                    "source_strategy_id": sid,
                    "source_instance_id": snapshot["instance_id"],
                    "source_snapshot": {
                        k: snapshot.get(k)
                        for k in ["instance_id", "strategy_version", "config_version", "status"]
                    },
                    "source_code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "baseline": baseline.model_dump(mode="json"),
                    "paper_feedback": feedback,
                    "orders": {
                        "sample_limit": 200,
                        "sample_count": len(fills),
                        "coverage": "recent_session_sample",
                        "fills": fills,
                    },
                    "diagnosis": (
                        "收益下降或回撤扩大达到阈值；"
                        "用成交与研究记忆判断信号、退出和成本方面的改进方向。"
                    ),
                }
                diagnostic["order_sample_count"] = len(fills)
                diagnostic["source_code_sha256"] = context["source_code_sha256"]
                if chosen is None:
                    chosen = context
                else:
                    # A busy first source must not starve other eligible Paper instances.
                    _, _, first_blocked = self._memory(chosen, config, now)
                    _, _, current_blocked = self._memory(context, config, now)
                    if first_blocked and not current_blocked:
                        chosen = context
            except Exception as exc:
                diagnostic.update(status="unavailable", reason=str(exc)[:240])
        return diagnostics, chosen

    def _memory(
        self, context: dict[str, Any], config: EvolutionConfig, now: datetime
    ) -> tuple[list[dict[str, Any]], int, bool]:
        memory: list[dict[str, Any]] = []
        active, blocked = 0, False
        symbol = context["baseline"]["strategy_spec"]["symbol"]
        with self.db.session() as session:
            records = session.scalars(
                select(ArcMission).order_by(ArcMission.updated_at.desc())
            ).yield_per(20)
            for row in records:
                projection = ARCMissionProjection.model_validate(row.projection_json)
                goal = projection.goal
                if goal is None:
                    continue
                source = goal.evolution_context or {}
                parent = goal.feedback_parent or {}
                same = (source.get("source_instance_id") or parent.get("instance_id")) == context[
                    "source_instance_id"
                ]
                busy = projection.state not in {"completed", "rejected", "failed"}
                if projection.state == "needs_operator":
                    ctrl = get_controller(row.mission_id)
                    busy = bool(ctrl and _feedback_child_active(ctrl))
                if source and busy and projection.state != "paper_observing":
                    active += 1
                updated = (
                    row.created_at.replace(tzinfo=UTC)
                    if row.created_at.tzinfo is None
                    else row.created_at
                )
                if same and (busy or now - updated < timedelta(hours=config.cooldown_hours)):
                    blocked = True
                if symbol not in goal.symbols or len(memory) >= 20:
                    continue
                # Only development receipts become cross-task memory. Hidden final metrics
                # never enter another proposal context as if they were training data.
                for attempt in projection.attempts:
                    receipt = projection.avo.get("development", {}).get(attempt.attempt_id)
                    if receipt and len(memory) < 20:
                        memory.append(
                            {
                                "mission_id": row.mission_id,
                                "candidate_id": attempt.candidate_id,
                                "hypothesis": attempt.hypothesis,
                                "spec": attempt.strategy_spec,
                                "development": receipt,
                            }
                        )
        return memory, active, blocked
