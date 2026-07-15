"""Deterministic contract checks for the public operator answer surface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from hypertrade.runtime.domain.models import OperatorEvidenceV1, OperatorResponseV1

OPERATOR_ANSWER_SUITE_VERSION = "operator_answer_golden_v1"
_MIN_CASES = 24
_REQUIRED_COHORTS = {
    "market",
    "strategy",
    "portfolio",
    "execution",
    "context",
    "delivery",
}


@dataclass(frozen=True)
class OperatorAnswerCase:
    case_id: str
    cohort: str
    turns: tuple[str, ...]
    expected_outcomes: tuple[str, ...]
    min_evidence: int = 0
    require_unknowns: bool = False
    require_next_action: bool = False
    required_context_refs: tuple[str, ...] = ()
    required_event_types: tuple[str, ...] = ()
    max_first_public_event_ms: int | None = None
    max_visible_characters: int = 1_400
    forbidden_visible_fragments: tuple[str, ...] = ()
    require_decision_first: bool = True


@dataclass(frozen=True)
class OperatorAnswerObservation:
    response: OperatorResponseV1 | None
    visible_text: str
    event_types: tuple[str, ...] = ()
    first_public_event_ms: int | None = None


class OperatorAnswerEvalSuite:
    """Score only the visible contract, never private reasoning or raw tool payloads."""

    def cases(self) -> tuple[OperatorAnswerCase, ...]:
        return _load_cases()

    def catalog_status(self) -> dict[str, Any]:
        cases = self.cases()
        cohorts = {case.cohort for case in cases}
        return {
            "suite_version": OPERATOR_ANSWER_SUITE_VERSION,
            "case_count": len(cases),
            "cohorts": {
                name: sum(case.cohort == name for case in cases)
                for name in sorted(cohorts)
            },
            "status": (
                "ready"
                if len(cases) >= _MIN_CASES and cohorts >= _REQUIRED_COHORTS
                else "invalid"
            ),
        }

    def evaluate(
        self,
        case: OperatorAnswerCase,
        observation: OperatorAnswerObservation,
    ) -> dict[str, Any]:
        response = observation.response
        visible = observation.visible_text.strip()
        lowered = visible.lower()
        evidence = response.evidence if response is not None else ()
        evidence_has_provenance = all(
            item.source_refs or item.artifact_refs for item in evidence
        )
        checks: dict[str, bool] = {
            "response_contract": response is not None,
            "expected_outcome": response is not None and response.outcome in case.expected_outcomes,
            "evidence_count": len(evidence) >= case.min_evidence,
            "evidence_provenance": evidence_has_provenance,
            "unknowns": not case.require_unknowns or bool(response and response.unknowns),
            "next_action": not case.require_next_action or bool(response and response.next_actions),
            "context_resolution": not case.required_context_refs
            or (
                response is not None
                and set(case.required_context_refs).issubset(set(response.context_refs))
            ),
            "public_events": set(case.required_event_types).issubset(set(observation.event_types)),
            "first_public_event": case.max_first_public_event_ms is None
            or (
                observation.first_public_event_ms is not None
                and observation.first_public_event_ms <= case.max_first_public_event_ms
            ),
            "visible_length": len(visible) <= case.max_visible_characters,
            "no_internal_noise": all(
                fragment.lower() not in lowered for fragment in case.forbidden_visible_fragments
            ),
            "decision_first": not case.require_decision_first or visible.startswith("## 结论"),
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        return {
            "case_id": case.case_id,
            "cohort": case.cohort,
            "status": "passed" if not failed_checks else "failed",
            "failed_checks": failed_checks,
            "visible_characters": len(visible),
            "evidence_count": len(evidence),
        }

    def compliant_fixture(self, case: OperatorAnswerCase) -> OperatorAnswerObservation:
        """A synthetic contract fixture used only to verify the evaluator itself."""

        evidence: tuple[OperatorEvidenceV1, ...] = ()
        if case.min_evidence:
            evidence = tuple(
                OperatorEvidenceV1(
                    summary=f"已验证证据 {index + 1}",
                    source_refs=(f"eval:{case.case_id}:{index + 1}",),
                )
                for index in range(case.min_evidence)
            )
        response = OperatorResponseV1(
            mission_id="mis_operator_eval",
            outcome=case.expected_outcomes[0],
            decision="仅输出可验证结论。",
            confidence="medium" if evidence else "not_assessed",
            evidence=evidence,
            unknowns=("存在待补充的数据。",) if case.require_unknowns else (),
            next_actions=("补充数据后再判断。",) if case.require_next_action else (),
            context_refs=case.required_context_refs,
        )
        visible = "## 结论\n仅输出可验证结论。"
        return OperatorAnswerObservation(
            response=response,
            visible_text=visible,
            event_types=case.required_event_types,
            first_public_event_ms=case.max_first_public_event_ms,
        )


def _load_cases() -> tuple[OperatorAnswerCase, ...]:
    resource = files("hypertrade.evals").joinpath("operator_answer_golden_v1.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("operator_answer_golden_v1 must contain a JSON list")
    cases = tuple(_case_from_payload(item) for item in payload)
    identifiers = [case.case_id for case in cases]
    if len(cases) < _MIN_CASES or len(identifiers) != len(set(identifiers)):
        raise ValueError("operator_answer_golden_v1 must contain unique operator cases")
    cohorts = {case.cohort for case in cases}
    if cohorts < _REQUIRED_COHORTS:
        raise ValueError("operator_answer_golden_v1 must cover every operator cohort")
    return cases


def _case_from_payload(payload: object) -> OperatorAnswerCase:
    if not isinstance(payload, dict):
        raise ValueError("operator answer case must be an object")
    expected = payload.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("operator answer case needs expected requirements")
    turns = payload.get("turns")
    outcomes = expected.get("outcomes")
    if (
        not isinstance(turns, list)
        or not turns
        or not all(isinstance(item, str) and item.strip() for item in turns)
        or not isinstance(outcomes, list)
        or not outcomes
        or not all(isinstance(item, str) for item in outcomes)
    ):
        raise ValueError("operator answer case needs non-empty turns and outcomes")
    return OperatorAnswerCase(
        case_id=_required_text(payload, "case_id"),
        cohort=_required_text(payload, "cohort"),
        turns=tuple(turns),
        expected_outcomes=tuple(outcomes),
        min_evidence=_non_negative_int(expected, "min_evidence"),
        require_unknowns=bool(expected.get("require_unknowns", False)),
        require_next_action=bool(expected.get("require_next_action", False)),
        required_context_refs=_strings(expected, "required_context_refs"),
        required_event_types=_strings(expected, "required_event_types"),
        max_first_public_event_ms=_optional_non_negative_int(
            expected, "max_first_public_event_ms"
        ),
        max_visible_characters=_positive_int(expected, "max_visible_characters", default=1_400),
        forbidden_visible_fragments=_strings(expected, "forbidden_visible_fragments"),
        require_decision_first=bool(expected.get("require_decision_first", True)),
    )


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"operator answer case needs {key}")
    return value


def _strings(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"operator answer case {key} must be a string list")
    return tuple(value)


def _non_negative_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key, 0)
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"operator answer case {key} must be non-negative")
    return value


def _optional_non_negative_int(payload: dict[str, object], key: str) -> int | None:
    if key not in payload:
        return None
    return _non_negative_int(payload, key)


def _positive_int(payload: dict[str, object], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"operator answer case {key} must be positive")
    return value
