"""Build the compact public answer from validated Mission facts only."""

from __future__ import annotations

from collections.abc import Sequence

from hypertrade.runtime.application.safety_intent import (
    classify_objective_safety,
    requires_evidence_review,
)
from hypertrade.runtime.domain.models import (
    MissionProjection,
    MissionStatus,
    OperatorEvidenceV1,
    OperatorResponseV1,
    StepAttemptV2,
    StepObservationV2,
)

_MAX_VISIBLE_EVIDENCE = 3
_MAX_VISIBLE_UNKNOWNS = 3


def build_operator_response(
    mission: MissionProjection,
    attempts: Sequence[StepAttemptV2],
) -> OperatorResponseV1:
    """Project evidence, uncertainty and only useful next actions for an operator.

    This boundary intentionally does not expose a Plan, step id, tool count, raw
    payload or model reasoning. Those remain available through the audit surface.
    """

    evidence: list[OperatorEvidenceV1] = []
    safety = classify_objective_safety(mission.objective)
    unknowns = _unique((*mission.unknowns, *safety.unknowns))
    evidence_review_required = requires_evidence_review(mission.objective)
    promotion_review_required = _requires_promotion_review(mission.objective)
    direction_review_required = _requires_direction_review(mission.objective)
    if evidence_review_required:
        unknowns.append("样本内与样本外结果的可比性和失效原因尚未完成独立复核。")
    failure_categories: list[str] = []
    for attempt in attempts:
        observation = attempt.observation
        if observation is None:
            continue
        unknowns.extend(item for item in observation.unknowns if item not in unknowns)
        if attempt.capability_id.startswith("runtime."):
            continue
        if observation.status == "succeeded" and _has_valid_provenance(observation):
            is_live_strategy_inventory = attempt.capability_id == "bitpro.live_strategy_summary"
            evidence.append(
                OperatorEvidenceV1(
                    summary=_compact(
                        observation.summary,
                        max_chars=3_600 if is_live_strategy_inventory else 360,
                    ),
                    source_refs=tuple(
                        observation.source_refs[:20]
                        if is_live_strategy_inventory
                        else observation.source_refs[:3]
                    ),
                    artifact_refs=tuple(observation.artifact_refs[:3]),
                )
            )
        elif observation.status == "succeeded" and not observation.unknowns:
            unknowns.append("读取结果未返回可验证来源。")
        elif observation.error_category:
            failure_categories.append(observation.error_category)

    visible_evidence = tuple(evidence[:_MAX_VISIBLE_EVIDENCE])
    visible_unknowns = tuple(_unique(unknowns)[:_MAX_VISIBLE_UNKNOWNS])
    clarification_options = _clarification_options(mission.constraints)
    outcome: str
    decision: str
    confidence: str
    next_actions: tuple[str, ...]
    if clarification_options or _objective_needs_clarification(mission.objective):
        outcome = "needs_clarification"
        options = "、".join(clarification_options) or "要分析的标的、策略或回测编号"
        decision = f"需要先确认对象：请指定 {options}。"
        confidence = "not_assessed"
        next_actions = (f"请回复要分析的具体对象：{options}。",)
    elif safety.disposition != "normal":
        outcome, decision, confidence, next_actions = _safety_outcome(safety)
    elif promotion_review_required:
        outcome = "needs_review"
        decision = "不能仅凭单次回测直接进入模拟盘；需要复核样本外表现、交易成本和风险限额。"
        confidence = "not_assessed"
        next_actions = ("由策略负责人复核后再决定是否进入模拟盘。",)
    elif direction_review_required:
        outcome = "needs_review"
        decision = "当前证据不能形成买卖指令；需要由有权限的操作员结合风险限额完成复核。"
        confidence = "not_assessed"
        next_actions = ("复核行情新鲜度、风险限额和策略规则后再决定方向。",)
    else:
        outcome, decision, confidence, next_actions = _outcome(
            mission.status,
            evidence=visible_evidence,
            unknowns=visible_unknowns,
            failure_categories=failure_categories,
            input_is_data_gap=False,
            evidence_review_required=evidence_review_required,
        )
        if visible_evidence and outcome in {"completed", "needs_data"}:
            # The first evidence item is the task-specific, validated projection
            # selected by the planner. It replaces generic completion boilerplate.
            decision = visible_evidence[0].summary
        elif not visible_evidence and visible_unknowns and outcome == "needs_data":
            # An empty search should name the exact missing record, not replace
            # it with a generic completion phrase that hides the user's target.
            decision = _decision_unknown(mission.objective, visible_unknowns)
        if visible_evidence and _objective_requests_evidence(mission.objective):
            # A plural evidence question needs the bounded evidence set in the
            # conclusion, not only whichever capability happened to run first.
            decision = "可验证证据：" + "；".join(
                _compact(item.summary, max_chars=180) for item in visible_evidence
            )
        if visible_evidence and _objective_requests_next_steps(mission.objective):
            decision = "下一步：基于已验证证据补齐样本外区间、交易成本和失效条件，再形成研究结论。"
            next_actions = ("下一步：运行独立样本外验证，并记录成本和失效条件。",)
    # The public schema has a strict decision bound. Evidence may legitimately
    # be longer (for example, a requested strategy inventory), but a verbose
    # source projection must never make the entire Mission delivery fail.
    decision = _compact(decision, max_chars=600)
    return OperatorResponseV1(
        mission_id=mission.mission_id,
        outcome=outcome,
        decision=decision,
        confidence=confidence,
        evidence=visible_evidence,
        unknowns=visible_unknowns,
        next_actions=next_actions,
        context_refs=tuple(
            constraint
            for constraint in mission.constraints
            if constraint.startswith("conversation:")
        ),
    )


