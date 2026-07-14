"""Textual operator workbench over HyperTrade's REST/SSE control plane."""

from __future__ import annotations

import json
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from hypertrade.tui.models import WorkbenchClient, WorkbenchState, WorkbenchStore


class TaskListItem(ListItem):
    def __init__(self, task: dict[str, Any]) -> None:
        self.task_id = str(task.get("id", ""))
        status = str(task.get("status", "unknown"))
        kind = str(task.get("kind", "task"))
        objective = str(task.get("objective", "")).replace("\n", " ")[:42]
        super().__init__(Label(f"{status.upper():<17} {kind}\n{objective}", markup=False))


class ControlConfirmScreen(ModalScreen[str | None]):
    """Require an operator reason before requesting a server-side transition."""

    DEFAULT_CSS = """
    ControlConfirmScreen { align: center middle; background: rgba(0, 8, 6, 0.75); }
    #control-dialog {
        width: 64; height: 14; border: solid #d7a83d;
        background: #07110e; padding: 1 2;
    }
    #control-dialog Input { margin-top: 1; }
    #control-buttons { height: 3; margin-top: 1; align-horizontal: right; }
    #control-buttons Button { margin-left: 1; }
    """

    def __init__(self, action: str, task_id: str) -> None:
        super().__init__()
        self.action_name = action
        self.task_id = task_id

    def compose(self) -> ComposeResult:
        with Vertical(id="control-dialog"):
            yield Label(
                f"REQUEST {self.action_name.upper()}\n{self.task_id}\n"
                "Server auth, idempotency and task state remain authoritative.",
                markup=False,
            )
            yield Input(placeholder="Required operator reason", id="control-reason")
            with Horizontal(id="control-buttons"):
                yield Button("Cancel", id="control-cancel")
                yield Button("Submit request", variant="warning", id="control-submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "control-cancel":
            self.dismiss(None)
            return
        reason = self.query_one("#control-reason", Input).value.strip()
        if not reason:
            self.notify("Operator reason is required", severity="error")
            return
        self.dismiss(reason)


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; background: rgba(0, 8, 6, 0.75); }
    #help-dialog {
        width: 72; height: 24; border: solid #50dbc1;
        background: #07110e; padding: 1 2;
    }
    #help-close { margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(
                "KEYBOARD\n\n"
                "Ctrl+N  focus new-task prompt\n"
                "Ctrl+P  request pause\n"
                "Ctrl+R  request resume/retry based on status\n"
                "Ctrl+C  request cancel\n"
                "R       refresh REST snapshot\n"
                "G/E/A   graph, evidence, approval focus\n"
                "?       help\n"
                "Q       quit\n\n"
                "Every mutation requires a reason and is revalidated by the server.",
                markup=False,
            )
            yield Button("Close", id="help-close", variant="primary")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        self.dismiss(None)


