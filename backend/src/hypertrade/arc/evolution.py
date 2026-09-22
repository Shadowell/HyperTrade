"""Hourly Paper diagnostics -> evidence-bound AVO work, with durable scheduling and memory."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from hypertrade.arc.attribution import attribution_report, collect_attribution
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
    PaperFeedbackPolicyV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController, ARCMissionProjection
from hypertrade.arc.evolution_continuation import ContinuationLedger, readiness
from hypertrade.arc.evolution_diagnostics import (
    blocked_data_diagnostic,
    snapshot_contract_unverified,
    upstream_read_unavailable,
)
from hypertrade.arc.evolution_models import EvolutionControl, EvolutionCycle
from hypertrade.arc.feedback import collect_windows
from hypertrade.arc.store import get_controller, research_lock
from hypertrade.arc.universe import declared_symbols, normalize_symbols
from hypertrade.db import ArcMission, Database
from hypertrade.memory.service import MemoryService
from hypertrade.targets.read_ports import SnapshotContractError, read_ports
from hypertrade.targets.registry import (
    MarketTargetUnavailable,
    active_market_target_id,
    adapter_for_target,
    get_market_target,
)


class EvolutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    proactive_enabled: bool = False
    # Which registered market target the loop runs against; resolves through
    # hypertrade.targets so swapping platforms is configuration, not code.
    target_id: str = Field(default="bitpro", pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    max_research_per_day: int = Field(default=4, ge=1, le=100)
    max_research_total: int | None = Field(default=None, ge=1)
    paper_review_mode: Literal["human", "agent"] = "human"
    paper_criteria: ARCSuccessCriteriaV1 = Field(
        default_factory=lambda: ARCSuccessCriteriaV1(
            min_oos_net_return=Decimal("1E-8"),
            min_oos_sharpe=Decimal(0),
            max_drawdown=Decimal(".2"),
            min_trades=30,
            required_validation_policy="arc_windowed_v1",
        )
    )
    interval_minutes: int = Field(default=60, ge=15, le=1440)
    strategy_ids: list[int | str] = Field(default_factory=list, max_length=50)

    @field_validator("strategy_ids", mode="before")
    @classmethod
    def reject_boolean_strategy_ids(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            if any(isinstance(item, bool) for item in value):
                raise ValueError("strategy_ids must not contain booleans")
            if any(type(item) not in (int, str) for item in value):
                raise ValueError("strategy_ids must contain integers or strings")
        return value

    threshold_pp: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    # benchmark_relative compares each strategy's 7+7 move against its own
    # symbol's buy-and-hold over the same halves; absolute keeps the legacy
    # raw comparison. Benchmark failures fall back to absolute and are
    # annotated in the window payload.
    degradation_basis: Literal["benchmark_relative", "absolute"] = "benchmark_relative"
    # Offline meta-tuning: advisory receipts by default (meta_tuning_enabled),
    # bounded auto-apply of the threshold step only when explicitly authorized.
    meta_tuning_enabled: bool = True
    meta_tuning_auto_apply: bool = False
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


def strategy_symbols(snapshot: dict[str, Any]) -> list[str]:
    """All normalized symbols of a running strategy (empty when unreadable)."""
    try:
        return normalize_symbols(snapshot.get("strategy", {}).get("symbols", []))
    except (ValueError, TypeError):
        return []


def target_symbols(snapshot: dict[str, Any], *, bitpro: bool) -> list[str]:
    if bitpro:
        return strategy_symbols(snapshot)
    values = (snapshot.get("strategy") or {}).get("symbols") or []
    if not isinstance(values, (list, tuple)):
        raise ValueError("目标标的证据格式无效")
    symbols = [str(value).strip() for value in values]
    if not symbols or any(not value or len(value) > 128 for value in symbols):
        raise ValueError("目标标的证据缺失")
    return list(dict.fromkeys(symbols))


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
        self._client_target_id: str | None = None

    def status(self) -> dict[str, Any]:
        from hypertrade.arc.research_budget import budget_status

        with self.db.session() as session:
            row = session.get(EvolutionControl, "global")
            cycles = session.scalars(
                select(EvolutionCycle)
                .where(EvolutionCycle.status.not_in(["budget_admitted", "budget_denied"]))
                .order_by(EvolutionCycle.created_at.desc())
                .limit(20)
            ).all()
            return {
                "config": EvolutionConfig.model_validate(row.config_json if row else {}).model_dump(
                    mode="json"
                ),
                "budget": budget_status(
                    self.db,
                    EvolutionConfig.model_validate(row.config_json if row else {}),
                    datetime.now(UTC),
                ),
                "revision": row.revision if row else 0,
                "cycles": [cycle_view(c) for c in cycles],
                "continuations": ContinuationLedger(self.db).view(),
            }

    def configure(self, config: EvolutionConfig, *, revision: int, actor: str) -> dict[str, Any]:
        try:
            profile = get_market_target(config.target_id).profile
        except MarketTargetUnavailable as exc:
            raise ValueError(str(exc)) from exc
        if profile.strategy_id_format == "integer":
            normalized_ids: list[int | str] = []
            for value in config.strategy_ids:
                if type(value) is int and value > 0:
                    normalized_ids.append(value)
                elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
                    normalized_ids.append(int(value))
                else:
                    raise ValueError("策略ID必须为正整数")
            config.strategy_ids = normalized_ids
        elif any(
            not isinstance(x, str) or not x.strip() or len(x) > 128 for x in config.strategy_ids
        ):
            raise ValueError("目标策略ID必须为非空字符串")
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
        clock_frozen = now is not None
        now = now or datetime.now(UTC)
        with research_lock("evolution-scanner") as owner:
            if owner is None:
                return {"status": "busy"}
            ContinuationLedger(self.db).refresh(now)
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
                with self.db.session() as session:
                    receipt = session.get(EvolutionCycle, "budget_" + mission_id)
                    if receipt is not None:
                        payload["budget"] = dict(receipt.payload_json)
                        payload["trigger_source"] = receipt.payload_json.get("trigger_source")
                payload["mission_id"] = mission_id
                return self._save_cycle(cycle_id, "research_created", payload)
            self._save_cycle(cycle_id, "scanning", payload)
            try:
                config = EvolutionConfig.model_validate(payload["config"])
                diagnostics, chosen = self._scan(
                    config,
                    now,
                    on_progress=lambda rows: self._save_cycle(
                        cycle_id, "scanning", {**payload, "diagnostics": list(rows)}
                    ),
                )
                payload["diagnostics"] = diagnostics
                owner()
                latest = self.status()
                if payload["preview"]:
                    return self._save_cycle(cycle_id, "preview_complete", payload)
                ContinuationLedger(self.db).record_check(cycle_id, diagnostics, latest["budget"])
                if not latest["config"]["enabled"] or latest["revision"] != payload["revision"]:
                    return self._save_cycle(cycle_id, "cancelled_by_config", payload)
                if chosen is None:
                    return self._save_cycle(cycle_id, "no_action", payload)
                context = chosen
                if config.target_id != "bitpro":
                    payload["source_strategy_id"] = context["source_strategy_id"]
                    payload["source_instance_id"] = context["source_instance_id"]
                    payload["target_id"] = config.target_id
                    payload["skip_reason"] = "target_paper_write_port_not_migrated"
                    return self._save_cycle(cycle_id, "deferred_target_write_port", payload)
                memory = self._memory(context, now)
                payload["memory_count"] = len(memory)
                payload["memory_manifest"] = context["memory_manifest"]
                context["memory"] = memory
                context["cycle_id"] = cycle_id
                goal = ARCGoalV1(
                    objective=(
                        "依据有来源的原Paper观察、历史成交样本和开发实验提出可证伪优化方向；"
                        "触发来源为" + context["trigger_source"] + "，稳定表现不得声称退化；"
                        "保留原策略，通过同窗比较和最终门槛后按配置评审独立Paper。"
                    ),
                    symbols=declared_symbols(context["baseline"]["strategy_spec"]),
                    timeframes=[context["baseline"]["strategy_spec"]["timeframe"]],
                    research_mode="avo",
                    provider_name="codex",
                    paper_review_required=True,
                    paper_review_mode=config.paper_review_mode,
                    paper_initial_equity=config.paper_capital,
                    evolution_context=context,
                    research_windows=ResearchWindowsV1.model_validate(context["research_windows"]),
                    feedback=PaperFeedbackPolicyV1(enabled=True, threshold_pp=config.threshold_pp),
                    budget=ARCBudgetV1(
                        max_candidates=config.max_candidates,
                        max_model_calls=config.max_model_calls,
                        max_backtests=config.max_backtests,
                    ),
                    success_criteria=config.paper_criteria.model_copy(deep=True),
                )
                ctrl = ARCController(mission_id=mission_id, goal=goal)
                ctrl.projection.created_by = "paper-evolution-worker"
                owner()
                # Config and source identity are rechecked immediately before creating new work.
                current = self.status()
                if current["revision"] != payload["revision"] or not current["config"]["enabled"]:
                    return self._save_cycle(cycle_id, "cancelled_by_config", payload)
                fresh_session = read_ports(self._client(config)).get_session_snapshot(
                    strategy_id=str(context["source_strategy_id"]),
                    instance_id=context["source_instance_id"],
                )
                fresh = {
                    "instance_id": fresh_session.instance_id,
                    "strategy_version": fresh_session.strategy_version,
                    "config_version": fresh_session.config_version,
                    "status": fresh_session.status,
                }
                if any(
                    fresh.get(k) != context["source_snapshot"].get(k)
                    for k in ["instance_id", "strategy_version", "config_version", "status"]
                ):
                    payload["skip_reason"] = "原模拟盘身份或版本在诊断期间发生变化"
                    return self._save_cycle(cycle_id, "source_changed", payload)
                source_now = read_ports(self._client(config)).get_strategy_source(
                    str(context["source_strategy_id"])
                )
                if source_now.code_sha256 != context["source_code_sha256"]:
                    return self._save_cycle(cycle_id, "source_changed", payload)
                if (
                    baseline_config({"config": source_now.config}, config.paper_capital)
                    != context["baseline"]["strategy_spec"]["baseline_config"]
                ):
                    return self._save_cycle(cycle_id, "source_changed", payload)
                from hypertrade.arc.research_budget import admit

                payload["budget"] = admit(
                    ctrl,
                    now=now if clock_frozen else datetime.now(UTC),
                    revision=payload["revision"],
                    db=self.db,
                )
                payload["trigger_source"] = context["trigger_source"]
                if not payload["budget"]["accepted"]:
                    return self._save_cycle(cycle_id, "deferred", payload)
                payload["mission_id"] = mission_id
                payload["source_strategy_id"] = context["source_strategy_id"]
                return self._save_cycle(cycle_id, "research_created", payload)
            except Exception as exc:
                payload["error"] = type(exc).__name__
                return self._save_cycle(cycle_id, "error", payload)

    def _client(self, config: EvolutionConfig | None = None) -> Any:
        target_id = config.target_id if config is not None else active_market_target_id()
        if self.client is None or (
            self._client_target_id is not None and self._client_target_id != target_id
        ):
            self.client = adapter_for_target(target_id)
            self._client_target_id = target_id
        return self.client

    def _scan(
        self,
        config: EvolutionConfig,
        now: datetime,
        on_progress: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        client = self._client(config)
        profile = get_market_target(config.target_id).profile
        required = ("running_inventory", "session_snapshot", "return_series", "session_trades")
        missing = [name for name in required if not getattr(profile.capabilities, name)]
        if missing:
            return (
                [
                    {
                        "status": "unavailable",
                        "reason": "target_read_capabilities_missing:" + ",".join(missing),
                    }
                ],
                None,
            )
        ports = read_ports(client)
        rows = ports.list_running_strategies(50)
        total, unavailable = ports.inventory_coverage()
        diagnostics = []
        invalid_inventory_rows = 0
        for row in unavailable:
            try:
                sid = (
                    int(row.strategy_id)
                    if profile.strategy_id_format == "integer"
                    else row.strategy_id
                )
            except (TypeError, ValueError):
                invalid_inventory_rows += 1
                continue
            if (isinstance(sid, int) and sid <= 0) or (isinstance(sid, str) and not sid.strip()):
                invalid_inventory_rows += 1
                continue
            if config.strategy_ids and sid not in config.strategy_ids:
                continue
            diagnostics.append(
                {
                    "target_id": config.target_id,
                    "strategy_id": sid,
                    "status": "unavailable",
                    **upstream_read_unavailable(now),
                }
            )
        if invalid_inventory_rows:
            diagnostics.append(
                {
                    "target_id": config.target_id,
                    "status": "partial_coverage",
                    "reason": "上游运行策略清单存在无效身份的行，本轮无法归属策略；请核对只读清单",
                    "unattributed_count": invalid_inventory_rows,
                }
            )
        if total > 50:
            diagnostics.append(
                {
                    "status": "partial_coverage",
                    "reason": "本轮最多扫描50个运行策略，未扫描部分不作结论",
                }
            )
        chosen = None
        from hypertrade.arc.research_budget import budget_status, source_key

        budget: dict[str, Any] | None = None

        def rank(context: dict[str, Any]) -> tuple[Any, ...]:
            nonlocal budget
            if budget is None:
                budget = budget_status(self.db, config, now)
            source = budget["sources"].get(
                source_key(
                    context["target_id"],
                    context["source_strategy_id"],
                    context["source_instance_id"],
                ),
                {},
            )
            until = datetime.fromisoformat(
                source.get("cooldown_at", "1970-01-01T00:00:00+00:00")
            ) + timedelta(hours=config.cooldown_hours)
            blocked = source.get("busy", False) or now < until
            preferred = "degradation"
            return (
                blocked,
                context["trigger_source"] != preferred,
                source.get("last_admitted_at", ""),
                context["source_strategy_id"],
            )

        end = (
            now
            if profile.calendar.mode == "sessions"
            else now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        )
        for row in sorted(
            rows,
            key=lambda item: (
                int(item.strategy_id)
                if profile.strategy_id_format == "integer"
                else item.strategy_id
            ),
        ):
            sid = (
                int(row.strategy_id) if profile.strategy_id_format == "integer" else row.strategy_id
            )
            if config.strategy_ids and sid not in config.strategy_ids:
                continue
            diagnostic: dict[str, Any] = {
                "target_id": config.target_id,
                "strategy_id": sid,
                "name": row.name,
                "attribution_report": attribution_report({"strategy_id": sid}, now),
            }
            diagnostics.append(diagnostic)
            snapshot: dict[str, Any] = {}
            snapshot_read = False
            try:
                session = ports.get_session_snapshot(strategy_id=str(sid))
                snapshot_read = True
                snapshot = {
                    **(session.source or {}),
                    "strategy_id": session.strategy_id,
                    "instance_id": session.instance_id,
                    "strategy_version": session.strategy_version,
                    "config_version": session.config_version,
                    "status": session.status,
                    "trade_count": session.trade_count,
                    "strategy": {
                        **((session.source or {}).get("strategy") or {}),
                        "symbols": list(session.symbols),
                    },
                    "session": {
                        "started_at": session.session_started_at.isoformat()
                        if session.session_started_at
                        else None
                    },
                }
                if (
                    row.mode != "paper"
                    or snapshot.get("status") != "running"
                    or str(snapshot.get("strategy_id")) != str(sid)
                ):
                    raise ValueError("模拟盘身份或运行状态不满足诊断条件")
                if profile.transport == "bitpro_mcp_v1":
                    diagnostic["attribution_report"] = collect_attribution(client, snapshot, now)
                if int(snapshot.get("trade_count") or 0) < config.min_trades:
                    raise ValueError("成交样本不足")
                benchmark_symbols = (
                    target_symbols(snapshot, bitpro=profile.transport == "bitpro_mcp_v1") or None
                )
                feedback = collect_windows(
                    ports,
                    str(snapshot["instance_id"]),
                    str(sid),
                    end,
                    PaperFeedbackPolicyV1(
                        enabled=True,
                        threshold_pp=config.threshold_pp,
                        benchmark_relative=config.degradation_basis == "benchmark_relative",
                    ),
                    benchmark_symbols=benchmark_symbols,
                    timeframe=row.timeframe or None,
                    calendar=profile.calendar,
                )
                diagnostic["window_receipt_hash"] = digest(
                    {
                        "baseline": feedback.get("baseline_receipt"),
                        "calendar_source_hash": (feedback.get("calendar") or {}).get("source_hash"),
                        "receipts": feedback.get("receipts", []),
                    }
                    if profile.calendar.mode == "sessions"
                    else feedback.get("receipts", [])
                )
                diagnostic.update(
                    status="stable",
                    window=(
                        feedback
                        if profile.calendar.mode == "sessions"
                        else {k: v for k, v in feedback.items() if k != "receipts"}
                    ),
                )
                if not feedback["triggered"] and not config.proactive_enabled:
                    continue
                trigger = "degradation" if feedback["triggered"] else "proactive"
                diagnostic.update(status="opportunity", trigger_source=trigger)
                symbols = target_symbols(snapshot, bitpro=profile.transport == "bitpro_mcp_v1")
                if not symbols:
                    raise ValueError("策略标的为空，无法建立同窗比较基线")
                source_record = ports.get_strategy_source(str(sid))
                source = {"config": source_record.config}
                code = source_record.code
                if not isinstance(code, str) or not code.strip():
                    raise ValueError("无法读取原策略源码，不能建立可复现的比较基线")
                orders = ports.list_fills(str(sid), limit=200)
                start = datetime.fromisoformat(
                    snapshot["session"]["started_at"].replace("Z", "+00:00")
                )
                fills = []
                for trade in orders:
                    if trade.strategy_id != str(sid):
                        raise ValueError("成交记录策略身份不一致")
                    stamp = datetime.fromtimestamp(trade.ts_ms / 1000, UTC)
                    if start <= stamp <= now:
                        fills.append(
                            {
                                "id": trade.fill_id,
                                "timestamp": trade.ts_ms,
                                "symbol": trade.symbol,
                                "side": trade.side,
                                "type": trade.order_type,
                                "price": trade.price,
                                "quantity": trade.qty,
                                "fee": trade.fee,
                                "pnl": trade.pnl,
                            }
                        )
                if not fills:
                    raise ValueError("当前模拟会话没有可读取的历史成交样本")
                timeframe = str(source_record.timeframe or row.timeframe or "")
                if not timeframe:
                    raise ValueError("原策略周期未明确")
                baseline = ARCCandidateAttemptV1(
                    attempt_id="baseline_" + str(sid),
                    candidate_id="baseline_" + str(sid),
                    hypothesis="不可变的原策略比较基线",
                    strategy_code=code,
                    strategy_spec={
                        **({"symbols": symbols} if len(symbols) > 1 else {"symbol": symbols[0]}),
                        "timeframe": timeframe,
                        "baseline_config": baseline_config(source, config.paper_capital),
                    },
                )
                context = {
                    "target_id": config.target_id,
                    "trigger_source": trigger,
                    "source_strategy_id": sid,
                    "source_instance_id": snapshot["instance_id"],
                    "source_snapshot": {
                        k: snapshot.get(k)
                        for k in ["instance_id", "strategy_version", "config_version", "status"]
                    },
                    "source_code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "baseline": baseline.model_dump(mode="json"),
                    "paper_feedback": feedback,
                    "attribution_report": diagnostic["attribution_report"],
                    "orders": {
                        "sample_limit": 200,
                        "sample_count": len(fills),
                        "coverage": "recent_session_sample",
                        "fills": fills,
                    },
                    "diagnosis": (
                        (
                            "收益下降或回撤扩大达到阈值；"
                            if feedback["triggered"]
                            else "完整观察未达到退化阈值，主动探索可证伪方向；"
                        )
                        + "用成交与研究记忆判断信号、退出和成本方面的改进方向。"
                    ),
                }
                diagnostic["order_sample_count"] = len(fills)
                diagnostic["source_code_sha256"] = context["source_code_sha256"]
                if chosen is None or rank(context) < rank(chosen):
                    chosen = context
            except Exception as exc:
                diagnostic.update(status="unavailable", reason=str(exc)[:240])
                # Explain current sampling separately; never fill the missing historical window.
                identified = (
                    snapshot
                    if str(snapshot.get("strategy_id")) == str(sid)
                    and snapshot.get("status") == "running"
                    else {}
                )
                if isinstance(exc, SnapshotContractError):
                    diagnostic.update(snapshot_contract_unverified(now))
                elif not snapshot_read:
                    diagnostic.update(upstream_read_unavailable(now))
                elif profile.transport == "bitpro_mcp_v1":
                    diagnostic.update(
                        blocked_data_diagnostic(client, identified, now, str(exc)[:240])
                    )
            finally:
                bound_snapshot = snapshot if str(snapshot.get("strategy_id")) == str(sid) else {}
                diagnostic["continuation"] = readiness(
                    bound_snapshot,
                    diagnostic,
                    config,
                    now,
                    profile=profile,
                    snapshot_read=snapshot_read,
                )
                if on_progress is not None:
                    on_progress(diagnostics)
        for diagnostic in diagnostics:
            if "continuation" not in diagnostic and diagnostic.get("strategy_id"):
                diagnostic["continuation"] = readiness(
                    {}, diagnostic, config, now, profile=profile, snapshot_read=False
                )
        return diagnostics, chosen

    def _memory(self, context: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        memory: list[dict[str, Any]] = []
        scope_symbols = set(declared_symbols(context["baseline"]["strategy_spec"]))
        with self.db.session() as session:
            records = session.scalars(
                select(ArcMission).order_by(ArcMission.updated_at.desc())
            ).yield_per(20)
            for row in records:
                projection = ARCMissionProjection.model_validate(row.projection_json)
                goal = projection.goal
                if goal is None:
                    continue
                if not scope_symbols.intersection(goal.symbols) or len(memory) >= 200:
                    continue
                # Only development receipts become cross-task memory. Hidden final metrics
                # never enter another proposal context as if they were training data.
                for attempt in projection.attempts:
                    receipt = projection.avo.get("development", {}).get(attempt.attempt_id)
                    if receipt and len(memory) < 200:
                        memory.append(
                            {
                                "mission_id": row.mission_id,
                                "candidate_id": attempt.candidate_id,
                                "hypothesis": attempt.hypothesis,
                                "spec": attempt.strategy_spec,
                                "code_sha256": hashlib.sha256(
                                    attempt.strategy_code.encode()
                                ).hexdigest(),
                                "capital": str(goal.paper_initial_equity),
                                "development": receipt,
                            }
                        )
        windows = ResearchWindowsV1(as_of=now.astimezone(UTC).date() - timedelta(days=1))
        memory, manifest = MemoryService(self.db).project_research(
            memory,
            symbol=sorted(scope_symbols)[0] if scope_symbols else "",
            symbols=scope_symbols or None,
            timeframe=context["baseline"]["strategy_spec"]["timeframe"],
            windows=windows,
        )
        context["memory_manifest"] = manifest
        context["research_windows"] = windows.model_dump(mode="json")
        return memory