def render_operator_response(response: OperatorResponseV1) -> str:
    """Render the stable answer-first terminal/Markdown projection."""

    lines = ["## 结论", response.decision]
    if response.evidence:
        lines.extend(("", "## 已验证证据"))
        for item in response.evidence:
            if _is_live_strategy_inventory(item):
                lines.extend((item.summary, f"_来源：{_source_label(item)}_"))
            else:
                lines.append(f"- {item.summary}（来源：{_source_label(item)}）")
    if response.unknowns:
        lines.extend(("", "## 未验证或数据缺口"))
        lines.extend(f"- {item}" for item in response.unknowns)
    if response.next_actions:
        lines.extend(("", "## 下一步"))
        lines.extend(f"- {item}" for item in response.next_actions)
    return "\n".join(lines)


def _outcome(
    status: MissionStatus,
    *,
    evidence: tuple[OperatorEvidenceV1, ...],
    unknowns: tuple[str, ...],
    failure_categories: Sequence[str],
    input_is_data_gap: bool,
    evidence_review_required: bool,
) -> tuple[str, str, str, tuple[str, ...]]:
    if evidence_review_required:
        return (
            "needs_review",
            "样本内与样本外证据存在冲突，当前不能据此推进策略或改变风险暴露。",
            "not_assessed",
            ("核对样本划分、成本口径和市场制度后，由策略负责人完成独立复核。",),
        )
    if status == MissionStatus.COMPLETED and evidence and not unknowns:
        return (
            "completed",
            "已完成本次只读研究；结论仅覆盖下列已验证证据。",
            "medium",
            (),
        )
    if status == MissionStatus.COMPLETED and evidence:
        return (
            "needs_data",
            "已完成可验证部分；缺失信息未被推断为交易结论。",
            "low",
            _data_action(unknowns),
        )
    if status == MissionStatus.WAITING_APPROVAL:
        return (
            "needs_review",
            "当前操作需要人工复核或批准，不能自动继续。",
            "not_assessed",
            ("由有权限的操作员复核并决定是否批准。",),
        )
    if status == MissionStatus.WAITING_INPUT:
        if input_is_data_gap:
            return (
                "needs_data",
                "请求依赖的数据来源或新鲜度未获验证，当前不能给出交易判断。",
                "not_assessed",
                _data_action(unknowns),
            )
        return (
            "needs_clarification",
            "当前缺少继续判断所需的信息或确认，不能给出可执行结论。",
            "not_assessed",
            _data_action(unknowns),
        )
    if status in {MissionStatus.PAUSED, MissionStatus.PAUSE_REQUESTED, MissionStatus.RUNNING}:
        return (
            "in_progress",
            "研究仍在进行；当前没有足够的已验证证据可供判断。",
            "not_assessed",
            (),
        )
    if status in {MissionStatus.CANCELED, MissionStatus.CANCEL_REQUESTED}:
        return (
            "blocked",
            "请求未完成；当前不能据此给出交易判断。",
            "not_assessed",
            ("如需继续，请提交新的受治理研究请求。",),
        )
    if status in {MissionStatus.FAILED, MissionStatus.BUDGET_EXHAUSTED} or failure_categories:
        category = (
            failure_categories[0]
            if failure_categories
            else (
                "budget_exhausted"
                if status == MissionStatus.BUDGET_EXHAUSTED
                else "unknown_failure"
            )
        )
        return (
            "failed",
            "所需证据未能获得，当前不能给出可执行结论。",
            "not_assessed",
            (f"处理失败原因后重新运行：{_failure_label(category)}。",),
        )
    return (
        "needs_data",
        "缺少完成本次查询所需的可验证数据。",
        "not_assessed",
        _data_action(unknowns),
    )


