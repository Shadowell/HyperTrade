"""End-to-end task-completion checks for the operator-facing Agent surface.

Unlike the older contract suite, this evaluator treats a missing requested fact,
unresolved multi-turn reference or generic final answer as a task failure. It
scores only public, synthetic evaluation output and never model reasoning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from hypertrade.runtime.domain.models import OperatorResponseV1

TASK_COMPLETION_SUITE_VERSION = "operator_task_completion.v1"
_EXPECTED_CASE_COUNT = 100
_EXPECTED_COHORTS = {
    "market",
    "live_strategy",
    "backtest",
    "paper",
    "knowledge",
    "context",
    "ambiguity",
    "safety",
    "delivery",
    "portfolio",
}


@dataclass(frozen=True)
class TaskCompletionCase:
    case_id: str
    cohort: str
    turns: tuple[str, ...]
    expected_outcomes: tuple[str, ...]
    required_capabilities: tuple[str, ...] = ()
    required_visible: tuple[str, ...] = ()
    required_decision: tuple[str, ...] = ()
    required_source_prefixes: tuple[str, ...] = ()
    forbidden_visible: tuple[str, ...] = ()
    fixture: str = ""
    # Evidence is mandatory only for cases that claim a factual result.  A safe
    # refusal or a data-gap answer must not be forced to invent an evidence row.
    min_evidence: int = 0
    require_unknowns: bool = False
    require_next_actions: bool = False
    require_context: bool = False
    required_event_types: tuple[str, ...] = ()
    max_first_public_event_ms: int | None = None
    max_visible_characters: int = 1_800
    require_desktop_final: bool = False


@dataclass(frozen=True)
class TaskCompletionObservation:
    response: OperatorResponseV1 | None
    visible_text: str
    capability_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    first_public_event_ms: int | None = None
    executed_turns: int = 0
    desktop_final_text: str = ""


class OperatorTaskCompletionSuite:
    """Evaluate the whole user task, not merely Mission schema compliance."""

    def cases(self) -> tuple[TaskCompletionCase, ...]:
        return _load_cases()

    def catalog_status(self) -> dict[str, Any]:
        cases = self.cases()
        cohorts = {case.cohort for case in cases}
        return {
            "suite_version": TASK_COMPLETION_SUITE_VERSION,
            "case_count": len(cases),
            "cohorts": {
                name: sum(case.cohort == name for case in cases) for name in sorted(cohorts)
            },
            "multi_turn_count": sum(len(case.turns) > 1 for case in cases),
            "status": (
                "ready"
                if len(cases) == _EXPECTED_CASE_COUNT
                and cohorts == _EXPECTED_COHORTS
                and all(sum(case.cohort == cohort for case in cases) >= 10 for cohort in cohorts)
                else "invalid"
            ),
        }

    def evaluate(
        self,
        case: TaskCompletionCase,
        observation: TaskCompletionObservation,
    ) -> dict[str, Any]:
        response = observation.response
        visible = observation.visible_text.strip()
        lowered = visible.casefold()
        evidence = response.evidence if response is not None else ()
        checks: dict[str, bool] = {
            "response_contract": response is not None,
            "expected_outcome": response is not None
            and response.outcome in case.expected_outcomes,
            "requested_facts": all(
                fragment.casefold() in lowered for fragment in case.required_visible
            ),
            "decision_facts": response is not None
            and all(
                fragment.casefold() in response.decision.casefold()
                for fragment in case.required_decision
            ),
            "capability_route": set(case.required_capabilities).issubset(
                set(observation.capability_ids)
            ),
            "source_provenance": _has_source_prefixes(
                case.required_source_prefixes, observation.source_refs
            ),
            "evidence_count": len(evidence) >= case.min_evidence,
            "unknowns": not case.require_unknowns or bool(response and response.unknowns),
            "next_actions": not case.require_next_actions
            or bool(response and response.next_actions),
            "conversation_context": not case.require_context
            or (
                observation.executed_turns == len(case.turns)
                and response is not None
                and bool(response.context_refs)
            ),
            "public_events": set(case.required_event_types).issubset(set(observation.event_types)),
            "first_public_event": case.max_first_public_event_ms is None
            or (
                observation.first_public_event_ms is not None
                and observation.first_public_event_ms <= case.max_first_public_event_ms
            ),
            "final_delivery": not case.require_desktop_final
            or bool(observation.desktop_final_text)
            and observation.desktop_final_text.strip() == visible,
            "visible_length": len(visible) <= case.max_visible_characters,
            "no_forbidden_output": all(
                fragment.casefold() not in lowered for fragment in case.forbidden_visible
            ),
            "decision_first": visible.startswith("## 结论"),
        }
        failed_checks = tuple(name for name, passed in checks.items() if not passed)
        return {
            "case_id": case.case_id,
            "cohort": case.cohort,
            "status": "passed" if not failed_checks else "failed",
            "failed_checks": list(failed_checks),
            "remediation_ids": _remediation_ids(failed_checks),
            "visible_characters": len(visible),
            "evidence_count": len(evidence),
            "executed_turns": observation.executed_turns,
        }


def remediation_catalog() -> dict[str, dict[str, str]]:
    """Stable repair buckets used by reports; no benchmark can hide a failed task."""

    return {
        "R1": {
            "title": "路由与能力选择",
            "scope": "补齐意图识别、参数提取和受审查 capability 路由。",
        },
        "R2": {
            "title": "来源与数据映射",
            "scope": "补齐受控数据读取、字段投影和可验证来源，不能用记忆替代。",
        },
        "R3": {
            "title": "面向任务的回答编排",
            "scope": "把已验证字段编排成直接答案，移除空泛结论和无关内部信息。",
        },
        "R4": {
            "title": "多轮上下文",
            "scope": "引入服务端会话与指代消解；有歧义时只提出最小澄清。",
        },
        "R5": {
            "title": "流式与桌面最终交付",
            "scope": "确保 final 投影覆盖进度文本且保留答案事实和证据。",
        },
        "R6": {
            "title": "安全与数据缺口语义",
            "scope": "阻断越权动作，数据不足时说明缺什么和下一步，不伪造结论。",
        },
    }


def _load_cases() -> tuple[TaskCompletionCase, ...]:
    resource = files("hypertrade.evals").joinpath("operator_task_completion_v1.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("operator_task_completion_v1 must contain a list")
    cases = tuple(_case_from_payload(item) for item in payload)
    identifiers = [case.case_id for case in cases]
    if len(cases) != _EXPECTED_CASE_COUNT or len(identifiers) != len(set(identifiers)):
        raise ValueError("operator_task_completion_v1 must contain 100 unique cases")
    if {case.cohort for case in cases} != _EXPECTED_COHORTS:
        raise ValueError("operator_task_completion_v1 must cover the required cohorts")
    if sum(len(case.turns) > 1 for case in cases) < 10:
        raise ValueError("operator_task_completion_v1 must contain at least 10 multi-turn cases")
    return cases


def _case_from_payload(payload: object) -> TaskCompletionCase:
    if not isinstance(payload, dict):
        raise ValueError("task completion case must be an object")
    expected = payload.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("task completion case requires expected")
    turns = _strings(payload, "turns")
    outcomes = _strings(expected, "outcomes")
    if not turns or not outcomes:
        raise ValueError("task completion case requires turns and outcomes")
    return TaskCompletionCase(
        case_id=_required_text(payload, "case_id"),
        cohort=_required_text(payload, "cohort"),
        turns=turns,
        expected_outcomes=outcomes,
        required_capabilities=_strings(expected, "required_capabilities"),
        required_visible=_strings(expected, "required_visible"),
        required_decision=_strings(expected, "required_decision"),
        required_source_prefixes=_strings(expected, "required_source_prefixes"),
        forbidden_visible=_strings(expected, "forbidden_visible"),
        fixture=_optional_text(expected, "fixture"),
        min_evidence=_non_negative_int(expected, "min_evidence", default=0),
        require_unknowns=bool(expected.get("require_unknowns", False)),
        require_next_actions=bool(expected.get("require_next_actions", False)),
        require_context=bool(expected.get("require_context", False)),
        required_event_types=_strings(expected, "required_event_types"),
        max_first_public_event_ms=_optional_int(expected, "max_first_public_event_ms"),
        max_visible_characters=_positive_int(expected, "max_visible_characters", default=1_800),
        require_desktop_final=bool(expected.get("require_desktop_final", False)),
    )


def _has_source_prefixes(prefixes: tuple[str, ...], refs: tuple[str, ...]) -> bool:
    return all(any(ref.startswith(prefix) for ref in refs) for prefix in prefixes)


def _remediation_ids(failed_checks: tuple[str, ...]) -> list[str]:
    mapping = {
        "capability_route": "R1",
        "source_provenance": "R2",
        "requested_facts": "R3",
        "decision_facts": "R3",
        "decision_first": "R3",
        "visible_length": "R3",
        "no_forbidden_output": "R3",
        "conversation_context": "R4",
        "final_delivery": "R5",
        "public_events": "R5",
        "first_public_event": "R5",
        "expected_outcome": "R6",
        "unknowns": "R6",
        "next_actions": "R6",
        "evidence_count": "R2",
        "response_contract": "R5",
    }
    return list(dict.fromkeys(mapping[item] for item in failed_checks if item in mapping))


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"task completion case requires {key}")
    return value


def _optional_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"task completion case {key} must be text")
    return value


def _strings(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"task completion case {key} must be a string list")
    return tuple(value)


def _non_negative_int(payload: dict[str, object], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"task completion case {key} must be non-negative")
    return value


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    if key not in payload:
        return None
    return _non_negative_int(payload, key, default=0)


def _positive_int(payload: dict[str, object], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"task completion case {key} must be positive")
    return value
