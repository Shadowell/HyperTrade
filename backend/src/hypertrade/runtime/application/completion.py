"""Independent Mission completion verification.

The runtime may request verification, but it cannot manufacture completion:
only this evidence/attempt/budget check emits a persisted CompletionProofV1.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from hypertrade.runtime.domain.effects import ApprovalRequestV1, ToolCallV1
from hypertrade.runtime.domain.mission_events import mission_content_hash
from hypertrade.runtime.domain.models import (
    CompletionCriterionResultV1,
    CompletionProofV1,
    MissionProjection,
    PlanV2,
    StepAttemptV2,
    utc_now,
)


class MissionCompletionVerifier:
    def verify(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        attempts: Sequence[StepAttemptV2],
        *,
        context_valid: bool,
        approval_requests: Sequence[ApprovalRequestV1] = (),
        tool_calls: Sequence[ToolCallV1] = (),
    ) -> CompletionProofV1:
        relevant = [
            row
            for row in attempts
            if row.plan_version == plan.version
            or (row.plan_version < plan.version and row.step_id in plan.diff.kept)
        ]
        successful = [
            row for row in relevant if row.status == "succeeded" and row.observation is not None
        ]
        successful_steps = {row.step_id for row in successful}
        observations = [row.observation for row in successful if row.observation is not None]
        source_refs = tuple(sorted({ref for row in observations for ref in row.source_refs}))
        artifact_refs = tuple(sorted({ref for row in observations for ref in row.artifact_refs}))
        result_fields = Counter(key for row in observations for key in row.result)
        pending = tuple(
            row.attempt_id
            for row in relevant
            if row.status in {"running", "waiting_approval"}
        )
        pending_approvals = tuple(
            row.request_id
            for row in approval_requests
            if row.status in {"requested", "pending", "approved"}
        )
        pending_tool_calls = tuple(
            row.tool_call_id
            for row in tool_calls
            if row.status in {"prepared", "dispatched", "acknowledged", "timed_out"}
        )
        effect_unknown = any(row.status == "unknown" for row in relevant) or any(
            row.status == "effect_unknown"
            or (row.status == "reconciled" and row.reconciliation_outcome == "unknown")
            for row in tool_calls
        )
        budget_valid = _budget_valid(mission)
        criteria: list[CompletionCriterionResultV1] = []
        for criterion in mission.success_criteria:
            passed = False
            detail = "criterion was not satisfied"
            if criterion.kind == "all_steps_validated":
                missing = [row.step_id for row in plan.steps if row.step_id not in successful_steps]
                passed = not missing
                detail = "all plan steps have validated observations" if passed else (
                    f"missing validated steps: {', '.join(missing)}"
                )
            elif criterion.kind == "minimum_sources":
                expected_count = int(criterion.expected)
                passed = len(source_refs) >= expected_count
                detail = f"verified sources {len(source_refs)}/{expected_count}"
            elif criterion.kind == "artifact_kind_exists":
                expected_value = str(criterion.expected)
                passed = any(expected_value in ref for ref in artifact_refs)
                detail = (
                    f"artifact kind {expected_value} {'present' if passed else 'missing'}"
                )
            elif criterion.kind == "observation_field":
                expected_value = str(criterion.expected)
                passed = result_fields[expected_value] > 0
                detail = (
                    f"observation field {expected_value} {'present' if passed else 'missing'}"
                )
            criteria.append(
                CompletionCriterionResultV1(
                    criterion_id=criterion.criterion_id,
                    passed=passed,
                    detail=detail,
                )
            )

        gaps = [row.detail for row in criteria if not row.passed]
        if pending:
            gaps.append("unfinished tool/step attempts remain")
        if pending_approvals:
            gaps.append("approval requests remain unconsumed")
        if pending_tool_calls:
            gaps.append("external ToolCalls remain non-terminal")
        if effect_unknown:
            gaps.append("one or more attempts have unknown effect/result state")
        if not context_valid:
            gaps.append("completion context/evidence validation failed")
        if not budget_valid:
            gaps.append("Mission usage exceeds its approved budget")
        if not source_refs and not artifact_refs:
            gaps.append("no valid Evidence or Artifact binding exists")
        passed = not gaps and all(row.passed for row in criteria)
        proof_basis = {
            "mission_id": mission.mission_id,
            "mission_version": mission.version,
            "plan_version": plan.version,
            "criteria": [row.model_dump(mode="json") for row in criteria],
            "evidence_refs": source_refs,
            "artifact_refs": artifact_refs,
            "pending": pending,
            "pending_approvals": pending_approvals,
            "pending_tool_calls": pending_tool_calls,
            "effect_unknown": effect_unknown,
            "budget_valid": budget_valid,
            "context_valid": context_valid,
        }
        return CompletionProofV1(
            proof_id=f"cpf_{mission_content_hash(proof_basis)[:20]}",
            mission_id=mission.mission_id,
            mission_version=mission.version,
            plan_version=plan.version,
            passed=passed,
            criteria=tuple(criteria),
            evidence_refs=source_refs,
            artifact_refs=artifact_refs,
            gaps=tuple(dict.fromkeys(gaps)),
            pending_attempt_ids=pending,
            effect_unknown=effect_unknown,
            budget_valid=budget_valid,
            created_at=utc_now(),
        )


def _budget_valid(mission: MissionProjection) -> bool:
    usage = mission.usage
    budget = mission.budget
    return (
        usage.plan_versions <= budget.max_plan_versions
        and usage.step_attempts <= budget.max_steps_per_plan * budget.max_attempts_per_step
        and usage.tool_calls <= budget.max_tool_calls
        and usage.tokens <= budget.max_tokens
        and usage.duration_ms <= budget.max_duration_seconds * 1_000
    )
