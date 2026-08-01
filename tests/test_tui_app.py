from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from hypertrade.tui.app import ControlConfirmScreen, ResearchWorkbenchApp
from textual.widgets import Input, Static, TextArea


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeWorkbenchClient:
    def __init__(self) -> None:
        self.controls: list[tuple[str, str, str]] = []
        self.created: list[str] = []
        self.trigger_controls: list[tuple[str, str, str]] = []
        self.governance_controls: list[tuple[str, str, str]] = []
        self.portfolio_reviews: list[tuple[str, str, str, str]] = []
        self.window_captures = 0
        self.cohort_builds = 0
        self.shadow_builds = 0
        self.shadow_reviews: list[tuple[str, str, str, str]] = []

    def list_agent_sessions(self) -> list[dict[str, Any]]:
        return [{"id": "sess_1", "title": "TUI session", "status": "active"}]

    def create_agent_session(self, title: str) -> dict[str, Any]:
        self.created.append(title)
        return {"id": "sess_new", "title": title}

    def list_agent_tasks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "task_1",
                "session_id": "sess_1",
                "objective": "Research bounded BTC trend",
                "kind": "research_graph",
                "status": "completed",
                "usage": {"tokens": 250},
                "budget": {"max_tokens": 1000},
            }
        ]

    def create_agent_task(
        self, session_id: str, objective: str, *, kind: str = "chat_run"
    ) -> dict[str, Any]:
        return {
            "id": "task_new",
            "session_id": session_id,
            "objective": objective,
            "kind": kind,
            "status": "queued",
            "usage": {},
            "budget": {},
        }

    def get_agent_task(self, task_id: str) -> dict[str, Any]:
        if task_id == "task_new":
            return {
                "id": "task_new",
                "session_id": "sess_new",
                "objective": self.created[-1],
                "kind": "chat_run",
                "status": "queued",
                "usage": {},
                "budget": {},
            }
        return self.list_agent_tasks()[0]

    def list_agent_task_events(self, task_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        events = [
            {"sequence": 1, "event": "task_created", "actor": "operator"},
            {"sequence": 2, "event": "task_status_changed", "actor": "worker"},
        ]
        return [event for event in events if int(event["sequence"]) > after]

    def stream_agent_task_events(self, task_id: str, *, after: int = 0) -> Iterator[dict[str, Any]]:
        return iter(())

    def get_research_graph(self, task_id: str) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_key": "market_regime",
                    "role_key": "market_regime",
                    "status": "completed",
                    "attempt": 1,
                }
            ],
            "evidence": [
                {
                    "id": "ev_1",
                    "evidence_type": "market_fact",
                    "lifecycle_status": "active",
                }
            ],
        }

    def list_experiment_manifests(self) -> list[dict[str, Any]]:
        return [{"fingerprint": "abc", "status": "completed"}]

    def list_robustness_validations(self) -> list[dict[str, Any]]:
        return [{"id": "v_1", "final_status": "rejected"}]

    def list_paper_promotions(self) -> list[dict[str, Any]]:
        return [{"id": "p_1", "status": "pending_review"}]

    def list_research_triggers(self) -> dict[str, Any]:
        return {
            "feature_enabled": True,
            "control": {"kill_switch": False, "reason": ""},
            "items": [
                {
                    "id": "rtrg_1",
                    "name": "Drift trigger",
                    "trigger_type": "strategy_drift",
                    "enabled": True,
                    "next_run_at": None,
                }
            ],
        }

    def list_research_trigger_fires(self, trigger_id: str = "") -> list[dict[str, Any]]:
        return [{"id": "rfire_1", "status": "created", "task_id": "task_1", "reason": ""}]

    def set_research_trigger_enabled(
        self, trigger_id: str, *, enabled: bool, reason: str
    ) -> dict[str, Any]:
        self.trigger_controls.append((trigger_id, "enable" if enabled else "disable", reason))
        return {"id": trigger_id, "enabled": enabled}

    def set_research_trigger_control(self, *, kill_switch: bool, reason: str) -> dict[str, Any]:
        self.trigger_controls.append(("global", "kill_on" if kill_switch else "kill_off", reason))
        return {"kill_switch": kill_switch}

    def fire_research_trigger(
        self, trigger_id: str, *, reason: str = "operator_run_now"
    ) -> dict[str, Any]:
        self.trigger_controls.append((trigger_id, "run", reason))
        return {"id": "rfire_new", "status": "created"}

    def list_memory_assertions(self) -> list[dict[str, Any]]:
        status = "active" if self.governance_controls else "proposed"
        return [
            {
                "id": "masrt_1",
                "status": status,
                "usable": status == "active",
                "claim": "Evidence-bound volatility assertion",
            }
        ]

    def review_memory_assertion(
        self, assertion_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        self.governance_controls.append((assertion_id, decision, reason))
        return {"id": assertion_id, "status": "active" if decision == "approve" else decision}

    def list_skill_proposals(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "skp_1",
                "status": "pending_approval",
                "skill_key": "regime_summary",
                "definition_hash": "a" * 64,
            }
        ]

    def list_skill_releases(self) -> list[dict[str, Any]]:
        return []

    def decide_skill_proposal(
        self, proposal_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        self.governance_controls.append((proposal_id, decision, reason))
        return {"id": proposal_id, "status": decision}

    def list_portfolio_assessments(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "pasmt_1",
                "status": "needs_data",
                "strategies": [{"card_id": "scard_1"}],
                "unknowns": ["strategy.scard_1.capacity"],
                "recommendations": [
                    {
                        "recommendation_id": "plrec_001",
                        "action": "run_targeted_research",
                        "strategy_card_id": "scard_1",
                    }
                ],
            }
        ]

    def list_portfolio_observation_windows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "pwin_1",
                "status": "available",
                "quality": {
                    "coverage_ratio": "0.50000000",
                    "available_count": 1,
                    "denominator": 2,
                },
            }
        ]

    def capture_portfolio_observation_window(self) -> dict[str, Any]:
        self.window_captures += 1
        return self.list_portfolio_observation_windows()[0]

    def list_paper_cohorts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "pcoh_1",
                "version_number": 1,
                "status": "needs_data",
                "intake_count": 2,
                "comparable_count": 1,
                "proposal_count": 1,
            }
        ]

    def build_paper_cohort(self) -> dict[str, Any]:
        self.cohort_builds += 1
        return self.list_paper_cohorts()[0]

    def list_shadow_portfolios(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "shpf_1",
                "version_number": 1,
                "status": "needs_data",
                "intake_count": 2,
                "eligible_count": 0,
                "scenario_count": 0,
                "scenarios": [{"scenario_id": "shsc_1", "template": "equal_weight"}],
            }
        ]

    def build_shadow_portfolio(self) -> dict[str, Any]:
        self.shadow_builds += 1
        return self.list_shadow_portfolios()[0]

    def review_shadow_portfolio(
        self,
        proposal_id: str,
        scenario_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        self.shadow_reviews.append((proposal_id, scenario_id, decision, reason))
        return {"id": "shrv_1", "decision": decision, "capital_authorized": False}

    def list_strategy_cards(self) -> list[dict[str, Any]]:
        return [
            {
                "strategy_key": "btc_trend_v1",
                "version": {"version_number": 1},
                "lifecycle_status": "testing",
                "completeness_score": "0.50000",
            }
        ]

    def get_research_funnel(self) -> dict[str, Any]:
        return {
            "denominator": 1,
            "stages": {"manifest": 1, "paper": 0, "card": 1},
        }

    def create_portfolio_assessment(self) -> dict[str, Any]:
        return self.list_portfolio_assessments()[0]

    def review_portfolio_recommendation(
        self,
        assessment_id: str,
        recommendation_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        self.portfolio_reviews.append((assessment_id, recommendation_id, decision, reason))
        return {"id": "slrev_1", "decision": decision}

    def control_agent_task(self, task_id: str, action: str, *, reason: str) -> dict[str, Any]:
        self.controls.append((task_id, action, reason))
        return {**self.get_agent_task(task_id), "status": "pause_requested"}


@pytest.mark.anyio
async def test_tui_renders_graph_evidence_metrics_and_compact_layout() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert "MISSIONS\n1" in str(app.query_one("#metric-tasks", Static).content)
        assert "market_regime" in str(app.query_one("#graph-view", Static).content)
        assert "market_fact" in str(app.query_one("#evidence-view", Static).content)
        assert "cursor=2" in str(app.query_one("#timeline-view", Static).content)

        await pilot.resize_terminal(80, 36)
        await pilot.pause()
        assert app.has_class("compact")


@pytest.mark.anyio
async def test_tui_control_modal_requires_reason_and_dispatches_request() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(120, 42)) as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, ControlConfirmScreen)
        app.screen.query_one("#control-reason", Input).value = "manual review"
        await pilot.click("#control-submit")
        await pilot.pause()

    assert client.controls == [("task_1", "pause", "manual review")]


