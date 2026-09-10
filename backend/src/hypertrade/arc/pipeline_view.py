"""Live pipeline progress for an external console. A rendering, never a second store.

An operator watching a mission wants one question answered continuously: which stage
is it in, and is it moving. That is derived here from the same projection the evidence
view reads, so the console cannot drift from what the mission actually recorded.

Event payloads are not forwarded. They carry whole candidates and approval packages,
including ``strategy_code``, which stays behind candidate drill-down.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from hypertrade.arc.controller import ARCEventV1, ARCMissionProjection
from hypertrade.research.codegen import FAMILIES

STAGES: tuple[tuple[str, str], ...] = (
    ("goal", "目标编译"),
    ("explore", "候选探索"),
    ("red_team", "红队对抗"),
    ("validate", "BitPro 验证"),
    ("paper", "模拟盘观察"),
    ("approval", "实盘审批"),
    ("live", "实盘灰度"),
)

_BLOCKED_STATES = {"needs_operator", "failed"}

_EVENT_LABELS = {
    "paper_feedback_checked": "模拟盘 7+7 反馈",
    "avo_baseline_requested": "开始原策略同窗回测",
    "avo_baseline_result": "原策略同窗证据已入账",
    "avo_initialized": "AVO 研究已准备",
    "avo_model_requested": "请求模型规划",
    "avo_model_replied": "模型已选择研究操作",
    "avo_tool_requested": "执行研究操作",
    "avo_tool_finished": "研究操作完成",
    "avo_development_requested": "开始开发回测",
    "avo_development_result": "开发回测结果已入账",
    "avo_final_requested": "冻结候选并开始最终验证",
    "avo_unknown_result": "研究操作结果待核对",
    "goal_compiled": "目标已编译",
    "candidate_proposed": "提出候选",
    "candidate_mutated": "变异候选",
    "red_team_tested": "红队测试",
    "reflexion_recorded": "记录失败教训",
    "bitpro_self_tested": "BitPro 自测",
    "candidate_validated": "候选通过验证",
    "paper_review_requested": "等待人工审核",
    "paper_review_decided": "模拟盘审核决定",
    "paper_review_effect": "模拟盘执行回执",
    "paper_started": "模拟盘启动",
    "paper_observed": "模拟盘观察",
    "live_approval_ready": "审批包就绪",
    "live_decided": "实盘决策",
    "live_promoted": "实盘灰度上线",
    "live_revoked": "实盘授权撤销",
    "budget_extended": "追加候选预算",
    "operator_needed": "需要人工介入",
    "mission_completed": "任务完成",
    "mission_failed": "任务失败",
}

# Scalars only. Anything not named here never reaches the console.
_SAFE_EVENT_FIELDS = (
    "child_mission_id",
    "status",
    "provider_name",
    "name",
    "provider",
    "model",
    "request_hash",
    "attempt_id",
    "passed",
    "reason",
    "decision",
    "operator_id",
    "identity_source",
    "paper_instance_id",
    "live_instance_id",
    "validation_id",
    "backtest_id",
    "bitpro_strategy_id",
    "extra_candidates",
    "strategy_name",
)


def build_pipeline_view(
    projection: ARCMissionProjection, *, now: datetime | None = None
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    if projection.goal and projection.goal.paper_review_required:
        return _paper_review_pipeline(projection, clock)
    done = _completed_stages(projection)
    frontier = _frontier(done)
    blocked = projection.state in _BLOCKED_STATES
    metrics = _stage_metrics(projection, clock)
    stages: list[dict[str, Any]] = []
    for index, (key, label) in enumerate(STAGES):
        if index < frontier:
            status = "done"
        elif index == frontier:
            status = "blocked" if blocked else "active"
        else:
            status = "pending"
        stages.append({"key": key, "label": label, "status": status, **metrics[key]})
    return {
        "mission_id": projection.mission_id,
        "state": projection.state,
        "stages": stages,
        "current_stage": STAGES[frontier][0] if frontier < len(STAGES) else None,
        "blocked": blocked,
        "blocked_reason": _blocked_reason(projection) if blocked else None,
        "finished": frontier >= len(STAGES),
        "percent": _percent(frontier, metrics, blocked),
        "updated_at": projection.updated_at.isoformat(),
        "seconds_since_update": _age_seconds(projection.updated_at, clock),
        "event_count": len(projection.events),
        "activity": [_activity_row(event) for event in projection.events[-100:]][::-1],
    }


def build_pipeline_badge(
    projection: ARCMissionProjection, *, now: datetime | None = None
) -> dict[str, Any]:
    """The compact form a mission list renders per row."""
    if projection.goal and projection.goal.paper_review_required:
        view = _paper_review_pipeline(projection, now or datetime.now(UTC))
        stages = view["stages"]
        index = next((i for i, row in enumerate(stages) if row["status"] != "done"), len(stages))
        return {
            "current_stage": view["current_stage"],
            "current_label": stages[index]["label"] if index < len(stages) else "模拟盘运行中",
            "stage_index": index,
            "stage_total": len(stages),
            "percent": view["percent"],
            "blocked": view["blocked"],
            "finished": view["finished"],
        }
    done = _completed_stages(projection)
    frontier = _frontier(done)
    blocked = projection.state in _BLOCKED_STATES
    metrics = _stage_metrics(projection, now or datetime.now(UTC))
    return {
        "current_stage": STAGES[frontier][0] if frontier < len(STAGES) else None,
        "current_label": STAGES[frontier][1] if frontier < len(STAGES) else "已上线",
        "stage_index": frontier,
        "stage_total": len(STAGES),
        "percent": _percent(frontier, metrics, blocked),
        "blocked": blocked,
        "finished": frontier >= len(STAGES),
    }


def _completed_stages(projection: ARCMissionProjection) -> list[bool]:
    """A stage is done when it produced its own result, or when a later one started.

    Reaching a stage is proof the ones before it were cleared, which also keeps a
    mission restored from a sparse projection from reading as if it went backwards.
    """
    entered = _entered_stages(projection)
    finished = _stage_results(projection)
    return [finished[index] or any(entered[index + 1 :]) for index in range(len(STAGES))]


def _entered_stages(projection: ARCMissionProjection) -> list[bool]:
    attempts = projection.attempts
    return [
        bool(projection.events),
        bool(attempts),
        any(event.event_type == "red_team_tested" for event in projection.events),
        bool(projection.self_test_records) or any(item.bitpro_backtest_id for item in attempts),
        any(item.paper_instance_id for item in attempts),
        _decidable(projection),
        any(item.live_instance_id for item in attempts),
    ]


def _stage_results(projection: ARCMissionProjection) -> list[bool]:
    attempts = projection.attempts
    approval = projection.live_approval
    return [
        any(event.event_type == "goal_compiled" for event in projection.events),
        any(event.event_type == "red_team_tested" for event in projection.events),
        any(
            event.event_type == "red_team_tested" and event.payload.get("passed")
            for event in projection.events
        ),
        any(item.bitpro_backtest_id and item.validation_id for item in attempts),
        _decidable(projection),
        approval is not None and approval.status in {"approved", "promoted"},
        any(item.live_instance_id for item in attempts),
    ]


def _decidable(projection: ARCMissionProjection) -> bool:
    """An incomplete package is a list of the gaps, not proof the mission reached approval.

    A mission that exhausted its budget still ends with a package enumerating what it
    never produced. Reading that as evidence marked every earlier stage done and let a
    run with no surviving candidate report itself three quarters of the way to live.
    """
    approval = projection.live_approval
    return approval is not None and approval.status != "incomplete"


def _frontier(done: list[bool]) -> int:
    for index, complete in enumerate(done):
        if not complete:
            return index
    return len(done)


def _stage_metrics(projection: ARCMissionProjection, clock: datetime) -> dict[str, dict[str, Any]]:
    goal = projection.goal
    budget = goal.budget if goal is not None else None
    attempts = projection.attempts
    tested = {
        str(event.payload.get("attempt_id"))
        for event in projection.events
        if event.event_type == "red_team_tested"
    }
    survived = {
        str(event.payload.get("attempt_id"))
        for event in projection.events
        if event.event_type == "red_team_tested" and event.payload.get("passed")
    }
    self_tests = projection.self_test_records
    approval = projection.live_approval
    paper = _paper_metrics(projection, clock)
    live_attempt = next((item for item in attempts if item.live_instance_id), None)
    evidence_origin = None
    provider_status = None
    for event in reversed(projection.events):
        payload = event.payload
        if provider_status is None and event.event_type == "provider_status":
            provider_status = str(payload.get("status") or "")
        if isinstance(payload.get("preflight"), dict) and evidence_origin is None:
            evidence_origin = payload["preflight"].get("source_origin")
        if evidence_origin is not None and provider_status is not None:
            break
    return {
        "goal": {
            "detail": goal.objective if goal is not None else "",
            "metrics": {
                "symbol": (goal.symbols[0] if goal and goal.symbols else None),
                "timeframe": (goal.timeframes[0] if goal and goal.timeframes else None),
                "evidence_source_origin": evidence_origin,
                "alternative_source_confirmed": (
                    goal.alternative_source_confirmed if goal is not None else None
                ),
                "provider_channel": provider_status,
            },
        },
        "explore": {
            "detail": f"{len(attempts)} / {budget.max_candidates if budget else 0} 个候选",
            "metrics": {
                "used": len(attempts),
                "budget": budget.max_candidates if budget else 0,
                "rejected": sum(1 for item in attempts if item.state == "rejected"),
                "provider_origin": sum(
                    1 for item in attempts if item.origin == "provider_hypothesis"
                ),
                "ratio": _ratio(len(attempts), budget.max_candidates if budget else 0),
            },
        },
        "red_team": {
            "detail": f"{len(tested)} 个受测，{len(survived)} 个存活",
            "metrics": {
                "tested": len(tested),
                "survived": len(survived),
                "ratio": _ratio(len(survived), len(tested)),
            },
        },
        "validate": {
            "detail": (
                f"{sum(1 for item in self_tests if item.get('passed'))} 通过 / "
                f"{len(self_tests)} 次自测"
            ),
            "metrics": {
                "runs": len(self_tests),
                "passed": sum(1 for item in self_tests if item.get("passed")),
                "backtest_id": next(
                    (item.bitpro_backtest_id for item in attempts if item.bitpro_backtest_id),
                    None,
                ),
                "ratio": _ratio(
                    sum(1 for item in self_tests if item.get("passed")), len(self_tests)
                ),
            },
        },
        "paper": {"detail": paper.pop("detail"), "metrics": paper},
        "approval": {
            "detail": _approval_detail(projection),
            "metrics": {
                "status": approval.status if approval is not None else None,
                "recommendation": approval.recommendation if approval is not None else None,
                "unknowns": len(approval.unknowns) if approval is not None else 0,
                "ratio": 1.0 if approval is not None and not approval.unknowns else 0.0,
            },
        },
        "live": {
            "detail": (f"灰度实例 {live_attempt.live_instance_id}" if live_attempt else "尚未上线"),
            "metrics": {
                "live_instance_id": live_attempt.live_instance_id if live_attempt else None,
                "ratio": 1.0 if live_attempt else 0.0,
            },
        },
    }


def _paper_metrics(projection: ARCMissionProjection, clock: datetime) -> dict[str, Any]:
    goal = projection.goal
    policy = goal.observation if goal is not None else None
    min_hours = float(policy.min_hours) if policy is not None else 0.0
    min_trades = float(policy.min_trades) if policy is not None else 0.0
    observation = projection.paper_observation
    started = projection.paper_started_at
    if started is None:
        elapsed_hours = 0.0
    else:
        start = started if started.tzinfo else started.replace(tzinfo=UTC)
        elapsed_hours = max(0.0, (clock - start).total_seconds() / 3600.0)
    trades = observation.get("trades")
    trades_value = float(trades) if isinstance(trades, int | float) else 0.0
    instance = next(
        (item.paper_instance_id for item in projection.attempts if item.paper_instance_id),
        None,
    )
    hours_ratio = _ratio(elapsed_hours, min_hours)
    trades_ratio = _ratio(trades_value, min_trades)
    detail = (
        f"{elapsed_hours:.1f} / {min_hours:.0f} 小时，{trades_value:.0f} / {min_trades:.0f} 笔"
        if instance
        else "尚未启动模拟盘"
    )
    return {
        "detail": detail,
        "instance_id": instance,
        "elapsed_hours": round(elapsed_hours, 2),
        "min_hours": min_hours,
        "trades": trades_value,
        "min_trades": min_trades,
        "equity": observation.get("equity"),
        "net_return": observation.get("net_return"),
        "instance_matched": observation.get("instance_matched"),
        "bitpro_health": observation.get("bitpro_health"),
        "ratio": min(hours_ratio, trades_ratio),
    }


def _approval_detail(projection: ARCMissionProjection) -> str:
    approval = projection.live_approval
    if approval is None:
        return "等待模拟盘证据"
    if approval.unknowns:
        return f"{len(approval.unknowns)} 项证据缺口，不可审批"
    return f"建议{'批准' if approval.recommendation == 'approve' else '拒绝'}，等待人工决策"


def _percent(frontier: int, metrics: dict[str, dict[str, Any]], blocked: bool) -> float:
    total = len(STAGES)
    if frontier >= total:
        return 100.0
    intra = 0.0
    if not blocked:
        key = STAGES[frontier][0]
        raw = metrics[key]["metrics"].get("ratio")
        intra = min(0.95, max(0.0, float(raw))) if isinstance(raw, int | float) else 0.0
    return round((frontier + intra) / total * 100.0, 1)


def _blocked_reason(projection: ARCMissionProjection) -> dict[str, Any] | None:
    for event in reversed(projection.events):
        if event.event_type not in {"operator_needed", "mission_failed"}:
            continue
        missing = event.payload.get("missing")
        preflight = event.payload.get("preflight")
        return {
            "reason": str(event.payload.get("reason") or event.event_type),
            "message": str(event.payload.get("message") or "")[:300],
            "missing": [str(item) for item in missing] if isinstance(missing, list) else [],
            # A window stopped for provenance must show what it actually is.
            "source_origin": (
                preflight.get("source_origin") if isinstance(preflight, dict) else None
            ),
            "at": event.timestamp.isoformat(),
        }
    return None


_LOG_FIELDS = (
    frozenset(_SAFE_EVENT_FIELDS)
    | {
        "id",
        "arguments",
        "result",
        "calls",
        "usage",
        "budget_snapshot",
        "attempt",
        "goal",
        "objective",
        "hypothesis",
        "family",
        "family_key",
        "direction",
        "parameter_bounds",
        "tunable_parameters",
        "strategy_spec",
        "min",
        "max",
        "target",
        "message",
        "hint",
        "metrics",
        "development",
        "self_test",
        "reasons",
        "rejection_reasons",
        "warnings",
        "total_return_pct",
        "total_return",
        "net_return_pct",
        "max_drawdown",
        "max_drawdown_pct",
        "sharpe_ratio",
        "trade_count",
        "total_trades",
        "initial_capital",
        "final_equity",
        "backtest_result_id",
        "backtest_job_id",
        "research_finished",
        "duration_ms",
        "model_calls_used",
        "max_model_calls",
        "tool_calls_used",
        "max_tool_calls",
        "backtests_used",
        "max_backtests",
        "candidates_used",
        "max_candidates",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
    }
    | {p.name for family in FAMILIES for p in family.parameters}
)


def _safe_log(value: Any, depth: int = 0) -> Any:
    # Explicit field allowlist: no provider environment, source, auth or full chat context.
    if depth > 6:
        return "[详细内容超过展示层级]"
    if isinstance(value, str):
        return value[:4000] + ("…[已截断]" if len(value) > 4000 else "")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_safe_log(item, depth + 1) for item in value[:20]]
    if isinstance(value, dict):
        return {
            key: _safe_log(item, depth + 1) for key, item in value.items() if key in _LOG_FIELDS
        }
    return None


def _activity_row(event: ARCEventV1) -> dict[str, Any]:
    detail = {
        key: event.payload[key]
        for key in _SAFE_EVENT_FIELDS
        if key in event.payload and isinstance(event.payload[key], str | int | float | bool)
    }
    return {
        "event_id": event.event_id,
        "type": event.event_type,
        "label": _EVENT_LABELS.get(event.event_type, event.event_type),
        "at": event.timestamp.isoformat(),
        "detail": detail,
        "logs": _safe_log(event.payload),
    }


def _age_seconds(moment: datetime, clock: datetime) -> float:
    stamp = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return round(max(0.0, (clock - stamp).total_seconds()), 1)


def _ratio(value: float, limit: float) -> float:
    if limit <= 0:
        return 0.0
    return round(min(1.0, max(0.0, value / limit)), 4)


def _paper_review_pipeline(projection: ARCMissionProjection, clock: datetime) -> dict[str, Any]:
    labels = STAGES[:4] + (("approval", "人工审核"), ("paper", "模拟盘运行"))
    is_avo = projection.goal is not None and projection.goal.research_mode == "avo"
    if is_avo:
        labels = (
            ("goal", "任务准备"),
            ("explore", "AVO 自主研究"),
            ("red_team", "开发实验"),
            ("validate", "最终验证"),
        ) + labels[4:]

    review = projection.paper_review
    done = [
        any(e.event_type == "goal_compiled" for e in projection.events),
        bool(projection.attempts),
        any(
            e.event_type == "red_team_tested" and e.payload.get("passed") for e in projection.events
        ),
        bool(review.get("package_hash")) and not review.get("unknowns"),
        (review.get("decision") or {}).get("decision") == "approve",
        bool(review.get("paper_instance_id")) and review.get("status") == "paper_observing",
    ]
    if is_avo:
        done[2] = bool(projection.avo.get("development"))
    # A committed later-stage receipt also proves entry into earlier stages.
    completed = [value or any(done[i + 1 :]) for i, value in enumerate(done)]
    frontier = _frontier(completed)
    if is_avo and not review.get("package_hash") and projection.avo.get("phase"):
        frontier = {"research": 1, "development": 2, "final": 3}.get(
            projection.avo["phase"], frontier
        )
    blocked = projection.state in _BLOCKED_STATES
    metrics = _stage_metrics(projection, clock)
    metrics["approval"] = {"metrics": {"status": review.get("status"), "kind": "paper"}}
    if is_avo and projection.goal is not None:
        budget = projection.goal.budget
        metrics["explore"]["detail"] = (
            f"{len(projection.attempts)} 个候选 · {budget.model_calls_used} 次模型调用 · "
            f"{budget.tool_calls_used} 次工具调用"
        )
        metrics["red_team"]["detail"] = (
            f"{len(projection.avo.get('development', {}))} 个候选完成开发实验"
        )

    stages = [
        {
            "key": key,
            "label": label,
            "status": "done"
            if i < frontier or (completed[i] and i != frontier)
            else ("blocked" if blocked else "active")
            if i == frontier
            else "pending",
            **metrics[key],
        }
        for i, (key, label) in enumerate(labels)
    ]
    return {
        "mission_id": projection.mission_id,
        "state": projection.state,
        "stages": stages,
        "current_stage": labels[frontier][0] if frontier < len(labels) else None,
        "blocked": blocked,
        "blocked_reason": _blocked_reason(projection) if blocked else None,
        "finished": frontier == len(labels),
        "percent": 100.0 * frontier / len(labels),
        "updated_at": projection.updated_at.isoformat(),
        "seconds_since_update": _age_seconds(projection.updated_at, clock),
        "event_count": len(projection.events),
        "activity": [_activity_row(event) for event in projection.events[-100:]][::-1],
    }
