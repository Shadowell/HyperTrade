"""UI-independent state, cursor, and reconnect models for the TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class WorkbenchClient(Protocol):
    def list_agent_sessions(self) -> list[dict[str, Any]]: ...

    def create_agent_session(self, title: str) -> dict[str, Any]: ...

    def list_agent_tasks(self) -> list[dict[str, Any]]: ...

    def create_agent_task(
        self, session_id: str, objective: str, *, kind: str = "chat_run"
    ) -> dict[str, Any]: ...

    def get_agent_task(self, task_id: str) -> dict[str, Any]: ...

    def list_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]: ...

    def stream_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> Any: ...

    def get_research_graph(self, task_id: str) -> dict[str, Any]: ...

    def list_experiment_manifests(self) -> list[dict[str, Any]]: ...

    def list_robustness_validations(self) -> list[dict[str, Any]]: ...

    def list_paper_promotions(self) -> list[dict[str, Any]]: ...

    def list_research_triggers(self) -> dict[str, Any]: ...

    def list_research_trigger_fires(self, trigger_id: str = "") -> list[dict[str, Any]]: ...

    def set_research_trigger_enabled(
        self, trigger_id: str, *, enabled: bool, reason: str
    ) -> dict[str, Any]: ...

    def set_research_trigger_control(
        self, *, kill_switch: bool, reason: str
    ) -> dict[str, Any]: ...

    def fire_research_trigger(
        self, trigger_id: str, *, reason: str = "operator_run_now"
    ) -> dict[str, Any]: ...

    def list_memory_assertions(self) -> list[dict[str, Any]]: ...

    def review_memory_assertion(
        self, assertion_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]: ...

    def list_skill_proposals(self) -> list[dict[str, Any]]: ...

    def list_skill_releases(self) -> list[dict[str, Any]]: ...

    def decide_skill_proposal(
        self, proposal_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]: ...

    def control_agent_task(
        self, task_id: str, action: str, *, reason: str
    ) -> dict[str, Any]: ...


TERMINAL_OR_IDLE_STATUSES = frozenset(
    {"completed", "failed", "canceled", "paused", "retry_wait"}
)


@dataclass
class TaskEventCursor:
    """Maintain a monotonic SSE high-water mark and surface sequence gaps."""

    after: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[tuple[int, int]] = field(default_factory=list)

    def consume(self, event: dict[str, Any]) -> bool:
        sequence = event.get("sequence")
        if not isinstance(sequence, int):
            return False
        if sequence <= self.after:
            return False
        if sequence > self.after + 1:
            self.gaps.append((self.after + 1, sequence - 1))
        self.after = sequence
        self.events.append(dict(event))
        if len(self.events) > 500:
            self.events = self.events[-500:]
        return True

    @property
    def needs_snapshot_refresh(self) -> bool:
        return bool(self.gaps)


@dataclass
class WorkbenchState:
    sessions: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    selected_session_id: str = ""
    selected_task_id: str = ""
    selected_task: dict[str, Any] = field(default_factory=dict)
    graph: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    experiments: list[dict[str, Any]] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    trigger_projection: dict[str, Any] = field(default_factory=dict)
    trigger_fires: list[dict[str, Any]] = field(default_factory=list)
    memory_assertions: list[dict[str, Any]] = field(default_factory=list)
    skill_proposals: list[dict[str, Any]] = field(default_factory=list)
    skill_releases: list[dict[str, Any]] = field(default_factory=list)
    cursor: TaskEventCursor = field(default_factory=TaskEventCursor)
    connection_status: str = "snapshot"
    last_error: str = ""


class WorkbenchStore:
    """Read models from public contracts; no trading/business logic lives here."""

    def __init__(self, client: WorkbenchClient, *, initial_session_id: str = "") -> None:
        self.client = client
        self.state = WorkbenchState(selected_session_id=initial_session_id)

    def refresh_index(self) -> WorkbenchState:
        self.state.sessions = self.client.list_agent_sessions()
        self.state.tasks = self.client.list_agent_tasks()
        self.state.trigger_projection = self.client.list_research_triggers()
        self.state.trigger_fires = self.client.list_research_trigger_fires()
        self.state.memory_assertions = self.client.list_memory_assertions()
        self.state.skill_proposals = self.client.list_skill_proposals()
        self.state.skill_releases = self.client.list_skill_releases()
        if self.state.selected_session_id and not any(
            str(item.get("id", "")) == self.state.selected_session_id
            for item in self.state.sessions
        ):
            self.state.selected_session_id = ""
        if not self.state.selected_task_id and self.state.tasks:
            preferred = [
                task
                for task in self.state.tasks
                if not self.state.selected_session_id
                or str(task.get("session_id", "")) == self.state.selected_session_id
            ]
            if preferred:
                self.state.selected_task_id = str(preferred[0].get("id", ""))
        return self.state

    def select_task(self, task_id: str) -> WorkbenchState:
        if task_id != self.state.selected_task_id:
            self.state.cursor = TaskEventCursor()
        self.state.selected_task_id = task_id
        self.state.selected_task = self.client.get_agent_task(task_id)
        self.state.selected_session_id = str(self.state.selected_task.get("session_id", ""))
        self.state.graph = {}
        self.state.evidence = []
        if self.state.selected_task.get("kind") == "research_graph":
            self.state.graph = self.client.get_research_graph(task_id)
            raw_evidence = self.state.graph.get("evidence", [])
            self.state.evidence = [
                dict(item) for item in raw_evidence if isinstance(item, dict)
            ]
        self.state.experiments = self.client.list_experiment_manifests()
        self.state.validations = self.client.list_robustness_validations()
        self.state.approvals = self.client.list_paper_promotions()
        self.reconcile_events()
        self.state.connection_status = "snapshot"
        self.state.last_error = ""
        return self.state

    def reconcile_events(self) -> int:
        task_id = self.state.selected_task_id
        if not task_id:
            return 0
        accepted = 0
        for event in self.client.list_agent_task_events(
            task_id,
            after=self.state.cursor.after,
        ):
            accepted += int(self.state.cursor.consume(event))
        return accepted

    def apply_stream_event(self, event: dict[str, Any]) -> bool:
        accepted = self.state.cursor.consume(event)
        if accepted:
            self.state.connection_status = "live"
        return accepted

    def mark_disconnected(self, exc: BaseException) -> None:
        self.state.connection_status = "reconnecting"
        self.state.last_error = type(exc).__name__

    def refresh_after_disconnect(self) -> WorkbenchState:
        task_id = self.state.selected_task_id
        if not task_id:
            return self.state
        self.reconcile_events()
        # A REST snapshot is authoritative after a cursor gap or terminal SSE.
        self.state.selected_task = self.client.get_agent_task(task_id)
        self.state.connection_status = "snapshot"
        return self.state

    def create_task(self, objective: str) -> dict[str, Any]:
        normalized = objective.strip()
        if not normalized:
            raise ValueError("Task objective is required")
        session = self.client.create_agent_session(normalized[:120])
        task = self.client.create_agent_task(str(session["id"]), normalized)
        self.refresh_index()
        self.select_task(str(task["id"]))
        return task

    def control_selected(self, action: str, reason: str) -> dict[str, Any]:
        if not self.state.selected_task_id:
            raise ValueError("Select a task first")
        normalized = reason.strip()
        if not normalized:
            raise ValueError("Operator reason is required")
        result = self.client.control_agent_task(
            self.state.selected_task_id,
            action,
            reason=normalized,
        )
        self.state.selected_task = dict(result)
        self.reconcile_events()
        return result

    def control_trigger(
        self,
        action: str,
        *,
        trigger_id: str,
        reason: str,
    ) -> dict[str, Any]:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("Operator reason is required")
        if action in {"enable", "disable"}:
            if not trigger_id:
                raise ValueError("Trigger ID is required")
            result = self.client.set_research_trigger_enabled(
                trigger_id,
                enabled=action == "enable",
                reason=normalized_reason,
            )
        elif action == "run":
            if not trigger_id:
                raise ValueError("Trigger ID is required")
            result = self.client.fire_research_trigger(
                trigger_id,
                reason=normalized_reason,
            )
        elif action in {"kill_on", "kill_off"}:
            result = self.client.set_research_trigger_control(
                kill_switch=action == "kill_on",
                reason=normalized_reason,
            )
        else:
            raise ValueError(f"Unsupported trigger action: {action}")
        self.state.trigger_projection = self.client.list_research_triggers()
        self.state.trigger_fires = self.client.list_research_trigger_fires()
        return result

    def review_governance(
        self,
        resource_kind: str,
        action: str,
        *,
        resource_id: str,
        reason: str,
    ) -> dict[str, Any]:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("Operator reason is required")
        if not resource_id:
            raise ValueError("Governance resource ID is required")
        if resource_kind == "assertion" and action in {"approve", "reject", "dispute"}:
            result = self.client.review_memory_assertion(
                resource_id,
                decision=action,
                reason=normalized_reason,
            )
        elif resource_kind == "skill" and action in {"approve", "reject"}:
            result = self.client.decide_skill_proposal(
                resource_id,
                decision=action,
                reason=normalized_reason,
            )
        else:
            raise ValueError(f"Unsupported governance action: {resource_kind}:{action}")
        self.state.memory_assertions = self.client.list_memory_assertions()
        self.state.skill_proposals = self.client.list_skill_proposals()
        self.state.skill_releases = self.client.list_skill_releases()
        return result

    @property
    def selected_is_terminal_or_idle(self) -> bool:
        return str(self.state.selected_task.get("status", "")) in TERMINAL_OR_IDLE_STATUSES