@pytest.mark.anyio
async def test_tui_multiline_prompt_creates_new_session_and_task() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(120, 42)) as pilot:
        prompt = app.query_one("#task-prompt", TextArea)
        prompt.load_text("Research ETH\nwith bounded evidence")
        await pilot.click("#start-task")
        await pilot.pause()

    assert client.created == ["Research ETH\nwith bounded evidence"]


@pytest.mark.anyio
async def test_tui_trigger_tab_projects_and_controls_server_trigger() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.press("t")
        await pilot.click("#trigger-disable")
        await pilot.pause()
        assert isinstance(app.screen, ControlConfirmScreen)
        app.screen.query_one("#control-reason", Input).value = "operator review"
        await pilot.click("#control-submit")
        await pilot.pause()
        assert "rtrg_1" in str(app.query_one("#trigger-detail", Static).content)

    assert client.trigger_controls == [("rtrg_1", "disable", "operator review")]


@pytest.mark.anyio
async def test_tui_governance_tab_reviews_source_bound_assertion() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.press("m")
        await pilot.pause()
        assert "masrt_1" in str(app.query_one("#governance-detail", Static).content)
        await pilot.click("#governance-assertion-approve")
        await pilot.pause()
        assert isinstance(app.screen, ControlConfirmScreen)
        app.screen.query_one("#control-reason", Input).value = "sources verified"
        await pilot.click("#control-submit")
        await pilot.pause()

    assert client.governance_controls == [("masrt_1", "approve", "sources verified")]


