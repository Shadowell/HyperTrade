"""Build the compact public answer from validated Mission facts only."""

from __future__ import annotations

from collections.abc import Sequence

from hypertrade.runtime.application.safety_intent import classify_objective_safety
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
    failure_categories: list[str] = []
    for attempt in attempts:
        observation = attempt.observation
        if observation is None:
            continue
        unknowns.extend(item for item in observation.unknowns if item not in unknowns)
        if attempt.capability_id.startswith("runtime."):
            continue
        if observation.status == "succeeded" and _has_valid_provenance(observation):
            evidence.append(
                OperatorEvidenceV1(
                    summary=_compact(observation.summary),
                    source_refs=tuple(observation.source_refs[:3]),
                    artifact_refs=tuple(observation.artifact_refs[:3]),
                )
            )
        elif observation.status == "succeeded" and not observation.unknowns:
            unknowns.append("读取结果未返回可验证来源。")
        elif observation.error_category:
            failure_categories.append(observation.error_category)

    visible_evidence = tuple(evidence[:_MAX_VISIBLE_EVIDENCE])
    visible_unknowns = tuple(_unique(unknowns)[:_MAX_VISIBLE_UNKNOWNS])
    outcome, decision, confidence, next_actions = _outcome(
        mission.status,
        evidence=visible_evidence,
        unknowns=visible_unknowns,
        failure_categories=failure_categories,
        input_is_data_gap=safety.disposition == "needs_data",
    )
    return OperatorResponseV1(
        mission_id=mission.mission_id,
        outcome=outcome,
        decision=decision,
        confidence=confidence,
        evidence=visible_evidence,
        unknowns=visible_unknowns,
        next_actions=next_actions,
    )


def render_operator_response(response: OperatorResponseV1) -> str:
    """Render the stable answer-first terminal/Markdown projection."""

    lines = ["## 结论", response.decision]
    if response.evidence:
        lines.extend(("", "## 已验证证据"))
        for item in response.evidence:
            refs = (*item.source_refs, *item.artifact_refs)
            lines.append(f"- {item.summary}（来源：{'；'.join(refs)}）")
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
) -> tuple[str, str, str, tuple[str, ...]]:
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
        "没有获得可验证证据，当前不能给出交易判断。",
        "not_assessed",
        _data_action(unknowns),
    )


def _data_action(unknowns: tuple[str, ...]) -> tuple[str, ...]:
    if unknowns:
        return (f"补充或确认后再判断：{unknowns[0]}。",)
    return ("补充可验证的数据来源后再判断。",)


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


def _compact(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= 360:
        return normalized
    return f"{normalized[:357].rstrip()}…"


def _unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
