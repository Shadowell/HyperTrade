"""Named failure fixtures for the isolated operator-answer evaluator only."""

from __future__ import annotations

from typing import Literal

EvaluationFailure = Literal["timeout", "source_unavailable"]
_PREFIX = "operator_eval_fixture:"
_CASE_FAILURES: dict[str, EvaluationFailure] = {
    "source_timeout": "timeout",
    "provider_failure": "source_unavailable",
}


def fixture_constraint(case_id: str) -> str:
    """Return a durable, non-sensitive fixture marker for one authored case."""

    failure = _CASE_FAILURES.get(case_id, "")
    return f"{_PREFIX}{failure}" if failure else ""


def failure_from_constraints(constraints: tuple[str, ...]) -> EvaluationFailure | None:
    """Recognize only the two authored failure modes; arbitrary values are ignored."""

    for item in constraints:
        value = item.removeprefix(_PREFIX)
        if item.startswith(_PREFIX) and value in _CASE_FAILURES.values():
            return value  # type: ignore[return-value]
    return None