@pytest.mark.anyio
async def test_tui_portfolio_tab_records_human_review_only() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(190, 50)) as pilot:
        await pilot.press("l")
        await pilot.pause()
        assert "plrec_001" in str(app.query_one("#portfolio-detail", Static).content)
        assert "FUNNEL · denominator=1 · cards=1" in str(
            app.query_one("#portfolio-detail", Static).content
        )
        assert "SHADOW · shpf_1" in str(app.query_one("#portfolio-detail", Static).content)
        await pilot.click("#portfolio-shadow")
        await pilot.pause()
        app.query_one("#shadow-proposal-id", Input).value = "shpf_1"
        app.query_one("#shadow-scenario-id", Input).value = "shsc_1"
        await pilot.click("#shadow-hold")
        await pilot.pause()
        assert isinstance(app.screen, ControlConfirmScreen)
        app.screen.query_one("#control-reason", Input).value = "hypothetical review only"
        await pilot.click("#control-submit")
        await pilot.pause()
        await pilot.click("#portfolio-hold")
        await pilot.pause()
        assert isinstance(app.screen, ControlConfirmScreen)
        app.screen.query_one("#control-reason", Input).value = "need aligned returns"
        await pilot.click("#control-submit")
        await pilot.pause()

    assert client.portfolio_reviews == [("pasmt_1", "plrec_001", "hold", "need aligned returns")]
    assert client.shadow_builds == 1
    assert client.shadow_reviews == [("shpf_1", "shsc_1", "hold", "hypothetical review only")]
