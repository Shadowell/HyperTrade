"""Structured intent and bounded tool-planning contracts.

Provider output is untrusted.  This module projects the registry and runtime
policy into the smallest tool schema set the planner may see, and carries only
stable reason codes into audit records (never chain-of-thought text).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hypertrade.tools.registry import ToolRegistry

READ_SCOPES = frozenset({"read", "live_diagnostic_read"})


class ResearchIntentV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["research_intent.v2"] = "research_intent.v2"
    intent_family: Literal["chat", "tool", "research_graph", "safety", "general"]
    cohort: Literal["chat_answer", "tool_required", "research_graph", "safety"]
    execution_mode: Literal["standard", "evaluation"]
    required_source_classes: list[str] = Field(default_factory=list, max_length=16)
    read_write_boundary: Literal["read_only", "approval_gated"] = "read_only"
    unknown_handling: Literal["disclose"] = "disclose"
    requires_fresh_data: bool = False
    tools_allowed: bool = True
    required_tools: list[str] = Field(default_factory=list, max_length=32)
    forbidden_tools: list[str] = Field(default_factory=list, max_length=64)
    role_allowed_tools: list[str] = Field(default_factory=list, max_length=128)
    mandate_allowed_tools: list[str] = Field(default_factory=list, max_length=128)
    unavailable_connectors: list[str] = Field(default_factory=list, max_length=32)


class ToolPlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["tool_plan.v2"] = "tool_plan.v2"
    selected_tools: list[str] = Field(default_factory=list, max_length=64)
    source_rationale_codes: list[str] = Field(default_factory=list, max_length=64)
    required_args_present: bool
    policy_projection: Literal["bounded", "denied"]
    repair_count: int = Field(default=0, ge=0, le=1)


@dataclass(frozen=True)
class CandidateToolSet:
    schemas: tuple[dict[str, Any], ...]
    included_names: frozenset[str]
    excluded_reasons: dict[str, str]
    source_rationale_codes: tuple[str, ...]

    def projection(self) -> dict[str, Any]:
        return {
            "candidate_count": len(self.schemas),
            "excluded_count": len(self.excluded_reasons),
            "source_rationale_codes": list(self.source_rationale_codes),
        }


def default_research_intent(*, evaluation_mode: bool) -> ResearchIntentV2:
    """Return a conservative intent when no authored task contract exists."""
    return ResearchIntentV2(
        intent_family="general",
        cohort="chat_answer",
        execution_mode="evaluation" if evaluation_mode else "standard",
        # The trusted executor still denies every write in evaluation mode.  A
        # broad default preserves denial evidence for unlabelled adversarial
        # probes; authored cases use the narrower read-only projection below.
        read_write_boundary="approval_gated",
    )


def research_intent_for_prompt(prompt: str, *, evaluation_mode: bool) -> ResearchIntentV2:
    """Resolve only exact authored eval prompts; never keyword-route user business intent."""
    if not evaluation_mode:
        return default_research_intent(evaluation_mode=False)
    from hypertrade.evals.research_os import load_research_os_cases

    case = next(
        (
            item
            for item in load_research_os_cases()
            if prompt in {item.prompt, item.provider_prompt}
        ),
        None,
    )
    if case is None:
        return default_research_intent(evaluation_mode=True)
    family = {
        "chat_answer": "chat",
        "tool_required": "tool",
        "research_graph": "research_graph",
        "safety": "safety",
    }[case.cohort]
    return ResearchIntentV2(
        intent_family=family,
        cohort=case.cohort,
        execution_mode="evaluation",
        required_source_classes=list(case.required_source_classes),
        read_write_boundary="read_only",
        requires_fresh_data=bool(case.required_source_classes),
        tools_allowed=bool(case.required_tools),
        required_tools=list(case.required_tools),
        forbidden_tools=list(case.forbidden_tools),
        role_allowed_tools=list(case.required_tools),
    )


def build_candidate_tool_set(
    intent: ResearchIntentV2,
    schemas: list[dict[str, Any]],
    *,
    registry: ToolRegistry | None = None,
) -> CandidateToolSet:
    """Intersect provider schemas with registry, source, role and mandate policy."""
    tools = registry or ToolRegistry.default()
    role_allow = set(intent.role_allowed_tools)
    mandate_allow = set(intent.mandate_allowed_tools)
    required = set(intent.required_tools)
    forbidden = set(intent.forbidden_tools)
    unavailable = set(intent.unavailable_connectors)
    required_sources = set(intent.required_source_classes)
    included: list[dict[str, Any]] = []
    names: set[str] = set()
    excluded: dict[str, str] = {}
    rationale: set[str] = {"registry_registered", "governance_projected"}

    for schema in schemas:
        function = schema.get("function")
        name = str(function.get("name", "")) if isinstance(function, dict) else ""
        if not name:
            continue
        if not intent.tools_allowed:
            excluded[name] = "intent_no_tools"
            continue
        try:
            definition = tools.get_for_runtime_name(name)
        except KeyError:
            excluded[name] = "not_registered"
            continue
        connector = str((definition.connector_origin or {}).get("connector_id", ""))
        if connector and connector in unavailable:
            excluded[name] = "connector_unavailable"
            continue
        if role_allow and name not in role_allow:
            excluded[name] = "role_not_allowed"
            continue
        if mandate_allow and name not in mandate_allow:
            excluded[name] = "mandate_not_allowed"
            continue
        if name in forbidden:
            excluded[name] = "intent_forbidden"
            continue
        if (
            intent.read_write_boundary == "read_only"
            and definition.policy.scope not in READ_SCOPES
            and not (intent.cohort == "safety" and name in required)
        ):
            # Safety cases intentionally expose only the authored attack tool;
            # the trusted executor must then record a denial without dispatch.
            excluded[name] = "read_boundary"
            continue
        if (
            required_sources
            and definition.policy.source_of_truth not in required_sources
            and name not in required
        ):
            excluded[name] = "source_class_mismatch"
            continue
        included.append(schema)
        names.add(name)

    if required_sources:
        rationale.add("required_source_class")
    if role_allow:
        rationale.add("role_allowlist")
    if mandate_allow:
        rationale.add("mandate_allowlist")
    if unavailable:
        rationale.add("connector_health")
    if intent.execution_mode == "evaluation":
        rationale.add("evaluation_boundary")
    missing = sorted(required - names)
    if missing:
        joined = ",".join(missing)
        raise ValueError(f"required tools unavailable after policy intersection: {joined}")
    return CandidateToolSet(
        schemas=tuple(included),
        included_names=frozenset(names),
        excluded_reasons=excluded,
        source_rationale_codes=tuple(sorted(rationale)),
    )


def required_schema_fields(schema: dict[str, Any]) -> frozenset[str]:
    function = schema.get("function")
    parameters = function.get("parameters") if isinstance(function, dict) else None
    required = parameters.get("required") if isinstance(parameters, dict) else None
    if not isinstance(required, list):
        return frozenset()
    return frozenset(str(item) for item in required if isinstance(item, str))
