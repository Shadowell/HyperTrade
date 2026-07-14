"""One bounded research role attempt: plan, policy, tools, schema, Evidence V2."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import partial
from threading import BoundedSemaphore
from typing import Any

import httpx

from hypertrade.agent.checkpoints import TaskCheckpointService
from hypertrade.agent.task_events import TaskEventService
from hypertrade.db import Database, utc_now
from hypertrade.research.budgets import TaskBudgetGuard
from hypertrade.research.evidence import EvidenceService
from hypertrade.research.evidence_schemas import (
    CounterEvidenceInput,
    DataGapEvidenceInput,
    EvidenceScope,
    EvidenceSourceRef,
    FactEvidenceInput,
    InferenceEvidenceInput,
)
from hypertrade.research.graph_control import ResearchGraphControlInterrupted
from hypertrade.research.graph_tools import GraphToolContext, ResearchToolRunner
from hypertrade.research.node_runs import TaskNodeRunService
from hypertrade.research.role_provider import (
    ResearchRoleProvider,
    RoleProviderContext,
    RoleSchemaError,
)
from hypertrade.research.roles.definitions import ROLE_CATALOG, RoleDefinition
from hypertrade.research.roles.schemas import (
    CounterEvidenceDraft,
    DataGapDraft,
    EvidenceDraftBase,
    FactDraft,
    InferenceDraft,
    RoleOutput,
    RoleUsage,
    ToolObservation,
)
from hypertrade.research.schemas import StrategySpecDraft
from hypertrade.research.tool_policy import RoleToolDenied, RoleToolPolicyResolver


@dataclass(frozen=True)
class RoleExecutionResult:
    node_run_id: str
    role_key: str
    evidence_ids: tuple[str, ...]
    summary: str
    strategy_spec: dict[str, Any] | None
    usage: dict[str, int]
    replayed: bool = False

    def state_update(self) -> dict[str, Any]:
        return {
            "completed_nodes": [self.role_key],
            "evidence_ids": list(self.evidence_ids),
            "node_outputs": {
                self.role_key: {
                    "node_run_id": self.node_run_id,
                    "evidence_ids": list(self.evidence_ids),
                    "summary": self.summary,
                    "strategy_spec": self.strategy_spec,
                    "usage": dict(self.usage),
                    "replayed": self.replayed,
                }
            },
        }


class RoleExecutor:
    def __init__(
        self,
        db: Database,
        *,
        provider: ResearchRoleProvider,
        tool_runner: ResearchToolRunner,
        policy_resolver: RoleToolPolicyResolver | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tool_runner = tool_runner
        self.policy_resolver = policy_resolver or RoleToolPolicyResolver()
        self.nodes = TaskNodeRunService(db)
        self.budgets = TaskBudgetGuard(db)
        self.evidence = EvidenceService(db)
        self.provider_semaphore = BoundedSemaphore(value=2)
        self.bitpro_semaphore = BoundedSemaphore(value=1)
        self.read_tool_semaphore = BoundedSemaphore(value=2)

    async def execute(
        self,
        role_key: str,
        *,
        task_id: str,
        objective: str,
        mandate: dict[str, Any],
        job_id: str,
        prior_evidence_ids: list[str],
        depends_on: list[str],
        enabled: bool,
        disabled_reason: str = "",
        operator_tool_allowlist: set[str] | None = None,
        control_guard: Callable[[str | None], None] | None = None,
    ) -> RoleExecutionResult:
        role = ROLE_CATALOG[role_key]
        policy = self.policy_resolver.resolve(
            role, operator_allowlist=operator_tool_allowlist
        )
        start = self.nodes.start(
            task_id,
            node_key=role.key,
            role_key=role.key,
            depends_on=depends_on,
            input_ref={
                "objective_ref": f"task:{task_id}",
                "mandate_id": str(mandate.get("id", "")),
                "job_id": job_id,
                "prompt_version": role.version,
                "prompt_hash": role.prompt_hash,
                "provider": self.provider.name,
                "model": self.provider.model,
                "output_schema": "research_role_output.v1",
                "prior_evidence_ids": sorted(set(prior_evidence_ids)),
            },
            tool_policy=policy.projection(),
        )
        if start.replayed:
            output = dict(start.node.output_ref_json)
            return RoleExecutionResult(
                node_run_id=start.node.id,
                role_key=role.key,
                evidence_ids=tuple(output.get("evidence_ids", [])),
                summary=str(output.get("summary", "completed node replay")),
                strategy_spec=(
                    dict(output["strategy_spec"])
                    if isinstance(output.get("strategy_spec"), dict)
                    else None
                ),
                usage={
                    str(key): int(value)
                    for key, value in dict(start.node.usage_json).items()
                    if isinstance(value, int)
                },
                replayed=True,
            )

        try:
            self._guard(control_guard, start.node.id)
            if not enabled:
                return self._complete_disabled(
                    start.node.id,
                    task_id=task_id,
                    role=role,
                    mandate=mandate,
                    reason=disabled_reason or "optional_capability_unavailable",
                )
            context = self._provider_context(
                task_id=task_id,
                node_run_id=start.node.id,
                objective=objective,
                mandate=mandate,
            )
            plan_result = await self._provider_call(
                task_id,
                role,
                phase="plan",
                calls=1,
                token_reservation=max(1, role.budget.max_tokens // 3),
                operation=lambda: self.provider.plan(role, context, policy),
                control_guard=control_guard,
                node_run_id=start.node.id,
            )
            plan = plan_result.value
            try:
                self.policy_resolver.authorize(policy, plan.tool_calls)
            except RoleToolDenied as exc:
                TaskEventService(self.db).append(
                    task_id,
                    "research_role_tool_denied",
                    actor=f"role:{role.key}",
                    payload={
                        "node_run_id": start.node.id,
                        "tool_name": exc.tool_name,
                        "reason": exc.reason,
                    },
                )
                raise
            observations, tool_usage = await self._run_tools(
                role,
                task_id=task_id,
                node_run_id=start.node.id,
                calls=plan.tool_calls,
                context=self._tool_context(
                    task_id=task_id,
                    objective=objective,
                    mandate=mandate,
                    job_id=job_id,
                ),
                control_guard=control_guard,
            )
            automatic_gap_ids = self._record_unavailable_gaps(
                role,
                task_id=task_id,
                node_run_id=start.node.id,
                mandate=mandate,
                observations=observations,
            )
            self._guard(control_guard, start.node.id)
            synth_result = await self._provider_call(
                task_id,
                role,
                phase="synthesize",
                calls=2,
                token_reservation=max(1, role.budget.max_tokens * 2 // 3),
                operation=lambda: self.provider.synthesize(role, context, observations),
                control_guard=control_guard,
                node_run_id=start.node.id,
            )
            evidence_ids, strategy_spec = self._persist_output(
                synth_result.value,
                role=role,
                task_id=task_id,
                node_run_id=start.node.id,
                mandate=mandate,
                observations=observations,
            )
            all_evidence_ids = tuple(sorted({*automatic_gap_ids, *evidence_ids}))
            usage = _sum_usage(plan_result.usage, tool_usage, synth_result.usage)
            self._enforce_role_usage(role, usage)
            output_ref = {
                "evidence_ids": list(all_evidence_ids),
                "summary": synth_result.value.summary,
                "strategy_spec": strategy_spec,
                "provider": self.provider.name,
                "model": self.provider.model,
                "prompt_hash": role.prompt_hash,
                "tool_catalog_hash": policy.catalog_hash,
            }
            completed = self.nodes.complete(
                start.node.id,
                output_ref=output_ref,
                usage=usage.model_dump(mode="json"),
            )
            TaskCheckpointService(self.db).create(
                task_id,
                {
                    "schema_version": "research_graph_checkpoint.v1",
                    "completed_node": role.key,
                    "node_run_id": completed.id,
                    "evidence_ids": list(all_evidence_ids),
                    "strategy_spec_ref": (
                        f"node:{completed.id}:strategy_spec" if strategy_spec else ""
                    ),
                },
                node_run_id=completed.id,
            )
            return RoleExecutionResult(
                node_run_id=completed.id,
                role_key=role.key,
                evidence_ids=all_evidence_ids,
                summary=synth_result.value.summary,
                strategy_spec=strategy_spec,
                usage={
                    "model_calls": usage.model_calls,
                    "tool_calls": usage.tool_calls,
                    "tokens": usage.tokens,
                },
            )
        except ResearchGraphControlInterrupted as exc:
            current_rows = {row.id: row for row in self.nodes.list(task_id)}
            current = current_rows.get(start.node.id)
            if current is not None and current.status == "running":
                self.nodes.interrupt(
                    start.node.id,
                    status="paused" if exc.status == "paused" else "canceled",
                    reason=exc.reason,
                )
            raise
        except Exception as exc:
            current_rows = {row.id: row for row in self.nodes.list(task_id)}
            current = current_rows.get(start.node.id)
            if current is not None and current.status == "running":
                self.nodes.fail(
                    start.node.id,
                    error={
                        "code": _error_code(exc),
                        "type": type(exc).__name__,
                        "retryable": isinstance(exc, httpx.TimeoutException | TimeoutError),
                    },
                )
            raise

    async def _provider_call(
        self,
        task_id: str,
        role: RoleDefinition,
        *,
        phase: str,
        calls: int,
        token_reservation: int,
        operation: Callable[[], Any],
        control_guard: Callable[[str | None], None] | None,
        node_run_id: str,
    ) -> Any:
        self._guard(control_guard, node_run_id)
        reservation = self.budgets.reserve(
            task_id,
            role.key,
            role_budget=role.budget,
            model_calls=calls,
            tokens=token_reservation,
        )
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_with_semaphore, self.provider_semaphore, operation),
                timeout=role.budget.timeout_seconds,
            )
        except Exception:
            self.budgets.release(reservation, reason=f"{phase}_failed")
            raise
        self.budgets.settle(
            reservation,
            actual_model_calls=result.usage.model_calls,
            actual_tool_calls=0,
            actual_tokens=result.usage.tokens,
        )
        self._guard(control_guard, node_run_id)
        return result

    async def _run_tools(
        self,
        role: RoleDefinition,
        *,
        task_id: str,
        node_run_id: str,
        calls: list[Any],
        context: GraphToolContext,
        control_guard: Callable[[str | None], None] | None,
    ) -> tuple[list[ToolObservation], RoleUsage]:
        if not calls:
            return [], RoleUsage()
        reservation = self.budgets.reserve(
            task_id,
            role.key,
            role_budget=role.budget,
            tool_calls=len(calls),
        )
        observations: list[ToolObservation] = []
        try:
            for call in calls:
                self._guard(control_guard, node_run_id)
                semaphore = (
                    self.bitpro_semaphore
                    if call.name.startswith("bitpro.")
                    else self.read_tool_semaphore
                )
                observation = await asyncio.wait_for(
                    asyncio.to_thread(
                        _with_semaphore,
                        semaphore,
                        partial(self.tool_runner.run, call, context),
                    ),
                    timeout=role.budget.timeout_seconds,
                )
                observations.append(observation)
                self._guard(control_guard, node_run_id)
        except Exception:
            self.budgets.release(reservation, reason="tool_dispatch_failed")
            raise
        self.budgets.settle(
            reservation,
            actual_model_calls=0,
            actual_tool_calls=len(observations),
            actual_tokens=0,
        )
        return observations, RoleUsage(tool_calls=len(observations))

    def _persist_output(
        self,
        output: RoleOutput,
        *,
        role: RoleDefinition,
        task_id: str,
        node_run_id: str,
        mandate: dict[str, Any],
        observations: list[ToolObservation],
    ) -> tuple[list[str], dict[str, Any] | None]:
        source_map = {
            str(source.get("source_id", "")): EvidenceSourceRef.model_validate(source)
            for observation in observations
            for source in observation.sources
            if str(source.get("source_id", ""))
        }
        task_evidence = {
            row["id"]: row
            for row in self.evidence.query(task_id=task_id, limit=200)
        }
        now = utc_now()
        evidence_ids: list[str] = []
        for draft in output.evidence:
            unknown_sources = set(draft.source_ids) - set(source_map)
            if unknown_sources:
                raise RoleSchemaError(
                    f"role {role.key} referenced unobserved sources: {sorted(unknown_sources)}"
                )
            referenced = (
                set(draft.supporting_evidence_ids)
                | set(draft.opposing_evidence_ids)
                | (
                    set(draft.challenged_evidence_ids)
                    if isinstance(draft, CounterEvidenceDraft)
                    else set()
                )
            )
            unknown_evidence = referenced - set(task_evidence)
            if unknown_evidence:
                raise RoleSchemaError(
                    f"role {role.key} referenced evidence outside Task: {sorted(unknown_evidence)}"
                )
            common = {
                "claim": draft.claim,
                "scope": _scope(mandate),
                "sources": [source_map[source_id] for source_id in draft.source_ids],
                "confidence": Decimal(str(draft.confidence)),
                "as_of": now,
                "valid_until": (
                    now + timedelta(seconds=draft.valid_for_seconds)
                    if draft.valid_for_seconds
                    else None
                ),
                "task_id": task_id,
                "node_run_id": node_run_id,
                "role_key": role.key,
                "supporting_evidence_ids": draft.supporting_evidence_ids,
                "opposing_evidence_ids": draft.opposing_evidence_ids,
            }
            payload = _evidence_input(draft, common)
            stored = self.evidence.append(payload, actor=f"role_executor:{role.key}")
            evidence_ids.append(str(stored["id"]))
            task_evidence[str(stored["id"])] = stored
        strategy_spec = self._strategy_spec(output, role=role, mandate=mandate)
        return evidence_ids, strategy_spec

    def _record_unavailable_gaps(
        self,
        role: RoleDefinition,
        *,
        task_id: str,
        node_run_id: str,
        mandate: dict[str, Any],
        observations: list[ToolObservation],
    ) -> list[str]:
        ids: list[str] = []
        for observation in observations:
            if observation.available:
                continue
            stored = self.evidence.append(
                DataGapEvidenceInput(
                    claim=f"{role.key} source unavailable: {observation.tool_name}",
                    scope=_scope(mandate),
                    confidence=Decimal("0"),
                    as_of=utc_now(),
                    task_id=task_id,
                    node_run_id=node_run_id,
                    role_key=role.key,
                    expected_sources=["tool"],
                    remediation=(
                        f"Restore {observation.tool_name} ({observation.error_code}) and rerun "
                        "this node."
                    ),
                ),
                actor=f"role_executor:{role.key}",
            )
            ids.append(str(stored["id"]))
        return ids

    def _complete_disabled(
        self,
        node_run_id: str,
        *,
        task_id: str,
        role: RoleDefinition,
        mandate: dict[str, Any],
        reason: str,
    ) -> RoleExecutionResult:
        stored = self.evidence.append(
            DataGapEvidenceInput(
                claim=f"Optional research role unavailable: {role.key}",
                scope=_scope(mandate),
                confidence=Decimal("0"),
                as_of=utc_now(),
                task_id=task_id,
                node_run_id=node_run_id,
                role_key=role.key,
                expected_sources=["tool"],
                remediation=f"Enable the required capability and rerun {role.key}: {reason}",
            ),
            actor=f"role_selector:{role.key}",
        )
        output = {
            "evidence_ids": [stored["id"]],
            "summary": f"{role.key} skipped with explicit data gap: {reason}",
            "strategy_spec": None,
            "provider": self.provider.name,
            "model": self.provider.model,
            "prompt_hash": role.prompt_hash,
        }
        node = self.nodes.complete(node_run_id, output_ref=output, usage={})
        TaskCheckpointService(self.db).create(
            task_id,
            {
                "schema_version": "research_graph_checkpoint.v1",
                "completed_node": role.key,
                "node_run_id": node.id,
                "evidence_ids": [stored["id"]],
                "optional_data_gap": True,
            },
            node_run_id=node.id,
        )
        return RoleExecutionResult(
            node_run_id=node.id,
            role_key=role.key,
            evidence_ids=(str(stored["id"]),),
            summary=str(output["summary"]),
            strategy_spec=None,
            usage={},
        )

    def _provider_context(
        self,
        *,
        task_id: str,
        node_run_id: str,
        objective: str,
        mandate: dict[str, Any],
    ) -> RoleProviderContext:
        evidence = tuple(
            {
                "id": row["id"],
                "type": row["evidence_type"],
                "status": row["status"],
                "claim": str(row["claim"])[:1_000],
                "confidence": row["confidence"],
            }
            for row in self.evidence.query(task_id=task_id, limit=200)
        )
        return RoleProviderContext(
            task_id=task_id,
            node_run_id=node_run_id,
            objective=objective,
            mandate=dict(mandate),
            evidence=evidence,
        )

    @staticmethod
    def _tool_context(
        *, task_id: str, objective: str, mandate: dict[str, Any], job_id: str
    ) -> GraphToolContext:
        strategy_spec = mandate.get("strategy_spec")
        spec = dict(strategy_spec) if isinstance(strategy_spec, dict) else {}
        return GraphToolContext(
            task_id=task_id,
            mandate_id=str(mandate.get("id", "")),
            job_id=job_id,
            objective=objective,
            symbols=tuple(str(item) for item in mandate.get("symbols", [])),
            timeframes=tuple(str(item) for item in mandate.get("timeframes", [])),
            strategy_key=str(spec.get("strategy_key", "")),
        )

    @staticmethod
    def _strategy_spec(
        output: RoleOutput, *, role: RoleDefinition, mandate: dict[str, Any]
    ) -> dict[str, Any] | None:
        if output.strategy_spec is None:
            if role.key == "strategy_engineer" and any(
                not isinstance(item, DataGapDraft) for item in output.evidence
            ):
                raise RoleSchemaError("strategy_engineer non-gap output requires strategy_spec")
            return None
        if role.key != "strategy_engineer":
            raise RoleSchemaError(f"role {role.key} cannot emit strategy_spec")
        spec = StrategySpecDraft.model_validate(output.strategy_spec)
        if spec.mandate_id != str(mandate.get("id", "")):
            raise RoleSchemaError("strategy_spec mandate_id mismatch")
        return spec.model_dump(mode="json")

    @staticmethod
    def _enforce_role_usage(role: RoleDefinition, usage: RoleUsage) -> None:
        if usage.model_calls > role.budget.max_model_calls:
            raise RoleSchemaError(f"role model-call budget exceeded: {role.key}")
        if usage.tool_calls > role.budget.max_tool_calls:
            raise RoleSchemaError(f"role tool-call budget exceeded: {role.key}")
        if usage.tokens > role.budget.max_tokens:
            raise RoleSchemaError(f"role token budget exceeded: {role.key}")

    @staticmethod
    def _guard(
        control_guard: Callable[[str | None], None] | None,
        node_run_id: str | None,
    ) -> None:
        if control_guard is not None:
            control_guard(node_run_id)


def _evidence_input(draft: EvidenceDraftBase, common: dict[str, Any]) -> Any:
    if isinstance(draft, FactDraft):
        return FactEvidenceInput(**common)
    if isinstance(draft, InferenceDraft):
        return InferenceEvidenceInput(
            **common,
            inference_method=draft.inference_method,
        )
    if isinstance(draft, CounterEvidenceDraft):
        return CounterEvidenceInput(
            **common,
            challenged_evidence_ids=draft.challenged_evidence_ids,
            rationale=draft.rationale,
        )
    if isinstance(draft, DataGapDraft):
        return DataGapEvidenceInput(
            **common,
            expected_sources=draft.expected_sources,
            remediation=draft.remediation,
        )
    raise TypeError(type(draft).__name__)


def _scope(mandate: dict[str, Any]) -> EvidenceScope:
    strategy_spec = mandate.get("strategy_spec")
    spec = dict(strategy_spec) if isinstance(strategy_spec, dict) else {}
    return EvidenceScope(
        symbols=list(mandate.get("symbols", [])),
        timeframes=list(mandate.get("timeframes", [])),
        market_type=str(mandate.get("market_type", "")),
        mandate_id=str(mandate.get("id", "")),
        strategy_key=str(spec.get("strategy_key", "")),
    )


def _sum_usage(*items: RoleUsage) -> RoleUsage:
    return RoleUsage(
        model_calls=sum(item.model_calls for item in items),
        tool_calls=sum(item.tool_calls for item in items),
        tokens=sum(item.tokens for item in items),
    )


def _error_code(exc: Exception) -> str:
    if isinstance(exc, RoleToolDenied):
        return "role_tool_denied"
    if isinstance(exc, RoleSchemaError):
        return "role_schema_invalid"
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "role_timeout"
    return "role_execution_failed"


def _with_semaphore(semaphore: BoundedSemaphore, operation: Callable[[], Any]) -> Any:
    with semaphore:
        return operation()
