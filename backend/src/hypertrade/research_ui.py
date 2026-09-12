"""Human interface for one canonical research task; UI actions never bypass review hashes."""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import quote

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static, TextArea

from hypertrade.research_follow import research_events


def pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class EvidenceScreen(ModalScreen[tuple[str, str, str] | None]):
    BINDINGS = [
        Binding("escape", "back", "返回", priority=True),
        Binding("q", "quit_view", "退出观看", priority=True),
        Binding("ctrl+c", "detach", "退出观看", priority=True),
    ]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (action == "quit_view" and isinstance(self.app.focused, Input))

    def action_quit_view(self) -> None:
        self.action_detach()

    def action_detach(self) -> None:
        if isinstance(self.app, ResearchApp):
            self.app.action_detach()

    def action_back(self) -> None:
        self.dismiss(None)

    CSS = """
    EvidenceScreen { align: center middle; }
    #evidence-box { width: 92%; height: 85%; border: round $accent;
        background: $surface; padding: 1; }
    #evidence-text { height: 1fr; }
    #reason { margin: 1 0; }
    """

    def __init__(self, package: dict[str, Any], *, review: bool = False):
        super().__init__()
        self.package = package
        self.review = review

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        ready = (
            self.review
            and self.package.get("status") == "ready"
            and not self.package.get("unknowns")
            and bool(self.package.get("package_hash"))
        )
        with Vertical(id="evidence-box"):
            yield Static(
                "逐版本人工审核：阅读标的、参数、最终回测、资金配置与风险后再决定。"
                if self.review
                else "研究证据：任务、开发回测与来源。Esc返回，Ctrl+C退出观看。",
                markup=False,
            )
            yield TextArea(pretty(self.package), read_only=True, id="evidence-text")
            if ready:
                yield Input(
                    placeholder="填写审核意见（必填，最多500字）", id="reason", max_length=500
                )
            with Horizontal():
                if ready:
                    yield Button("批准此版本模拟盘", id="approve", variant="success", disabled=True)
                    yield Button("驳回此版本", id="reject", variant="error", disabled=True)
                yield Button("返回，不提交", id="back")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "reason":
            for key in ("approve", "reject"):
                self.query_one("#" + key, Button).disabled = not bool(event.value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        choice = event.button.id
        if choice == "back":
            self.dismiss(None)
        elif choice in {"approve", "reject"}:
            reason = self.query_one("#reason", Input).value.strip()
            if reason:
                self.dismiss((str(self.package["package_hash"]), choice, reason))


class ResearchApp(App[None]):
    TITLE = "HyperTrade · 自主研究"
    BINDINGS = [
        Binding("q", "quit", "退出观看", priority=True),
        Binding("ctrl+c", "detach", "退出观看", priority=True),
        ("e", "evidence", "研究证据"),
        ("r", "review", "人工审核"),
        ("c", "continue_research", "追加预算"),
        ("f", "follow", "重新连接"),
    ]
    CSS = """
    #stage { height: auto; min-height: 3; border: round $primary; padding: 0 1; }
    #notice { height: auto; min-height: 2; color: $warning; }
    #body { height: 1fr; }
    #events { width: 48%; }
    #details { width: 52%; }
    """

    def __init__(self, client: httpx.Client, mission_id: str):
        super().__init__()
        self.client = client
        self.mission_id = mission_id
        self.path = "/api/v1/arc/missions/" + quote(mission_id, safe="")
        self.rows: dict[str, dict[str, Any]] = {}
        self.stop_reading = threading.Event()
        self.following = False
        self.state = ""
        self.writing = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self.mission_id + "\n正在连接研究事件…", id="stage", markup=False)
        yield Static(
            "方向键选择活动查看完整日志；Q 退出不停止服务器任务。", id="notice", markup=False
        )
        with Horizontal(id="body"):
            yield DataTable(id="events", cursor_type="row")
            yield TextArea("选择左侧活动，展开其日志。", read_only=True, id="details")
        yield Footer()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (action == "quit" and isinstance(self.focused, Input))

    async def action_quit(self) -> None:
        self.action_detach()

    def action_detach(self) -> None:
        self.stop_reading.set()
        self.exit()

    def on_mount(self) -> None:
        self.query_one("#events", DataTable).add_columns("时间", "研究活动")
        self.action_follow()

    def on_unmount(self) -> None:
        self.stop_reading.set()

    def show_notice(self, message: str) -> None:
        self.query_one("#notice", Static).update(message)

    def action_follow(self) -> None:
        if not self.following and not self.writing:
            self.following = True
            self.read_stream()

    @work(thread=True, exit_on_error=False)
    def read_stream(self) -> None:
        try:
            for kind, payload in research_events(
                self.client, self.mission_id, stopped=self.stop_reading.is_set
            ):
                if self.stop_reading.is_set():
                    return
                self.call_from_thread(self.receive, kind, payload)
        except Exception as exc:
            if not self.stop_reading.is_set():
                self.call_from_thread(
                    self.show_notice,
                    f"读取失败：{type(exc).__name__}。按 F 重新连接；研究仍在服务器。",
                )
        finally:
            self.following = False

    def receive(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "activity":
            key = str(payload["event_id"])
            if key not in self.rows:
                self.rows[key] = payload
                table = self.query_one("#events", DataTable)
                follow_latest = table.cursor_row >= table.row_count - 1
                table.add_row(
                    str(payload.get("at", ""))[11:19], str(payload.get("label", "")), key=key
                )
                if follow_latest:
                    table.move_cursor(row=table.row_count - 1)
        elif kind == "snapshot":
            self.state = str(payload.get("state", ""))
            stages = " → ".join(f"{s['label']} [{s['status']}]" for s in payload.get("stages", []))
            self.query_one("#stage", Static).update(self.mission_id + "\n" + stages)
        elif kind == "checkpoint":
            self.show_notice(
                "当前："
                + str(payload.get("state"))
                + "。E 查看证据 / R 审核 / C 追加预算 / Q 退出。模拟观察状态不等于运行健康。"
            )
        elif kind in {"connection", "error"}:
            self.show_notice(str(payload.get("message", "")))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row = self.rows.get(str(event.row_key.value))
        if row:
            self.query_one("#details", TextArea).load_text(pretty(row))

    def action_evidence(self) -> None:
        self.read_evidence(False)

    def action_review(self) -> None:
        self.read_evidence(True)

    @work(thread=True, exclusive=True, group="evidence", exit_on_error=False)
    def read_evidence(self, review: bool) -> None:
        try:
            response = self.client.get(self.path + ("/paper-review" if review else "/evidence"))
            response.raise_for_status()
            self.call_from_thread(
                self.push_screen, EvidenceScreen(response.json(), review=review), self.review_result
            )
        except Exception as exc:
            self.call_from_thread(self.show_notice, f"证据读取失败：{type(exc).__name__}")

    def review_result(self, decision: tuple[str, str, str] | None) -> None:
        if decision and not self.writing:
            digest, choice, reason = decision
            self.writing = True
            self.submit_action(
                "/paper-review/decide",
                {"package_hash": digest, "decision": choice, "reason": reason},
                "cli-paper-" + digest + "-" + choice,
            )

    def action_continue_research(self) -> None:
        if self.state != "needs_operator" or self.writing:
            self.show_notice("仅待处理任务可追加预算；先按 E 查看停止原因。")
            return
        self.push_screen(BudgetScreen(), self.budget_result)

    def budget_result(self, result: dict[str, int] | None) -> None:
        if result and not self.writing:
            import uuid

            self.writing = True
            self.submit_action("/continue", result, "cli-continue-" + uuid.uuid4().hex)

    @work(thread=True, exit_on_error=False)
    def submit_action(self, suffix: str, payload: dict[str, Any], key: str) -> None:
        try:
            response = self.client.post(
                self.path + suffix, json=payload, headers={"Idempotency-Key": key}
            )
            response.raise_for_status()
            self.call_from_thread(self.show_notice, "操作已提交，正在读取服务端结果。")
        except httpx.HTTPStatusError as exc:
            self.call_from_thread(
                self.show_notice, f"操作被拒绝 HTTP {exc.response.status_code}；请重新读取证据。"
            )
        except httpx.TransportError:
            # Never retry an unknown mutation as though it were an event reconnect.
            self.call_from_thread(
                self.show_notice, f"提交结果未知；先刷新核对，勿重复提交。操作键：{key}"
            )
        finally:
            self.writing = False
            self.call_from_thread(self.action_follow)


class BudgetScreen(ModalScreen[dict[str, int] | None]):
    BINDINGS = [
        Binding("escape", "back", "返回", priority=True),
        Binding("q", "quit_view", "退出观看", priority=True),
        Binding("ctrl+c", "detach", "退出观看", priority=True),
    ]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (action == "quit_view" and isinstance(self.app.focused, Input))

    def action_quit_view(self) -> None:
        self.action_detach()

    def action_detach(self) -> None:
        if isinstance(self.app, ResearchApp):
            self.app.action_detach()

    def action_back(self) -> None:
        self.dismiss(None)

    CSS = """
    BudgetScreen {align:center middle;}
    #budget-box {width:60; height:auto; padding:1; border:round $accent; background:$surface;}
    """

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        with Vertical(id="budget-box"):
            yield Static("追加研究预算；已使用最终窗口的任务不能继续调参。", markup=False)
            for key, label, value in [
                ("extra_candidates", "候选数", 3),
                ("extra_model_calls", "模型调用", 10),
                ("extra_backtests", "回测数", 4),
                ("extra_wall_seconds", "时长秒", 1800),
            ]:
                yield Static(label)
                yield Input(str(value), id=key, type="integer")
            yield Button("确认追加并继续", id="continue")
            yield Button("取消", id="cancel")
            yield Static("", id="budget-error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "continue":
            try:
                values = {str(i.id): int(i.value) for i in self.query(Input)}
                if any(v < 0 for v in values.values()) or not any(values.values()):
                    raise ValueError
                self.dismiss(values)
            except ValueError:
                self.query_one("#budget-error", Static).update("请输入非负整数，至少追加一项。")