class ResearchWorkbenchApp(App[None]):
    """Read-mostly TUI; server APIs remain the only control authority."""

    TITLE = "HyperTrade Research Workbench"
    SUB_TITLE = "durable tasks · evidence · validation · approvals"
    BINDINGS = [
        Binding("ctrl+n", "new_task", "New task", priority=True),
        Binding("ctrl+p", "pause", "Pause", priority=True),
        Binding("ctrl+r", "resume_or_retry", "Resume/Retry", priority=True),
        Binding("ctrl+c", "cancel_task", "Cancel task", priority=True),
        ("r", "refresh", "Refresh"),
        ("g", "graph", "Graph"),
        ("e", "evidence", "Evidence"),
        ("a", "approval", "Approval"),
        ("question_mark", "help", "Help"),
        ("q", "quit", "Quit"),
    ]

    CSS = """
    Screen { background: #030b09; color: #d9e4df; }
    Header, Footer { background: #07110e; color: #7debd6; }
    #metric-strip { height: 5; padding: 0 1; }
    .metric {
        width: 1fr; border: solid #18352e; background: #07110e;
        padding: 0 1; margin-right: 1;
    }
    #workspace { height: 1fr; padding: 0 1; }
    .pane { border: solid #18352e; background: #06100d; padding: 0 1; margin-right: 1; }
    .pane-title { height: 2; color: #64ddc5; text-style: bold; }
    #sessions-pane { width: 31; }
    #center-pane { width: 1fr; }
    #evidence-pane { width: 38; margin-right: 0; }
    #task-list { height: 1fr; }
    TaskListItem { height: 4; padding: 0 1; border-bottom: solid #10251f; }
    TaskListItem.--highlight { background: #103127; color: #8ff5df; }
    #graph-view { height: 2fr; overflow-y: auto; }
    #timeline-view { height: 1fr; border-top: solid #18352e; overflow-y: auto; }
    #evidence-view { height: 1fr; overflow-y: auto; }
    #detail-tabs { height: 18; margin: 0 1; border: solid #18352e; }
    .detail { padding: 0 1; overflow-y: auto; }
    #prompt-row { height: 7; margin: 0 1 1 1; }
    #task-prompt { width: 1fr; border: solid #285348; }
    #start-task { width: 18; height: 3; margin: 1; }
    .medium #evidence-pane { display: none; }
    .compact #sessions-pane, .compact #evidence-pane { display: none; }
    .compact #detail-tabs { height: 14; }
    .compact #prompt-row { height: 6; }
    """

    def __init__(self, *, client: WorkbenchClient, initial_session_id: str = "") -> None:
        super().__init__()
        self.client = client
        self.store = WorkbenchStore(client, initial_session_id=initial_session_id)
        self._stream_task_id = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="metric-strip"):
            for metric_id in ("tasks", "running", "review", "failed", "budget"):
                yield Static("—", id=f"metric-{metric_id}", classes="metric", markup=False)
        with Horizontal(id="workspace"):
            with Vertical(id="sessions-pane", classes="pane"):
                yield Static("SESSIONS / TASKS", classes="pane-title", markup=False)
                yield ListView(id="task-list")
            with Vertical(id="center-pane", classes="pane"):
                yield Static("RESEARCH GRAPH", classes="pane-title", markup=False)
                yield Static("Select a task", id="graph-view", markup=False)
                yield Static("TIMELINE", classes="pane-title", markup=False)
                yield Static("No events", id="timeline-view", markup=False)
            with Vertical(id="evidence-pane", classes="pane"):
                yield Static("EVIDENCE / GAPS", classes="pane-title", markup=False)
                yield Static("No evidence", id="evidence-view", markup=False)
        with TabbedContent(id="detail-tabs"):
            with TabPane("Task", id="tab-task"):
                yield Static("No task", id="task-detail", classes="detail", markup=False)
            with TabPane("Experiment", id="tab-experiment"):
                yield Static(
                    "No experiment", id="experiment-detail", classes="detail", markup=False
                )
            with TabPane("Validation", id="tab-validation"):
                yield Static(
                    "No validation", id="validation-detail", classes="detail", markup=False
                )
            with TabPane("Approval", id="tab-approval"):
                yield Static("No approval", id="approval-detail", classes="detail", markup=False)
        with Horizontal(id="prompt-row"):
            yield TextArea(
                "",
                id="task-prompt",
                soft_wrap=True,
                placeholder="New bounded research/chat task objective (Ctrl+N)",
            )
            yield Button("Create task", id="start-task", variant="primary")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_snapshot()
        self.set_interval(15.0, self.action_refresh)

    def on_resize(self, event: Resize) -> None:
        self.remove_class("compact", "medium")
        if event.size.width < 100:
            self.add_class("compact")
        elif event.size.width < 145:
            self.add_class("medium")

    async def refresh_snapshot(self) -> None:
        try:
            state = self.store.refresh_index()
            if state.selected_task_id:
                state = self.store.select_task(state.selected_task_id)
            await self._render_state(state)
            if state.selected_task_id:
                self.follow_task_stream(state.selected_task_id)
        except Exception as exc:
            self.store.mark_disconnected(exc)
            self.notify(f"Snapshot failed: {type(exc).__name__}", severity="error")
            await self._render_state(self.store.state)

    async def _render_state(self, state: WorkbenchState) -> None:
        tasks = state.tasks
        running = sum(str(item.get("status")) == "running" for item in tasks)
        review = sum(str(item.get("status")) == "awaiting_approval" for item in tasks)
        failed = sum(str(item.get("status")) == "failed" for item in tasks)
        self.query_one("#metric-tasks", Static).update(f"TASKS\n{len(tasks)}")
        self.query_one("#metric-running", Static).update(f"RUNNING\n{running}")
        self.query_one("#metric-review", Static).update(f"REVIEW\n{review}")
        self.query_one("#metric-failed", Static).update(f"FAILED\n{failed}")
        self.query_one("#metric-budget", Static).update(self._budget_metric(state.selected_task))

        task_list = self.query_one("#task-list", ListView)
        await task_list.clear()
        for task in tasks[:100]:
            await task_list.append(TaskListItem(task))
        self.query_one("#graph-view", Static).update(self._graph_text(state))
        self.query_one("#timeline-view", Static).update(self._timeline_text(state))
        self.query_one("#evidence-view", Static).update(self._evidence_text(state))
        self.query_one("#task-detail", Static).update(self._task_text(state))
        self.query_one("#experiment-detail", Static).update(
            self._records_text(state.experiments, "fingerprint", "status")
        )
        self.query_one("#validation-detail", Static).update(
            self._records_text(state.validations, "id", "final_status")
        )
        self.query_one("#approval-detail", Static).update(
            self._records_text(state.approvals, "id", "status")
        )

    @work(thread=True, exclusive=True, group="task-stream")
    def follow_task_stream(self, task_id: str) -> None:
        self._stream_task_id = task_id
        try:
            for event in self.client.stream_agent_task_events(
                task_id,
                after=self.store.state.cursor.after,
            ):
                if task_id != self._stream_task_id:
                    return
                self.call_from_thread(self._accept_stream_event, task_id, dict(event))
        except Exception as exc:
            self.call_from_thread(self._stream_disconnected, task_id, exc)
            return
        self.call_from_thread(self._stream_finished, task_id)

    def _accept_stream_event(self, task_id: str, event: dict[str, Any]) -> None:
        if task_id != self.store.state.selected_task_id:
            return
        if self.store.apply_stream_event(event):
            self.query_one("#timeline-view", Static).update(self._timeline_text(self.store.state))
            if self.store.state.cursor.needs_snapshot_refresh:
                self._refresh_after_stream(task_id)

    def _stream_disconnected(self, task_id: str, exc: BaseException) -> None:
        if task_id != self.store.state.selected_task_id:
            return
        self.store.mark_disconnected(exc)
        self.query_one("#timeline-view", Static).update(self._timeline_text(self.store.state))
        self.notify("Task stream disconnected; reconciling from cursor", severity="warning")
        self._refresh_after_stream(task_id)

    def _stream_finished(self, task_id: str) -> None:
        if task_id == self.store.state.selected_task_id:
            self._refresh_after_stream(task_id)

    @work(thread=True, exclusive=True, group="snapshot-reconcile")
    def _refresh_after_stream(self, task_id: str) -> None:
        try:
            state = self.store.refresh_after_disconnect()
        except Exception as exc:
            self.call_from_thread(self.store.mark_disconnected, exc)
            self.call_from_thread(
                self.set_timer,
                1.0,
                lambda: self.follow_task_stream(task_id),
            )
            return
        self.call_from_thread(self._reconciled, task_id, state)

    def _reconciled(self, task_id: str, state: WorkbenchState) -> None:
        if task_id != self.store.state.selected_task_id:
            return
        self.call_later(self._render_state, state)
        status = str(state.selected_task.get("status", ""))
        if status not in {"completed", "failed", "canceled", "paused", "retry_wait"}:
            self.set_timer(1.0, lambda: self.follow_task_stream(task_id))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not isinstance(event.item, TaskListItem):
            return
        try:
            state = self.store.select_task(event.item.task_id)
        except Exception as exc:
            self.notify(f"Task load failed: {type(exc).__name__}", severity="error")
            return
        await self._render_state(state)
        self.follow_task_stream(event.item.task_id)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "start-task":
            return
        prompt = self.query_one("#task-prompt", TextArea).text.strip()
        try:
            task = self.store.create_task(prompt)
        except Exception as exc:
            self.notify(f"Task creation failed: {type(exc).__name__}", severity="error")
            return
        self.query_one("#task-prompt", TextArea).clear()
        await self._render_state(self.store.state)
        self.follow_task_stream(str(task["id"]))

    def action_new_task(self) -> None:
        self.query_one("#task-prompt", TextArea).focus()

    async def action_refresh(self) -> None:
        await self.refresh_snapshot()

    def action_pause(self) -> None:
        self._request_control("pause")

    def action_resume_or_retry(self) -> None:
        status = str(self.store.state.selected_task.get("status", ""))
        if status == "paused":
            self._request_control("resume")
        elif status in {"failed", "retry_wait"}:
            self._request_control("retry")
        else:
            self.notify(
                "Resume/retry is not valid for the current server status",
                severity="warning",
            )

    def action_cancel_task(self) -> None:
        self._request_control("cancel")

    def _request_control(self, action: str) -> None:
        task_id = self.store.state.selected_task_id
        if not task_id:
            self.notify("Select a task first", severity="warning")
            return
        self.push_screen(
            ControlConfirmScreen(action, task_id),
            lambda reason: self._apply_control(action, reason),
        )

    def _apply_control(self, action: str, reason: str | None) -> None:
        if reason is None:
            return
        try:
            result = self.store.control_selected(action, reason)
        except Exception as exc:
            self.notify(f"Control rejected: {type(exc).__name__}", severity="error")
            return
        self.notify(f"{action} accepted: {result.get('status', 'unknown')}")
        self.call_later(self._render_state, self.store.state)

    def action_graph(self) -> None:
        self.query_one("#graph-view", Static).focus()

    def action_evidence(self) -> None:
        self.query_one("#evidence-view", Static).focus()

    def action_approval(self) -> None:
        self.query_one("#detail-tabs", TabbedContent).active = "tab-approval"

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    @staticmethod
    def _budget_metric(task: dict[str, Any]) -> str:
        raw_usage = task.get("usage")
        raw_budget = task.get("budget")
        usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
        budget = dict(raw_budget) if isinstance(raw_budget, dict) else {}
        used = int(usage.get("tokens", 0) or 0)
        limit = int(budget.get("max_tokens", 0) or 0)
        percent = round(used / limit * 100) if limit else 0
        return f"TOKEN CAPACITY\n{used:,}/{limit:,} ({percent}%)"

    @staticmethod
    def _graph_text(state: WorkbenchState) -> str:
        if not state.selected_task:
            return "Select a task"
        nodes = state.graph.get("nodes", []) if state.graph else []
        if not nodes:
            return (
                f"{state.selected_task.get('kind')} · {state.selected_task.get('status')}\n"
                "No Research Graph nodes for this task."
            )
        lines = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            lines.append(
                f"{str(node.get('status', '')).upper():<12} "
                f"{node.get('node_key', '')} · {node.get('role_key', '')} "
                f"attempt {node.get('attempt', 0)}"
            )
        return "\n".join(lines) or "No graph nodes"

    @staticmethod
    def _timeline_text(state: WorkbenchState) -> str:
        prefix = (
            f"connection={state.connection_status} cursor={state.cursor.after}"
            f" gaps={len(state.cursor.gaps)}"
        )
        if state.last_error:
            prefix += f" last_error={state.last_error}"
        lines = [prefix]
        for event in state.cursor.events[-30:]:
            lines.append(
                f"{int(event.get('sequence', 0)):04d} "
                f"{event.get('event', '')} · {event.get('actor', '')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _evidence_text(state: WorkbenchState) -> str:
        if not state.evidence:
            return "No Evidence V2 records for the selected task."
        lines = []
        for item in state.evidence[:80]:
            evidence_id = item.get("id", "")
            evidence_type = item.get("evidence_type", item.get("type", "evidence"))
            lifecycle = item.get("lifecycle_status", item.get("status", ""))
            lines.append(f"{evidence_type} · {lifecycle}\n{evidence_id}")
        return "\n\n".join(lines)

    @staticmethod
    def _task_text(state: WorkbenchState) -> str:
        task = state.selected_task
        if not task:
            return "No task"
        checkpoint = task.get("latest_checkpoint")
        error = task.get("error") if isinstance(task.get("error"), dict) else {}
        return (
            f"{task.get('id')} · {task.get('kind')} · {task.get('status')}\n"
            f"session={task.get('session_id', '')} resource="
            f"{task.get('resource_type', '')}:{task.get('resource_id', '')}\n"
            f"objective: {task.get('objective', '')}\n"
            f"checkpoint: {json.dumps(checkpoint, ensure_ascii=False) if checkpoint else 'none'}\n"
            f"error: {json.dumps(error, ensure_ascii=False) if error else 'none'}"
        )

    @staticmethod
    def _records_text(records: list[dict[str, Any]], id_key: str, status_key: str) -> str:
        if not records:
            return "No records"
        lines = []
        for item in records[:20]:
            identifier = str(item.get(id_key, ""))
            lines.append(f"{item.get(status_key, 'unknown')} · {identifier[:80]}")
        return "\n".join(lines)
