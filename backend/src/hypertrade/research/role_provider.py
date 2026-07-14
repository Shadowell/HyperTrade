"""Provider adapters for strict research-role planning and evidence drafts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from hypertrade.providers.chat import ChatProvider, ChatResponse
from hypertrade.research.roles.definitions import RoleDefinition
from hypertrade.research.roles.schemas import (
    DataGapDraft,
    RoleOutput,
    RoleToolCall,
    RoleToolPlan,
    RoleUsage,
    ToolObservation,
)
from hypertrade.research.tool_policy import RoleToolPolicy
from hypertrade.skills.lifecycle import ApprovedSkillLoader


@dataclass(frozen=True)
class RoleProviderContext:
    task_id: str
    node_run_id: str
    objective: str
    mandate: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ProviderResult[T]:
    value: T
    usage: RoleUsage


class ResearchRoleProvider(Protocol):
    name: str
    model: str

    def plan(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        policy: RoleToolPolicy,
    ) -> ProviderResult[RoleToolPlan]: ...

    def synthesize(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        observations: list[ToolObservation],
    ) -> ProviderResult[RoleOutput]: ...


class RoleSchemaError(ValueError):
    pass


class ChatResearchRoleProvider:
    """Uses ChatProvider but accepts only strict JSON; private reasoning is discarded."""

    def __init__(
        self,
        provider: ChatProvider,
        *,
        skill_loader: ApprovedSkillLoader | None = None,
    ) -> None:
        self.provider = provider
        self.skill_loader = skill_loader
        self.name = provider.name
        self.model = provider.model

    def plan(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        policy: RoleToolPolicy,
    ) -> ProviderResult[RoleToolPlan]:
        response = self.provider.chat(
            [
                {"role": "system", "content": self._system_prompt(role)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "phase": "tool_plan",
                            "objective": context.objective,
                            "mandate": _bounded(context.mandate),
                            "allowed_tools": [tool.name for tool in policy.allowed],
                            "rules": [
                                "Return JSON only.",
                                "Every tool name must exactly match one allowed_tools entry.",
                                "Return an empty tool_calls list when no allowed tool is needed.",
                            ],
                            "output_contract": {
                                "tool_calls": [],
                                "rationale": "short",
                            },
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ]
        )
        try:
            plan = RoleToolPlan.model_validate(_json_object(response.content))
        except (ValueError, ValidationError):
            # Malformed tool plans fail closed to no dispatch. The evidence phase will
            # surface missing observations as a data gap instead of guessing a call.
            plan = RoleToolPlan(tool_calls=[], rationale="invalid_plan_failed_closed")
        return ProviderResult(plan, _usage(response))

    def synthesize(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        observations: list[ToolObservation],
    ) -> ProviderResult[RoleOutput]:
        request = {
            "phase": "evidence_output",
            "objective": context.objective,
            "mandate": _bounded(context.mandate),
            "prior_evidence": [_bounded(item) for item in context.evidence],
            "observations": [observation.model_dump(mode="json") for observation in observations],
            "rules": [
                "Return JSON only.",
                "Facts must use source_ids from observations.",
                "Inferences and counter-evidence must cite prior_evidence IDs.",
                "Never include credentials, private reasoning, raw artifacts, or write actions.",
            ],
            "output_contract": {
                "summary": "short",
                "evidence": [
                    {
                        "evidence_type": "data_gap",
                        "claim": "missing capability",
                        "confidence": 0,
                        "source_ids": [],
                        "supporting_evidence_ids": [],
                        "opposing_evidence_ids": [],
                        "valid_for_seconds": None,
                        "expected_sources": ["tool"],
                        "remediation": "restore source and rerun",
                    }
                ],
                "strategy_spec": None,
            },
        }
        first = self.provider.chat(
            [
                {"role": "system", "content": self._system_prompt(role)},
                {
                    "role": "user",
                    "content": json.dumps(request, ensure_ascii=False, sort_keys=True),
                },
            ]
        )
        try:
            output = RoleOutput.model_validate(_json_object(first.content))
            return ProviderResult(output, _usage(first))
        except (ValueError, ValidationError) as first_error:
            repair = self.provider.chat(
                [
                    {"role": "system", "content": self._system_prompt(role)},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                **request,
                                "phase": "schema_repair_once",
                                "validation_error": str(first_error)[:1_000],
                                "invalid_output": first.content[:8_000],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                ]
            )
            try:
                output = RoleOutput.model_validate(_json_object(repair.content))
            except (ValueError, ValidationError):
                # Invalid model text is untrusted and is never persisted. After the
                # single repair allowance, continue with an explicit unknown instead
                # of fabricating evidence or terminating the whole fixed graph.
                output = RoleOutput(
                    summary=f"{role.key} output invalid after one schema repair",
                    evidence=[
                        DataGapDraft(
                            claim=f"{role.key} provider output could not satisfy schema",
                            confidence=0.0,
                            expected_sources=["tool"],
                            remediation=(
                                "Inspect the provider/model compatibility and rerun only "
                                f"the {role.key} node."
                            ),
                        )
                    ],
                )
            usage = _usage(first)
            repaired_usage = _usage(repair)
            return ProviderResult(
                output,
                RoleUsage(
                    model_calls=usage.model_calls + repaired_usage.model_calls,
                    tokens=usage.tokens + repaired_usage.tokens,
                ),
            )

    def _system_prompt(self, role: RoleDefinition) -> str:
        if self.skill_loader is None:
            return role.prompt
        return role.prompt + self.skill_loader.prompt_for_role(role)


class DeterministicGapRoleProvider:
    """Keyless fail-closed fallback: exercises the graph but never invents analysis."""

    name = "deterministic_gap"
    model = "none"

    def plan(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        policy: RoleToolPolicy,
    ) -> ProviderResult[RoleToolPlan]:
        del context
        calls = [
            RoleToolCall(name=tool.name)
            for tool in policy.allowed[: role.budget.max_tool_calls]
        ]
        return ProviderResult(
            RoleToolPlan(tool_calls=calls, rationale="bounded deterministic read plan"),
            RoleUsage(),
        )

    def synthesize(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        observations: list[ToolObservation],
    ) -> ProviderResult[RoleOutput]:
        del context
        unavailable = [item.tool_name for item in observations if not item.available]
        claim = (
            f"{role.key} requires provider-backed synthesis; deterministic fallback "
            "does not form a market or strategy conclusion"
        )
        remediation = "Configure an approved chat provider and rerun only this role node."
        if unavailable:
            remediation = f"Restore {', '.join(sorted(unavailable))}; then {remediation}"
        output = RoleOutput(
            summary=claim,
            evidence=[
                DataGapDraft(
                    claim=claim,
                    confidence=0.0,
                    expected_sources=["tool"],
                    remediation=remediation,
                )
            ],
        )
        return ProviderResult(output, RoleUsage())


def _usage(response: ChatResponse) -> RoleUsage:
    usage = response.usage.to_dict()
    return RoleUsage(model_calls=1, tokens=int(usage.get("total_tokens", 0)))


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("role provider output must be a JSON object")
    return parsed


def _bounded(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        return {
            str(key): _bounded(item, depth=depth + 1)
            for key, item in list(value.items())[:50]
            if str(key).lower()
            not in {"access_token", "api_key", "authorization", "cookie", "password", "secret"}
        }
    if isinstance(value, list | tuple):
        return [_bounded(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:1_000]
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:1_000]
