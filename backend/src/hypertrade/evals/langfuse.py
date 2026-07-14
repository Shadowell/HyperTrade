"""Optional, metadata-only Langfuse export for completed Agent runs.

The Flight Recorder remains the audit system of record. This adapter mirrors a
small operational projection only when an operator explicitly configures a
self-hosted Langfuse project. It never exports prompts, completions, tool
arguments, credentials, private reasoning, or raw tool payloads.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Protocol

from hypertrade.config import Settings


class AgentRunForExport(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def run_state_json(self) -> dict[str, Any]: ...

    @property
    def trace_events(self) -> list[Any]: ...


@dataclass(frozen=True)
class LangfuseExportResult:
    status: str
    event_count: int = 0

    def as_dict(self) -> dict[str, str | int]:
        return {
            "provider": "langfuse",
            "status": self.status,
            "event_count": self.event_count,
            "payload_mode": "metadata_only",
            "prompts_exported": 0,
            "tool_arguments_exported": 0,
            "private_reasoning_exported": 0,
        }


class LangfuseTraceExporter:
    """Best-effort bridge to Langfuse; export failures never fail an Agent run."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def export(self, run: AgentRunForExport) -> LangfuseExportResult:
        configuration = self._configuration_status()
        if configuration is not None:
            return LangfuseExportResult(status=configuration)

        try:
            module: Any = importlib.import_module("langfuse")
            client_factory: Any = module.Langfuse
        except (ImportError, AttributeError):
            return LangfuseExportResult(status="sdk_unavailable")

        try:
            node_runs = _node_runs(run)
            client: Any = client_factory(
                public_key=self.settings.langfuse_public_key,
                secret_key=self.settings.langfuse_secret_key,
                base_url=self.settings.langfuse_base_url,
            )
            with client.start_as_current_observation(
                as_type="span",
                name="hypertrade.agent.run",
            ) as root_span:
                root_span.update(metadata=_run_metadata(run))
                for event in run.trace_events:
                    with client.start_as_current_observation(
                        as_type="span",
                        name=_event_name(event),
                    ) as event_span:
                        event_span.update(metadata=_event_metadata(event))
                for node in node_runs:
                    with client.start_as_current_observation(
                        as_type="span",
                        name=f"hypertrade.research.node.{_node_key(node)}",
                    ) as node_span:
                        node_span.update(metadata=_node_metadata(node))
            client.flush()
        except Exception:  # noqa: BLE001 - observability must not alter run outcome
            return LangfuseExportResult(status="failed")
        return LangfuseExportResult(
            status="exported",
            event_count=len(run.trace_events) + len(node_runs),
        )

    def _configuration_status(self) -> str | None:
        if not self.settings.langfuse_enabled:
            return "disabled"
        if not (
            self.settings.langfuse_public_key
            and self.settings.langfuse_secret_key
            and self.settings.langfuse_base_url
        ):
            return "not_configured"
        return None


def _run_metadata(run: AgentRunForExport) -> dict[str, Any]:
    state = _dict(run.run_state_json)
    observability = _dict(state.get("observability"))
    usage = _dict(observability.get("usage"))
    return {
        "run_id": run.id,
        "status": run.status,
        "execution_mode": str(state.get("execution_mode", "standard")),
        "provider": str(observability.get("provider", "")),
        "model": str(observability.get("model", "")),
        "duration_ms": _number(observability.get("duration_ms")),
        "model_request_count": _integer(usage.get("request_count")),
        "total_tokens": _integer(usage.get("total_tokens")),
        "payload_mode": "metadata_only",
        "prompts_exported": False,
        "tool_arguments_exported": False,
        "private_reasoning_exported": False,
    }


def _event_name(event: Any) -> str:
    tool_name = str(getattr(event, "tool_name", "event") or "event")
    return f"hypertrade.{tool_name.replace('.', '_')}"


def _event_metadata(event: Any) -> dict[str, Any]:
    output = _dict(getattr(event, "output_json", {}))
    policy = _dict(output.get("policy"))
    usage = _dict(output.get("usage"))
    return {
        "event_id": str(getattr(event, "id", "")),
        "event_name": str(getattr(event, "tool_name", "")),
        "status": str(output.get("execution_status") or getattr(event, "status", "")),
        "duration_ms": _number(output.get("duration_ms", output.get("execution_ms"))),
        "policy_scope": str(policy.get("scope", "")),
        "policy_outcome": str(output.get("policy_outcome", "")),
        "source_of_truth": str(policy.get("source_of_truth", "")),
        "tool_call_count": _integer(output.get("tool_call_count")),
        "total_tokens": _integer(usage.get("total_tokens")),
        "payload_mode": "metadata_only",
    }


def _node_runs(run: AgentRunForExport) -> list[Any]:
    value = getattr(run, "node_runs", [])
    return list(value) if isinstance(value, list | tuple) else []


def _node_key(node: Any) -> str:
    return str(getattr(node, "node_key", "unknown") or "unknown").replace(".", "_")[:80]


def _node_metadata(node: Any) -> dict[str, Any]:
    usage = _dict(getattr(node, "usage_json", {}))
    error = _dict(getattr(node, "error_json", {}))
    return {
        "node_run_id": str(getattr(node, "id", "")),
        "task_id": str(getattr(node, "task_id", "")),
        "node_key": str(getattr(node, "node_key", "")),
        "role_key": str(getattr(node, "role_key", "")),
        "attempt": _integer(getattr(node, "attempt", 0)),
        "status": str(getattr(node, "status", "")),
        "error_code": str(error.get("code", "")),
        "model_calls": _integer(usage.get("model_calls")),
        "tool_calls": _integer(usage.get("tool_calls")),
        "backtests": _integer(usage.get("backtests")),
        "total_tokens": _integer(usage.get("tokens", usage.get("total_tokens"))),
        "payload_mode": "metadata_only",
        "prompts_exported": False,
        "tool_arguments_exported": False,
        "raw_outputs_exported": False,
        "private_reasoning_exported": False,
    }


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if not isinstance(value, str):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return max(0.0, round(float(value), 3))
    if not isinstance(value, str):
        return 0.0
    try:
        return max(0.0, round(float(value), 3))
    except (TypeError, ValueError):
        return 0.0