def _data_action(unknowns: tuple[str, ...]) -> tuple[str, ...]:
    if unknowns:
        return (f"补充或确认后再继续：{unknowns[0].rstrip('。！？')}。",)
    return ("补充可验证的数据来源后再继续。",)


def _safety_outcome(safety: object) -> tuple[str, str, str, tuple[str, ...]]:
    disposition = getattr(safety, "disposition", "normal")
    reason = getattr(safety, "reason", "")
    if disposition == "blocked":
        decision = (
            "不能显示凭证、Token 或私钥。"
            if reason == "secret_disclosure_request_blocked"
            else "不能执行该请求：它超出只读研究权限，未执行任何交易、策略或资金变更。"
        )
        return "blocked", decision, "not_assessed", ("如需继续，请提交只读研究问题。",)
    if disposition == "needs_review":
        return (
            "needs_review",
            "该操作需要独立的风险与人工复核，当前不会自动执行。",
            "not_assessed",
            ("由有权限的操作员复核并决定是否批准。",),
        )
    return (
        "needs_data",
        "当前请求缺少可验证的前提数据，不能据此形成结论。",
        "not_assessed",
        ("补充可验证数据或改为只读事实查询后再继续。",),
    )


def _clarification_options(constraints: tuple[str, ...]) -> tuple[str, ...]:
    for constraint in constraints:
        if constraint.startswith("clarification_options:"):
            return tuple(item for item in constraint.partition(":")[2].split("|") if item)
    return ()


def _objective_needs_clarification(objective: str) -> bool:
    lowered = objective.casefold()
    return (
        any(term in lowered for term in ("分析他的交易数据", "看看这个策略", "现在怎么办"))
        or ("这个 backtest" in lowered and not any(char.isdigit() for char in lowered))
        or ("既要 btc 又要 eth" in lowered and "他的结果" in lowered)
    )


def _requires_promotion_review(objective: str) -> bool:
    lowered = objective.casefold()
    return "直接进入模拟盘" in lowered or ("回测" in lowered and "进入模拟盘" in lowered)


def _requires_direction_review(objective: str) -> bool:
    return "买还是卖" in objective.casefold()


def _objective_requests_next_steps(objective: str) -> bool:
    lowered = objective.casefold()
    return "下一步如何研究" in lowered or "下一步怎么研究" in lowered


def _objective_requests_evidence(objective: str) -> bool:
    lowered = objective.casefold()
    return "哪些证据" in lowered or "证据支持" in lowered


def _decision_unknown(objective: str, unknowns: tuple[str, ...]) -> str:
    """Select the missing fact that answers the user's named data surface."""

    lowered = objective.casefold()
    if "记忆" in lowered:
        for item in unknowns:
            if "记忆" in item:
                return item
    if "知识库" in lowered:
        for item in unknowns:
            if "研究证据" in item:
                return item
    return unknowns[0]


def _failure_label(category: str) -> str:
    return {
        "source_unavailable": "数据源不可用",
        "timeout": "读取超时",
        "rate_limited": "数据源限流",
        "contract_mismatch": "数据契约不匹配",
        "permission_denied": "权限不足",
    }.get(category, "运行失败")


def _has_valid_provenance(observation: StepObservationV2) -> bool:
    """Reject sentinel refs: an empty search is not evidence for a public conclusion."""

    refs = (*observation.source_refs, *observation.artifact_refs)
    return any(not ref.endswith(":no_matches") for ref in refs)


def _source_label(item: OperatorEvidenceV1) -> str:
    refs = (*item.source_refs, *item.artifact_refs)
    if refs and all(ref.startswith("bitpro_mcp:live_strategies:") for ref in refs):
        return "BitPro MCP（每条策略均可追溯）"
    return "；".join(refs)


def _is_live_strategy_inventory(item: OperatorEvidenceV1) -> bool:
    return bool(item.source_refs) and all(
        ref.startswith("bitpro_mcp:live_strategies:") for ref in item.source_refs
    )


def _compact(value: str, *, max_chars: int = 360) -> str:
    normalized = "\n".join(" ".join(line.split()) for line in value.splitlines()).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3].rstrip()}…"


def _unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
