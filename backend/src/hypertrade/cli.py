"""Terminal harness for operating HyperTrade.

The CLI has two modes: local AgentKernel execution for development, and remote
API execution for the deployed server. Slash commands are intentionally mapped
to concrete API/service calls so an operator can test each tool without asking the
LLM to plan first.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import getpass
import json
import os
import shlex
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO, cast, runtime_checkable
from urllib.parse import quote

import httpx
from sqlalchemy import desc, select

from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService, session_to_dict
from hypertrade.agent.task_events import TaskEventService, task_event_to_dict
from hypertrade.agent.task_executor import AgentTaskExecutor
from hypertrade.agent.tasks import (
    AgentTaskCreate,
    AgentTaskService,
    TaskControl,
    task_to_dict,
)
from hypertrade.backtest.service import BacktestService
from hypertrade.config import Settings, get_settings
from hypertrade.connectors.registry import ConnectorRegistry
from hypertrade.db import AgentRun, Database, TraceEvent, new_id
from hypertrade.evals.service import AgentEvalSuite
from hypertrade.memory.governance import MemoryAssertionReviewV1, MemoryAssertionService
from hypertrade.memory.service import MemoryService
from hypertrade.portfolio.cohort_schemas import (
    PaperCohortBuildV1,
    PaperCohortLabelDecisionV1,
)
from hypertrade.portfolio.cohorts import PaperCohortService
from hypertrade.portfolio.evidence import PortfolioEvidenceService
from hypertrade.portfolio.evidence_schemas import PortfolioObservationCaptureV1
from hypertrade.portfolio.lifecycle import (
    PortfolioAssessmentRequestV2,
    PortfolioAssessmentService,
    StrategyLifecycleDecisionV1,
)
from hypertrade.portfolio.regime_shadow import RegimeShadowAllocatorServiceV2
from hypertrade.portfolio.regime_shadow_schemas import (
    RegimeShadowBuildV2,
    ShadowAllocationPolicyV2,
)
from hypertrade.portfolio.shadow import ShadowPortfolioService
from hypertrade.portfolio.shadow_schemas import (
    ShadowPortfolioBuildV1,
    ShadowPortfolioReviewV1,
)
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.reporting.blocks import ReportBlock, render_report_blocks
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.graph import ResearchGraphRuntime, graph_topology_projection
from hypertrade.research.graph_tools import BuiltinResearchToolRunner
from hypertrade.research.paper_incubation import AutonomousPaperIncubationService
from hypertrade.research.paper_promotion import PaperPromotionService
from hypertrade.research.robustness import RobustnessValidationService
from hypertrade.research.role_provider import DeterministicGapRoleProvider
from hypertrade.research.schemas import ResearchJobCreate, ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.strategy_cards import StrategyCardService
from hypertrade.research.triggers import (
    ResearchTriggerService,
    TriggerControlUpdate,
    TriggerEvent,
)
from hypertrade.runtime.adapters.capability_catalog import (
    CatalogCapabilityPolicy,
    InMemoryCapabilityCatalog,
    SqlCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.context_engine import (
    ContextArtifactEngine,
    InMemoryContextArtifactStore,
    SqlContextArtifactStore,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.research_planner import ProviderBackedResearchPlanner
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.adapters.tool_runtime import (
    GovernedToolExecutor,
    InMemoryObservationStore,
    SqlObservationStore,
    builtin_handlers,
)
from hypertrade.runtime.application.entrypoint import (
    is_mission_canary,
    mission_request_for_prompt,
    mission_run_projection,
)
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.skills.lifecycle import SkillApprovalV1, SkillLifecycleService, SkillRollbackV1
from hypertrade.strategy.experiment import StrategyExperimentService
from hypertrade.strategy.library import StrategyLibraryService
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolDefinition, ToolRegistry


class AgentClient(Protocol):
    """Shared interface implemented by local and remote CLI clients."""

    def login(self) -> None: ...

    def run_agent(self, prompt: str) -> dict[str, Any]: ...

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]: ...

    def list_tools(self) -> list[dict[str, Any]]: ...

    def list_connectors(self) -> dict[str, Any]: ...

    def list_runs(self) -> list[dict[str, Any]]: ...

    def get_run(self, run_id: str) -> dict[str, Any]: ...

    def list_agent_sessions(self) -> list[dict[str, Any]]: ...

    def create_agent_session(self, title: str) -> dict[str, Any]: ...

    def list_agent_missions(self) -> list[dict[str, Any]]: ...

    def create_agent_mission(self, objective: str) -> dict[str, Any]: ...

    def run_agent_mission(self, mission_id: str) -> dict[str, Any]: ...

    def get_agent_mission(self, mission_id: str) -> dict[str, Any]: ...

    def list_agent_mission_events(
        self, mission_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]: ...

    def stream_agent_mission_events(
        self, mission_id: str, *, after: int = 0
    ) -> Iterator[dict[str, Any]]: ...

    def control_agent_mission(
        self, mission_id: str, action: str, *, reason: str
    ) -> dict[str, Any]: ...

    def list_agent_tasks(self) -> list[dict[str, Any]]: ...

    def create_agent_task(
        self,
        session_id: str,
        objective: str,
        *,
        kind: str = "chat_run",
    ) -> dict[str, Any]: ...

    def get_agent_task(self, task_id: str) -> dict[str, Any]: ...

    def list_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]: ...

    def stream_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> Iterator[dict[str, Any]]: ...

    def research_graph_topology(self) -> dict[str, Any]: ...

    def list_research_graphs(self) -> list[dict[str, Any]]: ...

    def get_research_graph(self, task_id: str) -> dict[str, Any]: ...

    def list_experiment_manifests(self) -> list[dict[str, Any]]: ...

    def get_experiment_manifest(self, fingerprint: str) -> dict[str, Any]: ...

    def diff_experiment_manifests(
        self, left_fingerprint: str, right_fingerprint: str
    ) -> dict[str, Any]: ...

    def list_robustness_validations(self) -> list[dict[str, Any]]: ...

    def get_robustness_validation(self, validation_id: str) -> dict[str, Any]: ...

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

    def control_agent_task(
        self,
        task_id: str,
        action: str,
        *,
        reason: str,
    ) -> dict[str, Any]: ...

    def list_memory(self) -> list[dict[str, Any]]: ...

    def search_memory(self, query: str) -> list[dict[str, Any]]: ...

    def disable_memory(self, memory_id: str) -> dict[str, Any]: ...

    def list_memory_assertions(self) -> list[dict[str, Any]]: ...

    def review_memory_assertion(
        self, assertion_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]: ...

    def list_skill_proposals(self) -> list[dict[str, Any]]: ...

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any]: ...

    def list_skill_releases(self) -> list[dict[str, Any]]: ...

    def decide_skill_proposal(
        self, proposal_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]: ...

    def rollback_skill_release(
        self, release_id: str, *, target_release_id: str, reason: str
    ) -> dict[str, Any]: ...

    def list_portfolio_assessments(self) -> list[dict[str, Any]]: ...

    def list_portfolio_observation_windows(self) -> list[dict[str, Any]]: ...

    def list_paper_cohorts(self) -> list[dict[str, Any]]: ...

    def list_paper_incubation_mandates(self) -> list[dict[str, Any]]: ...

    def build_paper_cohort(self) -> dict[str, Any]: ...

    def get_paper_cohort(self, cohort_id: str) -> dict[str, Any]: ...

    def diff_paper_cohorts(self, left_id: str, right_id: str) -> dict[str, Any]: ...

    def decide_paper_cohort_label(
        self,
        cohort_id: str,
        proposal_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def list_shadow_portfolios(self) -> list[dict[str, Any]]: ...

    def build_shadow_portfolio(self) -> dict[str, Any]: ...

    def get_shadow_portfolio(self, proposal_id: str) -> dict[str, Any]: ...

    def diff_shadow_portfolios(self, left_id: str, right_id: str) -> dict[str, Any]: ...

    def review_shadow_portfolio(
        self,
        proposal_id: str,
        scenario_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def list_regime_shadow_targets(self) -> list[dict[str, Any]]: ...

    def build_regime_shadow_target(
        self, regime_id: str, cohort_id: str
    ) -> dict[str, Any]: ...

    def get_regime_shadow_target(self, target_id: str) -> dict[str, Any]: ...

    def replay_regime_shadow_target(self, target_id: str) -> dict[str, Any]: ...

    def capture_portfolio_observation_window(self) -> dict[str, Any]: ...

    def get_portfolio_observation_window(self, window_id: str) -> dict[str, Any]: ...

    def diff_portfolio_observation_windows(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]: ...

    def create_portfolio_assessment(self) -> dict[str, Any]: ...

    def get_portfolio_assessment(self, assessment_id: str) -> dict[str, Any]: ...

    def diff_portfolio_assessments(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]: ...

    def review_portfolio_recommendation(
        self,
        assessment_id: str,
        recommendation_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]: ...

    def get_evals_status(self) -> dict[str, Any]: ...

    def list_strategy_cards(self) -> list[dict[str, Any]]: ...

    def get_research_funnel(self) -> dict[str, Any]: ...

    def list_strategy_evolution_runs(self) -> list[dict[str, Any]]: ...

    def get_strategy_evolution_run(self, run_id: str) -> dict[str, Any]: ...

    def list_monitors(self) -> list[dict[str, Any]]: ...

    def run_monitor(self, monitor_id: str) -> dict[str, Any]: ...

    def list_alerts(self) -> list[dict[str, Any]]: ...

    def list_strategy_research(self) -> list[dict[str, Any]]: ...

    def list_strategy_library(self, query: str = "") -> dict[str, Any]: ...

    def list_backtests(self) -> list[dict[str, Any]]: ...

    def create_strategy_research(self, prompt: str) -> dict[str, Any]: ...

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]: ...

    def create_strategy_iteration(self, prompt: str) -> dict[str, Any]: ...

    def list_research_mandates(self) -> list[dict[str, Any]]: ...

    def create_research_mandate(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def pause_research_mandate(self, mandate_id: str) -> dict[str, Any]: ...

    def resume_research_mandate(self, mandate_id: str) -> dict[str, Any]: ...

    def draft_research_strategy_spec(self, mandate_id: str, prompt: str) -> dict[str, Any]: ...

    def list_research_jobs(self, mandate_id: str = "") -> list[dict[str, Any]]: ...

    def queue_research_job(self, mandate_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def cancel_research_job(
        self, job_id: str, reason: str = "operator_canceled"
    ) -> dict[str, Any]: ...

    def run_research_job(self, job_id: str) -> dict[str, Any]: ...

    def research_job_report(self, job_id: str) -> dict[str, Any]: ...

    def list_paper_promotions(self) -> list[dict[str, Any]]: ...

    def request_paper_promotion(self, evidence_id: str, reason: str) -> dict[str, Any]: ...

    def approve_paper_promotion(
        self, promotion_id: str, reason: str, idempotency_key: str
    ) -> dict[str, Any]: ...

    def observe_paper_promotion(self, promotion_id: str) -> dict[str, Any]: ...

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_model_status(self) -> dict[str, Any]: ...

    def set_model(self, provider: str, model: str = "") -> dict[str, Any]: ...

    def get_market_ticker(self, symbol: str) -> dict[str, Any]: ...

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]: ...

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]: ...

    def get_paper_status(self) -> dict[str, Any]: ...

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]: ...

    def list_live_order_intents(self) -> list[dict[str, Any]]: ...

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]: ...

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]: ...

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]: ...


@runtime_checkable
class CanonicalThreadClient(Protocol):
    """Remote-only protocol used by canonical ask/chat surfaces."""

    def create_thread(self, *, title: str, retention: str) -> dict[str, Any]: ...

    def start_thread_turn(
        self,
        thread_id: str,
        prompt: str,
        *,
        client_message_id: str,
    ) -> dict[str, Any]: ...

    def get_thread_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]: ...

    def stream_thread_events(
        self,
        thread_id: str,
        *,
        after: int = 0,
    ) -> Iterator[dict[str, Any]]: ...

    def interrupt_thread_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]: ...


class AgentClientFactory(Protocol):
    def __call__(self, config: CliConfig, local: bool) -> AgentClient: ...


THINKING_FRAMES: tuple[str, ...] = ("|", "/", "-", "\\")
DEFAULT_REMOTE_API_URL = "http://47.79.36.92:3333"


SLASH_COMMAND_HELP: tuple[tuple[str, str], ...] = (
    ("/help", "Show this command list."),
    ("/status", "Show runtime, session, market, memory, and tool counts."),
    ("/model", "Show the active provider and model."),
    ("/model <provider>", "Switch the active chat provider for this CLI session."),
    ("/providers", "List configured providers and key status."),
    ("/tools", "List registered Agent tools with category, approval gate, and purpose."),
    ("/connectors", "List external connector capabilities and secret-redacted auth status."),
    ("/runs", "List recent Agent runs."),
    ("/run <run_id>", "Open one persisted run with the active report and trace renderer."),
    ("/sessions", "List durable Agent sessions."),
    ("/tasks", "List durable Agent tasks and control state."),
    ("/task <task_id>", "Inspect one task and its latest checkpoint."),
    (
        "/task <task_id> pause|resume|cancel|retry|branch [reason]",
        "Apply an idempotent operator control action.",
    ),
    (
        "/research-graph topology|list|show <task_id>",
        "Inspect the fixed role graph, node budgets, and evidence.",
    ),
    (
        "/ledger list|show <fingerprint>|diff <left> <right>",
        "Inspect immutable experiment manifests, executions, and semantic differences.",
    ),
    (
        "/validations list|show <validation_id>",
        "Inspect locked-OOS, walk-forward, sensitivity, and stress gates.",
    ),
    (
        "/triggers list|fires [id]|enable|disable|run <id>|kill on|off",
        "Inspect and control bounded background research triggers.",
    ),
    ("/memory", "List active audited memory."),
    ("/memory search <query>", "Search audited memory by text."),
    ("/memory disable <mem_id>", "Disable one memory item without deleting audit history."),
    (
        "/assertions list|approve|reject|dispute <id> [reason]",
        "Review source-bound Memory Assertions.",
    ),
    (
        "/skills proposals|show|releases|approve|reject|rollback",
        "Review evaluated code-free Skill proposals and immutable releases.",
    ),
    (
        "/portfolio-v2 list|assess|show|diff|review",
        "Inspect bounded portfolio lifecycle assessments and record human review.",
    ),
    (
        "/windows list|capture|show|diff",
        "Inspect bounded PortfolioObservationWindow data-quality evidence.",
    ),
    (
        "/cohorts list|build|show|diff|decide",
        "Inspect comparable paper cohorts and record expiring label reviews.",
    ),
    (
        "/regime-shadow list|build|show|replay",
        "Inspect point-in-time eligibility and hypothetical Shadow V2 targets.",
    ),
    (
        "/incubation",
        "Inspect PaperResearchMandates, kill switches, governed actions, and unknown effects.",
    ),
    ("/rag <query>", "Search project and trading knowledge chunks."),
    ("/evals", "Show deterministic Agent eval status."),
    ("/cards", "Show StrategyCard V2 candidates and the fixed research funnel."),
    ("/evolution list|show <run_id>", "Inspect read-only existing-strategy candidates."),
    ("/monitors", "List configured read-only monitors."),
    ("/monitor run <monitor_id>", "Run one monitor manually and persist alerts."),
    ("/alerts", "List recent monitor alert events."),
    ("/strategy", "List recent strategy research records."),
    ("/strategy library [query]", "Summarize strategy_knowledge memory as a strategy library."),
    ("/backtests", "List recent backtest runs."),
    ("/price ETH", "Fetch one exact OKX SWAP ticker without LLM planning."),
    ("/candles ETH --bar 1H --limit 100", "Fetch candles and derived trend features."),
    ("/compare ETH SOL --bar 4H --limit 100", "Compare relative strength for symbols."),
    ("/paper status", "Show the current paper trading session."),
    ("/paper pause|resume", "Pause or resume the local paper runtime."),
    ("/paper close [symbol]", "Close paper positions, optionally filtered by symbol."),
    ("/paper reset", "Start a fresh audited paper session."),
    ("/live intents", "List pending live/testnet order intents."),
    (
        "/live intent ETH buy 0.01 [--type limit --price 3500 --reason text]",
        "Create an approval-gated order intent.",
    ),
    ("/live approve loi_* [--reason text]", "Approve a pending order intent."),
    ("/live reject loi_* [--reason text]", "Reject a pending order intent."),
    ("/live execute loi_*", "Execute an approved Testnet intent through the configured adapter."),
    ("/research <prompt>", "Create strategy research from a prompt."),
    ("/research-program list", "List operator-controlled research mandates."),
    (
        "/research-program create '<json>'",
        "Create a manual-approval, live-disabled research mandate.",
    ),
    (
        "/research-program draft <rman_id> <prompt>",
        "Produce a bounded StrategySpec draft only.",
    ),
    ("/research-program jobs [rman_id]", "List durable research jobs."),
    (
        "/research-program queue <rman_id> <idempotency_key> <prompt>",
        "Queue a bounded research run with a unique idempotency key.",
    ),
    (
        "/research-program run <rjob_id>",
        "Run the bounded BitPro backtest matrix; never starts paper or live trading.",
    ),
    ("/research-program report <rjob_id>", "Read persisted BitPro result references and gates."),
    ("/research-program promotions", "List paper-promotion approvals and observation state."),
    (
        "/research-program promote <rexp_id> <reason>",
        "Request paper promotion from passing validation evidence; does not start paper.",
    ),
    (
        "/research-program approve-paper <ppr_id> <idempotency_key> <reason>",
        "Administrator-only BitPro paper configure/start approval.",
    ),
    (
        "/research-program observe-paper <ppr_id>",
        "Capture read-only BitPro paper observation evidence.",
    ),
    ("/experiment <prompt>", "Run research, backtest, critique, and revision workflow."),
    ("/backtest", "Run a backtest from the latest research record."),
    ("/backtest list", "List recent backtests."),
    ("/backtest latest|srch_*|<key>", "Run a specific backtest target."),
    ("/backtest --live --symbol ETH --bar 1H --limit 100", "Backtest with recent live candles."),
    ("/backtest --source bitpro_mcp --symbol ETH --bar 1H", "Backtest with BitPro MCP K-lines."),
)

SLASH_COMMAND_COMPLETIONS: tuple[str, ...] = tuple(
    dict.fromkeys(command.split()[0] for command, _ in SLASH_COMMAND_HELP)
)
SLASH_ARGUMENT_COMPLETIONS: dict[str, tuple[str, ...]] = {
    "/model": ("deepseek", "openai", "codex", "openai-codex", "openrouter", "qwen"),
    "/memory": ("search", "disable"),
    "/monitor": ("run",),
    "/strategy": ("library",),
    "/research-program": (
        "list",
        "create",
        "pause",
        "resume",
        "draft",
        "jobs",
        "queue",
        "run",
        "report",
        "promotions",
        "promote",
        "approve-paper",
        "observe-paper",
        "cancel",
    ),
    "/research-graph": ("topology", "list", "show"),
    "/evolution": ("list", "show"),
    "/ledger": ("list", "show", "diff"),
    "/validations": ("list", "show"),
    "/triggers": ("list", "fires", "enable", "disable", "run", "kill"),
    "/backtest": ("list", "latest", "--live", "--source bitpro_mcp"),
    "/paper": ("status", "pause", "resume", "close", "reset"),
    "/live": ("intents", "intent", "approve", "reject", "execute"),
    "/price": ("BTC", "ETH", "SOL", "DOGE", "PEPE"),
    "/ticker": ("BTC", "ETH", "SOL", "DOGE", "PEPE"),
    "/candles": ("BTC", "ETH", "SOL", "DOGE", "PEPE", "--bar 1H", "--limit 100"),
    "/kline": ("BTC", "ETH", "SOL", "DOGE", "PEPE", "--bar 1H", "--limit 100"),
    "/klines": ("BTC", "ETH", "SOL", "DOGE", "PEPE", "--bar 1H", "--limit 100"),
    "/compare": ("BTC", "ETH", "SOL", "DOGE", "PEPE"),
}
SLASH_CANDIDATE_LIMIT = 12


@dataclass(frozen=True)
class CliConfig:
    api_url: str
    username: str
    password: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls, *, api_url: str | None = None) -> CliConfig:
        saved = read_client_env()
        return cls(
            api_url=api_url
            or os.getenv("HYPERTRADE_API_URL")
            or saved.get("HYPERTRADE_API_URL")
            or "http://127.0.0.1:3334",
            username=os.getenv("HYPERTRADE_USERNAME")
            or saved.get("HYPERTRADE_USERNAME")
            or os.getenv("ADMIN_USERNAME")
            or "admin",
            password=os.getenv("HYPERTRADE_PASSWORD")
            or saved.get("HYPERTRADE_PASSWORD")
            or os.getenv("ADMIN_PASSWORD")
            or "hypertrade-admin",
            timeout_seconds=float(os.getenv("HYPERTRADE_TIMEOUT_SECONDS", "20")),
        )


@dataclass
class InteractiveHistory:
    enabled: bool
    readline_module: Any | None = None
    last_item: str = ""

    def add(self, item: str) -> None:
        value = item.strip()
        if not self.enabled or not value or value == self.last_item:
            return
        module = self.readline_module
        if module is None or not hasattr(module, "add_history"):
            return
        if hasattr(module, "get_current_history_length") and hasattr(
            module,
            "get_history_item",
        ):
            length = int(module.get_current_history_length())
            if length > 0 and module.get_history_item(length) == value:
                self.last_item = value
                return
        module.add_history(value)
        self.last_item = value


def configure_interactive_history(
    *,
    enabled: bool,
    history_path: Path | None = None,
    readline_module: Any | None = None,
    register_exit: Callable[..., Any] = atexit.register,
) -> InteractiveHistory:
    if not enabled:
        return InteractiveHistory(enabled=False)
    try:
        if readline_module is None:
            import readline

            module: Any = readline
        else:
            module = readline_module
    except ImportError:
        return InteractiveHistory(enabled=False)

    path = history_path or (Path.home() / ".hypertrade" / "history")
    history_persistence_enabled = True
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
    except OSError:
        # History persistence is convenience-only. Completion and in-session
        # recall must remain available when the local history path is invalid.
        history_persistence_enabled = False
    if path.exists() and not path.is_file():
        history_persistence_enabled = False
    history_file = str(path)
    if hasattr(module, "set_history_length"):
        module.set_history_length(1000)
    if history_persistence_enabled and hasattr(module, "read_history_file"):
        try:
            module.read_history_file(history_file)
        except FileNotFoundError:
            pass
        except OSError:
            history_persistence_enabled = False
    if history_persistence_enabled and hasattr(module, "write_history_file"):
        register_exit(module.write_history_file, history_file)
    _configure_slash_command_completion(module)
    return InteractiveHistory(enabled=True, readline_module=module)


def _configure_slash_command_completion(module: Any) -> None:
    if not hasattr(module, "set_completer"):
        return
    module.set_completer(_make_slash_command_completer(module))
    if hasattr(module, "set_completion_display_matches_hook"):
        with suppress(Exception):
            module.set_completion_display_matches_hook(_make_slash_command_display_hook(module))
    if hasattr(module, "parse_and_bind"):
        with suppress(Exception):
            module.parse_and_bind("tab: complete")


def _make_slash_command_completer(module: Any) -> Callable[[str, int], str | None]:
    def complete(text: str, state: int) -> str | None:
        line = text
        begidx = 0
        if hasattr(module, "get_line_buffer"):
            line = str(module.get_line_buffer())
        if hasattr(module, "get_begidx"):
            begidx = int(module.get_begidx())
        matches = _slash_command_completion_matches(line=line, text=text, begidx=begidx)
        if state < 0 or state >= len(matches):
            return None
        return matches[state]

    return complete


def _make_slash_command_display_hook(module: Any) -> Callable[[str, list[str], int], None]:
    def display(substitution: str, matches: list[str], longest_match_length: int) -> None:
        del matches, longest_match_length
        line = substitution
        if hasattr(module, "get_line_buffer"):
            line = str(module.get_line_buffer()) or substitution
        if not line.startswith("/"):
            return
        print("")
        render_slash_command_candidates(line, output=sys.stdout)
        if hasattr(module, "redisplay"):
            with suppress(Exception):
                module.redisplay()

    return display


def _slash_command_completion_matches(*, line: str, text: str, begidx: int) -> list[str]:
    if not line.startswith("/"):
        return []
    if begidx == 0:
        query = text.lower()
        return [
            f"{command} "
            for command in SLASH_COMMAND_COMPLETIONS
            if command.lower().startswith(query)
        ]

    command = line.split(maxsplit=1)[0].lower()
    candidates = SLASH_ARGUMENT_COMPLETIONS.get(command, ())
    query = text.lower()
    return [f"{candidate} " for candidate in candidates if candidate.lower().startswith(query)]


def _slash_command_candidates(
    prefix: str,
    *,
    limit: int | None = SLASH_CANDIDATE_LIMIT,
) -> list[tuple[str, str]]:
    normalized = " ".join(prefix.strip().lower().split())
    if not normalized.startswith("/"):
        return []
    if normalized == "/":
        matches = list(SLASH_COMMAND_HELP)
    else:
        matches = [
            (command, description)
            for command, description in SLASH_COMMAND_HELP
            if _slash_candidate_matches_prefix(command, normalized)
        ]
    if limit is None:
        return matches
    return matches[:limit]


def _slash_argument_candidates(
    prefix: str,
    *,
    limit: int | None = SLASH_CANDIDATE_LIMIT,
) -> list[str]:
    raw = prefix.strip()
    if not raw.startswith("/"):
        return []
    if " " not in raw:
        return []
    command, rest = raw.split(maxsplit=1)
    candidates = SLASH_ARGUMENT_COMPLETIONS.get(command.lower(), ())
    if not candidates:
        return []
    normalized_rest = rest.lower()
    matches = [
        candidate
        for candidate in candidates
        if candidate.lower().startswith(normalized_rest) and candidate.lower() != normalized_rest
    ]
    if limit is None:
        return matches
    return matches[:limit]


def _slash_candidate_matches_prefix(command: str, normalized_prefix: str) -> bool:
    normalized_command = " ".join(command.lower().split())
    command_name = normalized_command.split(maxsplit=1)[0]
    return normalized_command.startswith(normalized_prefix) or command_name.startswith(
        normalized_prefix
    )


def _looks_like_slash_prefix(command: str) -> bool:
    token = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    return token.startswith("/") and len(token) >= 2


def client_env_path() -> Path:
    configured = os.getenv("HYPERTRADE_CLIENT_ENV")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".hypertrade" / "client.env"


def read_client_env() -> dict[str, str]:
    path = client_env_path()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not parts or "=" not in parts[0]:
            continue
        key, value = parts[0].split("=", 1)
        if key in {"HYPERTRADE_API_URL", "HYPERTRADE_USERNAME", "HYPERTRADE_PASSWORD"}:
            values[key] = value
    return values


def write_client_env(config: CliConfig) -> Path:
    path = client_env_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    content = "\n".join(
        [
            f"HYPERTRADE_API_URL={_quote_shell_value(config.api_url)}",
            f"HYPERTRADE_USERNAME={_quote_shell_value(config.username)}",
            f"HYPERTRADE_PASSWORD={_quote_shell_value(config.password)}",
        ]
    )
    path.write_text(f"{content}\n")
    path.chmod(0o600)
    return path


def _quote_shell_value(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


class AgentApiClient:
    def __init__(
        self,
        config: CliConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.client = http_client or httpx.Client(
            base_url=config.api_url.rstrip("/"),
            timeout=_request_timeout(config.timeout_seconds),
        )

    def login(self) -> None:
        response = self.client.post(
            self._url("/api/auth/login"),
            json={"username": self.config.username, "password": self.config.password},
        )
        response.raise_for_status()

    def run_agent(self, prompt: str) -> dict[str, Any]:
        response = self.client.post(
            self._url("/api/agent/runs"),
            json={"prompt": prompt},
            headers={"Idempotency-Key": new_id("cli_run")},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Agent run response must be a JSON object")
        return payload

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]:
        with self.client.stream(
            "POST",
            self._url("/api/agent/runs/stream"),
            json={"prompt": prompt},
            headers={"Idempotency-Key": new_id("cli_stream")},
            timeout=_stream_timeout(config=self.config),
        ) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line == "":
                    if data_lines:
                        yield _parse_sse_event(event_name, data_lines)
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
            if data_lines:
                yield _parse_sse_event(event_name, data_lines)

    def create_thread(self, *, title: str, retention: str) -> dict[str, Any]:
        return self._post_object(
            "/api/agent/v1/threads",
            {"title": title, "retention": retention},
        )

    def start_thread_turn(
        self,
        thread_id: str,
        prompt: str,
        *,
        client_message_id: str,
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/agent/v1/threads/{quote(thread_id, safe='')}/turns",
            {"input": prompt, "client_message_id": client_message_id},
        )

    def get_thread_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/agent/v1/threads/{quote(thread_id, safe='')}/turns/"
            f"{quote(turn_id, safe='')}"
        )

    def stream_thread_events(
        self,
        thread_id: str,
        *,
        after: int = 0,
    ) -> Iterator[dict[str, Any]]:
        cursor = max(after, 0)
        with self.client.stream(
            "GET",
            self._url(
                f"/api/agent/v1/threads/{quote(thread_id, safe='')}/events/stream?after={cursor}"
            ),
            headers={"Last-Event-ID": str(cursor)},
            timeout=_stream_timeout(config=self.config),
        ) as response:
            response.raise_for_status()
            event_name = "message"
            event_cursor = cursor
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line == "":
                    if data_lines:
                        event = _parse_sse_event(event_name, data_lines)
                        event["cursor"] = event_cursor
                        yield event
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("id:"):
                    event_cursor = int(line.split(":", 1)[1].strip())
                elif line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
            if data_lines:
                event = _parse_sse_event(event_name, data_lines)
                event["cursor"] = event_cursor
                yield event

    def interrupt_thread_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        return self._post_object(
            f"/api/agent/v1/threads/{quote(thread_id, safe='')}/turns/"
            f"{quote(turn_id, safe='')}/interrupt",
            {},
        )

    def list_tools(self) -> list[dict[str, Any]]:
        return self._get_list("/api/harness/tools", "tools")

    def list_connectors(self) -> dict[str, Any]:
        return self._get_object("/api/connectors/capabilities")

    def list_runs(self) -> list[dict[str, Any]]:
        return self._get_list("/api/agent/runs", "runs")

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/agent/runs/{quote(run_id, safe='')}")

    def list_agent_sessions(self) -> list[dict[str, Any]]:
        return self._get_list("/api/agent/sessions", "sessions")

    def create_agent_session(self, title: str) -> dict[str, Any]:
        return self._post_object(
            "/api/agent/sessions",
            {"title": title, "surface": "tui", "created_by": "tui_operator"},
        )

    def list_agent_missions(self) -> list[dict[str, Any]]:
        return self._get_list("/api/agent/missions", "missions")

    def create_agent_mission(self, objective: str) -> dict[str, Any]:
        payload = mission_request_for_prompt(
            objective,
            actor="tui_operator",
            idempotency_key=new_id("tui_mission"),
        ).model_dump(mode="json")
        response = self.client.post(
            self._url("/api/agent/missions"),
            json=payload,
            headers={"Idempotency-Key": str(payload["idempotency_key"])},
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise TypeError("Mission creation response must be a JSON object")
        return value

    def run_agent_mission(self, mission_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/agent/missions/{quote(mission_id, safe='')}/run", {})

    def get_agent_mission(self, mission_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/agent/missions/{quote(mission_id, safe='')}")

    def list_agent_mission_events(
        self,
        mission_id: str,
        *,
        after: int = 0,
    ) -> list[dict[str, Any]]:
        return self._get_list(
            f"/api/agent/missions/{quote(mission_id, safe='')}/events?after={max(after, 0)}",
            "events",
        )

    def stream_agent_mission_events(
        self,
        mission_id: str,
        *,
        after: int = 0,
    ) -> Iterator[dict[str, Any]]:
        cursor = max(after, 0)
        with self.client.stream(
            "GET",
            self._url(
                f"/api/agent/missions/{quote(mission_id, safe='')}/events/stream?after={cursor}"
            ),
            headers={"Last-Event-ID": str(cursor)},
            timeout=_stream_timeout(config=self.config),
        ) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line == "":
                    if data_lines:
                        yield _parse_sse_event(event_name, data_lines)
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
            if data_lines:
                yield _parse_sse_event(event_name, data_lines)

    def control_agent_mission(
        self,
        mission_id: str,
        action: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        if action not in {"pause", "resume", "cancel"}:
            raise ValueError(f"unsupported Mission action: {action}")
        return self._post_object(
            f"/api/agent/missions/{quote(mission_id, safe='')}/control",
            {"action": action, "reason": reason},
        )

    def list_portfolio_assessments(self) -> list[dict[str, Any]]:
        return self._get_list("/api/portfolio/assessments", "items")

    def list_portfolio_observation_windows(self) -> list[dict[str, Any]]:
        return self._get_list("/api/portfolio/observation-windows", "items")

    def list_paper_cohorts(self) -> list[dict[str, Any]]:
        return self._get_list("/api/portfolio/paper-cohorts", "items")

    def list_paper_incubation_mandates(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/paper-incubation/mandates", "items")

    def build_paper_cohort(self) -> dict[str, Any]:
        return self._post_object(
            "/api/portfolio/paper-cohorts",
            {"idempotency_key": new_id("cli_cohort")},
        )

    def get_paper_cohort(self, cohort_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/paper-cohorts/{quote(cohort_id, safe='')}"
        )

    def diff_paper_cohorts(self, left_id: str, right_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/paper-cohorts/{quote(left_id, safe='')}"
            f"/diff/{quote(right_id, safe='')}"
        )

    def decide_paper_cohort_label(
        self,
        cohort_id: str,
        proposal_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/portfolio/paper-cohorts/{quote(cohort_id, safe='')}/decisions",
            {
                "proposal_id": proposal_id,
                "decision": decision,
                "reason": reason,
                "idempotency_key": new_id("cli_cohort_decision"),
            },
        )

    def list_shadow_portfolios(self) -> list[dict[str, Any]]:
        return self._get_list("/api/portfolio/shadow-portfolios", "items")

    def build_shadow_portfolio(self) -> dict[str, Any]:
        return self._post_object(
            "/api/portfolio/shadow-portfolios",
            {"idempotency_key": new_id("cli_shadow")},
        )

    def get_shadow_portfolio(self, proposal_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/shadow-portfolios/{quote(proposal_id, safe='')}"
        )

    def diff_shadow_portfolios(self, left_id: str, right_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/shadow-portfolios/{quote(left_id, safe='')}"
            f"/diff/{quote(right_id, safe='')}"
        )

    def review_shadow_portfolio(
        self,
        proposal_id: str,
        scenario_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/portfolio/shadow-portfolios/{quote(proposal_id, safe='')}/reviews",
            {
                "scenario_id": scenario_id,
                "decision": decision,
                "reason": reason,
                "idempotency_key": new_id("cli_shadow_review"),
            },
        )

    def list_regime_shadow_targets(self) -> list[dict[str, Any]]:
        return self._get_list(
            "/api/portfolio/regime-shadow-targets-v2", "items"
        )

    def build_regime_shadow_target(
        self, regime_id: str, cohort_id: str
    ) -> dict[str, Any]:
        return self._post_object(
            "/api/portfolio/regime-shadow-targets-v2",
            {
                "decision_at": datetime.now(UTC).isoformat(),
                "regime_snapshot_id": regime_id,
                "cohort_snapshot_id": cohort_id,
                "policy": _default_regime_shadow_policy().model_dump(
                    mode="json"
                ),
                "idempotency_key": new_id("cli_regime_shadow"),
            },
        )

    def get_regime_shadow_target(self, target_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/regime-shadow-targets-v2/"
            f"{quote(target_id, safe='')}"
        )

    def replay_regime_shadow_target(self, target_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/regime-shadow-targets-v2/"
            f"{quote(target_id, safe='')}/replay"
        )

    def capture_portfolio_observation_window(self) -> dict[str, Any]:
        return self._post_object(
            "/api/portfolio/observation-windows",
            {"idempotency_key": new_id("cli_window")},
        )

    def get_portfolio_observation_window(self, window_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/observation-windows/{quote(window_id, safe='')}"
        )

    def diff_portfolio_observation_windows(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/observation-windows/{quote(left_id, safe='')}"
            f"/diff/{quote(right_id, safe='')}"
        )

    def create_portfolio_assessment(self) -> dict[str, Any]:
        return self._post_object(
            "/api/portfolio/assessments",
            {"idempotency_key": new_id("cli_portfolio")},
        )

    def get_portfolio_assessment(self, assessment_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/assessments/{quote(assessment_id, safe='')}"
        )

    def diff_portfolio_assessments(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]:
        return self._get_object(
            f"/api/portfolio/assessments/{quote(left_id, safe='')}"
            f"/diff/{quote(right_id, safe='')}"
        )

    def review_portfolio_recommendation(
        self,
        assessment_id: str,
        recommendation_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/portfolio/assessments/{quote(assessment_id, safe='')}/reviews",
            {
                "recommendation_id": recommendation_id,
                "decision": decision,
                "reason": reason,
                "idempotency_key": new_id("cli_lifecycle_review"),
            },
        )

    def list_agent_tasks(self) -> list[dict[str, Any]]:
        return self._get_list("/api/agent/tasks", "tasks")

    def create_agent_task(
        self,
        session_id: str,
        objective: str,
        *,
        kind: str = "chat_run",
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/agent/sessions/{quote(session_id, safe='')}/tasks",
            {
                "objective": objective,
                "kind": kind,
                "idempotency_key": new_id("tui_task"),
            },
        )

    def get_agent_task(self, task_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/agent/tasks/{quote(task_id, safe='')}")

    def list_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]:
        return self._get_list(
            f"/api/agent/tasks/{quote(task_id, safe='')}/events?after={max(after, 0)}",
            "events",
        )

    def stream_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> Iterator[dict[str, Any]]:
        cursor = max(after, 0)
        with self.client.stream(
            "GET",
            self._url(
                f"/api/agent/tasks/{quote(task_id, safe='')}/stream?after={cursor}"
            ),
            headers={"Last-Event-ID": str(cursor)},
            timeout=_stream_timeout(config=self.config),
        ) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line == "":
                    if data_lines:
                        yield _parse_sse_event(event_name, data_lines)
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
            if data_lines:
                yield _parse_sse_event(event_name, data_lines)

    def research_graph_topology(self) -> dict[str, Any]:
        return self._get_object("/api/research/graphs/topology")

    def list_research_graphs(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/graphs", "items")

    def get_research_graph(self, task_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/research/graphs/{quote(task_id, safe='')}")

    def list_experiment_manifests(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/experiments", "items")

    def get_experiment_manifest(self, fingerprint: str) -> dict[str, Any]:
        return self._get_object(f"/api/research/experiments/{quote(fingerprint, safe='')}")

    def diff_experiment_manifests(
        self, left_fingerprint: str, right_fingerprint: str
    ) -> dict[str, Any]:
        return self._get_object(
            f"/api/research/experiments/{quote(left_fingerprint, safe='')}"
            f"/diff/{quote(right_fingerprint, safe='')}"
        )

    def list_robustness_validations(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/validations", "items")

    def get_robustness_validation(self, validation_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/research/validations/{quote(validation_id, safe='')}")

    def list_research_triggers(self) -> dict[str, Any]:
        return self._get_object("/api/research/triggers")

    def list_research_trigger_fires(self, trigger_id: str = "") -> list[dict[str, Any]]:
        suffix = f"?trigger_id={quote(trigger_id, safe='')}" if trigger_id else ""
        return self._get_list(f"/api/research/triggers/fires{suffix}", "items")

    def set_research_trigger_enabled(
        self, trigger_id: str, *, enabled: bool, reason: str
    ) -> dict[str, Any]:
        return self._put_object(
            f"/api/research/triggers/{quote(trigger_id, safe='')}/enabled",
            {"enabled": enabled, "reason": reason},
        )

    def set_research_trigger_control(
        self, *, kill_switch: bool, reason: str
    ) -> dict[str, Any]:
        return self._put_object(
            "/api/research/triggers/control",
            {"kill_switch": kill_switch, "reason": reason},
        )

    def fire_research_trigger(
        self, trigger_id: str, *, reason: str = "operator_run_now"
    ) -> dict[str, Any]:
        trigger = next(
            (
                item
                for item in self.list_research_triggers().get("items", [])
                if item.get("id") == trigger_id
            ),
            None,
        )
        if not isinstance(trigger, dict):
            raise KeyError(trigger_id)
        return self._post_object(
            f"/api/research/triggers/{quote(trigger_id, safe='')}/fire",
            {
                "source_type": trigger.get("trigger_type", "schedule"),
                "source_id": new_id("manual"),
                "metrics": {"operator_reason": reason},
            },
        )

    def control_agent_task(
        self,
        task_id: str,
        action: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/agent/tasks/{quote(task_id, safe='')}/{quote(action, safe='')}",
            {
                "reason": reason,
                "idempotency_key": new_id("cli"),
                "actor": "cli_operator",
            },
        )

    def list_memory(self) -> list[dict[str, Any]]:
        return self._get_list("/api/memory", "items")

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        return self._get_list(f"/api/memory?query={quote(query)}", "items")

    def disable_memory(self, memory_id: str) -> dict[str, Any]:
        response = self.client.delete(self._url(f"/api/memory/{memory_id}"))
        response.raise_for_status()
        payload = response.json()
        return dict(payload) if isinstance(payload, dict) else {"status": "ok"}

    def list_memory_assertions(self) -> list[dict[str, Any]]:
        return self._get_list("/api/memory/assertions", "items")

    def review_memory_assertion(
        self, assertion_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/memory/assertions/{quote(assertion_id, safe='')}/review",
            {
                "decision": decision,
                "reason": reason,
                "idempotency_key": new_id("cli_review"),
            },
        )

    def list_skill_proposals(self) -> list[dict[str, Any]]:
        return self._get_list("/api/skills/proposals", "items")

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/skills/proposals/{quote(proposal_id, safe='')}")

    def list_skill_releases(self) -> list[dict[str, Any]]:
        return self._get_list("/api/skills/releases", "items")

    def decide_skill_proposal(
        self, proposal_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/skills/proposals/{quote(proposal_id, safe='')}/approve",
            {
                "decision": decision,
                "reason": reason,
                "idempotency_key": new_id("cli_skill"),
            },
        )

    def rollback_skill_release(
        self, release_id: str, *, target_release_id: str, reason: str
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/skills/releases/{quote(release_id, safe='')}/rollback",
            {
                "target_release_id": target_release_id,
                "reason": reason,
                "idempotency_key": new_id("cli_rollback"),
            },
        )

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self._get_list(f"/api/rag/search?query={quote(query)}&limit={limit}", "hits")

    def get_evals_status(self) -> dict[str, Any]:
        return self._get_object("/api/evals/status")

    def list_strategy_cards(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/strategy-cards", "items")

    def get_research_funnel(self) -> dict[str, Any]:
        return self._get_object("/api/research/strategy-cards/funnel")

    def list_strategy_evolution_runs(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/evolution-runs", "items")

    def get_strategy_evolution_run(self, run_id: str) -> dict[str, Any]:
        return self._get_object(
            f"/api/research/evolution-runs/{quote(run_id, safe='')}"
        )

    def list_monitors(self) -> list[dict[str, Any]]:
        return self._get_list("/api/monitors", "items")

    def run_monitor(self, monitor_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/monitors/{monitor_id}/run", {})

    def list_alerts(self) -> list[dict[str, Any]]:
        return self._get_list("/api/alerts", "items")

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return self._get_list("/api/strategy/research", "items")

    def list_strategy_library(self, query: str = "") -> dict[str, Any]:
        suffix = f"?query={quote(query)}" if query else ""
        return self._get_object(f"/api/strategy/library{suffix}")

    def list_backtests(self) -> list[dict[str, Any]]:
        return self._get_list("/api/backtests", "items")

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        return self._post_object("/api/strategy/research", {"prompt": prompt})

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]:
        return self._post_object("/api/strategy/experiments", {"prompt": prompt})

    def create_strategy_iteration(self, prompt: str) -> dict[str, Any]:
        return self._post_object("/api/strategy/experiments/iterate", {"prompt": prompt})

    def list_research_mandates(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/mandates", "items")

    def create_research_mandate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_object("/api/research/mandates", payload)

    def pause_research_mandate(self, mandate_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/research/mandates/{quote(mandate_id, safe='')}/pause", {})

    def resume_research_mandate(self, mandate_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/research/mandates/{quote(mandate_id, safe='')}/resume", {})

    def draft_research_strategy_spec(self, mandate_id: str, prompt: str) -> dict[str, Any]:
        return self._post_object(
            f"/api/research/mandates/{quote(mandate_id, safe='')}/strategy-specs/draft",
            {"prompt": prompt},
        )

    def list_research_jobs(self, mandate_id: str = "") -> list[dict[str, Any]]:
        suffix = f"?mandate_id={quote(mandate_id)}" if mandate_id else ""
        return self._get_list(f"/api/research/jobs{suffix}", "items")

    def queue_research_job(self, mandate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_object(
            f"/api/research/mandates/{quote(mandate_id, safe='')}/jobs", payload
        )

    def cancel_research_job(self, job_id: str, reason: str = "operator_canceled") -> dict[str, Any]:
        return self._post_object(
            f"/api/research/jobs/{quote(job_id, safe='')}/cancel", {"reason": reason}
        )

    def run_research_job(self, job_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/research/jobs/{quote(job_id, safe='')}/run", {})

    def research_job_report(self, job_id: str) -> dict[str, Any]:
        return self._get_object(f"/api/research/jobs/{quote(job_id, safe='')}/report")

    def list_paper_promotions(self) -> list[dict[str, Any]]:
        return self._get_list("/api/research/paper-promotions", "items")

    def request_paper_promotion(self, evidence_id: str, reason: str) -> dict[str, Any]:
        return self._post_object(
            "/api/research/paper-promotions", {"evidence_id": evidence_id, "reason": reason}
        )

    def approve_paper_promotion(
        self, promotion_id: str, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/research/paper-promotions/{quote(promotion_id, safe='')}/approve",
            {"reason": reason, "idempotency_key": idempotency_key},
        )

    def observe_paper_promotion(self, promotion_id: str) -> dict[str, Any]:
        return self._post_object(
            f"/api/research/paper-promotions/{quote(promotion_id, safe='')}/observe", {}
        )

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]:
        return self._post_object(
            "/api/backtests",
            {
                "research_id": research_id,
                "strategy_key": strategy_key,
                "initial_cash": "100000",
                "use_live_candles": use_live_candles,
                "symbol": symbol,
                "bar": bar,
                "candle_limit": candle_limit,
                "candle_source": candle_source,
            },
        )

    def get_status(self) -> dict[str, Any]:
        overview = self._get_object("/api/harness/overview")
        return {
            "mode": "remote",
            "api_url": self.config.api_url,
            "agent_runs": _nested_int(overview, "agent_runs", "total_count"),
            "memory_items": _nested_int(overview, "memory", "active_count"),
            "tools": len(overview.get("tools", []))
            if isinstance(overview.get("tools"), list)
            else 0,
            "tickers": _nested_int(overview, "market", "ticker_count"),
            "latest_market_age_seconds": _nested_value(
                overview,
                "market",
                "latest_update_age_seconds",
            ),
        }

    def get_model_status(self) -> dict[str, Any]:
        overview = self._get_object("/api/harness/overview")
        providers = overview.get("providers", [])
        if not isinstance(providers, list):
            providers = []
        default_provider = next(
            (
                provider
                for provider in providers
                if isinstance(provider, dict) and provider.get("default")
            ),
            providers[0] if providers and isinstance(providers[0], dict) else {},
        )
        return {
            "default_provider": default_provider.get("name", "unknown"),
            "model": default_provider.get("model", "unknown"),
            "providers": [dict(provider) for provider in providers if isinstance(provider, dict)],
        }

    def set_model(self, provider: str, model: str = "") -> dict[str, Any]:
        body = {"provider": provider}
        if model:
            body["model"] = model
        return self._post_object("/api/harness/provider-selection", body)

    def get_market_ticker(self, symbol: str) -> dict[str, Any]:
        return self._get_object(f"/api/market/ticker/{symbol}")

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._get_object(f"/api/market/candles/{symbol}?bar={bar}&limit={limit}")

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        body = {"symbols": symbols, "bar": bar, "limit": limit}
        return self._post_object("/api/market/compare", body)

    def get_paper_status(self) -> dict[str, Any]:
        return self._get_object("/api/paper/status")

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"action": action}
        if symbol:
            body["symbol"] = symbol
        return self._post_object("/api/paper/control", body)

    def list_live_order_intents(self) -> list[dict[str, Any]]:
        return self._get_list("/api/live/order-intents", "items")

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        return self._post_object(
            "/api/live/order-intents",
            {
                "symbol": symbol,
                "side": side,
                "size": size,
                "order_type": order_type,
                "price": price,
                "reason": reason,
            },
        )

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/live/order-intents/{intent_id}/{decision}",
            {"reason": reason},
        )

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/live/order-intents/{intent_id}/execute", {})

    def _url(self, path: str) -> str:
        return f"{self.config.api_url.rstrip('/')}{path}"

    def _get_list(self, path: str, key: str) -> list[dict[str, Any]]:
        payload = self._get_object(path)
        items = payload.get(key, [])
        if not isinstance(items, list):
            raise TypeError(f"{path}.{key} must be a list")
        return [dict(item) for item in items if isinstance(item, dict)]

    def _get_object(self, path: str) -> dict[str, Any]:
        response = self.client.get(self._url(path))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError(f"{path} response must be a JSON object")
        return dict(payload)

    def _post_object(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self._url(path), json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError(f"{path} response must be a JSON object")
        return dict(payload)

    def _put_object(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.put(self._url(path), json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError(f"{path} response must be a JSON object")
        return dict(payload)


def _request_timeout(timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(timeout=timeout_seconds)


def _stream_timeout(*, config: CliConfig) -> httpx.Timeout:
    # Long-running tools such as BitPro backtests may be silent while the server
    # waits for the upstream job. Keep connect/write/pool bounded, but do not
    # abort an active SSE stream merely because no event arrived for a while.
    return httpx.Timeout(timeout=config.timeout_seconds, read=None)


_DEFAULT_DOCKER_DATABASE_URL = (
    "postgresql+psycopg://hypertrade:hypertrade@postgres:5432/hypertrade"
)
_LOCAL_SQLITE_PATH = Path.home() / ".hypertrade" / "local.db"
# backend/src/hypertrade/cli.py -> repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_local_database_url(database_url: str) -> str:
    """Resolve the database URL for the standalone local runtime.

    The compiled default points at the docker-network host `postgres`, which is
    unreachable on an operator laptop. When that exact default survives into
    the local runtime, substitute a per-user SQLite file so bare `ht` works
    outside docker. Any explicitly configured URL is respected as-is.
    """
    if not database_url or database_url == _DEFAULT_DOCKER_DATABASE_URL:
        return f"sqlite:///{_LOCAL_SQLITE_PATH}"
    return database_url


def _ensure_sqlite_schema(database_url: str) -> None:
    """Create the schema for local SQLite databases; idempotent and cheap.

    Production PostgreSQL keeps Alembic-managed schema and must not be touched
    from the CLI bootstrap path.
    """
    if not database_url.startswith("sqlite"):
        return
    path_part = database_url.removeprefix("sqlite:///")
    if path_part and path_part != ":memory:":
        Path(path_part).parent.mkdir(parents=True, exist_ok=True)
    Database(database_url).create_all()


def _local_runtime_settings() -> Settings:
    """Settings for `ht` running standalone from any working directory.

    - Load the repo `.env` when the current directory has none so API keys
      resolve outside the checkout.
    - Replace the docker-network default DATABASE_URL with per-user SQLite and
      ensure its schema; an explicit DATABASE_URL (env or .env) always wins.
    - Resolve docs/knowledge relative to the repo when cwd has no such
      directory so RAG context stays available.
    """
    cwd_env = Path.cwd() / ".env"
    env_file = cwd_env if cwd_env.exists() else _REPO_ROOT / ".env"
    settings = Settings(_env_file=str(env_file))
    database_url = _resolve_local_database_url(str(settings.database_url))
    _ensure_sqlite_schema(database_url)
    knowledge_dir = Path("docs/knowledge")
    if not knowledge_dir.exists():
        knowledge_dir = _REPO_ROOT / "docs" / "knowledge"
    return Settings(
        _env_file=str(env_file),
        DATABASE_URL=database_url,
        KNOWLEDGE_DIR=str(knowledge_dir),
    )


class LocalAgentClient:
    def __init__(self, *, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = db or Database(self.settings.database_url)
        self.selected_provider = self.settings.active_chat_provider
        self.selected_provider_model = ""
        self._mission_runtime: MissionRuntime | None = None
        self._mission_store: InMemoryMissionStore | SqlAlchemyMissionStore | None = None
        self._mission_catalog: InMemoryCapabilityCatalog | SqlCapabilityCatalog | None = None
        self._mission_resources: tuple[object, ...] = ()

    def login(self) -> None:
        return None

    def run_agent(self, prompt: str) -> dict[str, Any]:
        idempotency_key = new_id("local_mission")
        if is_mission_canary(
            enabled=self.settings.mission_runtime_enabled,
            percent=self.settings.mission_runtime_canary_percent,
            idempotency_key=idempotency_key,
        ):
            return asyncio.run(self._run_mission(prompt, idempotency_key=idempotency_key))
        kernel = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
            provider_name=self.selected_provider,
            provider_model=self.selected_provider_model or None,
        )
        task = self._create_agent_task(prompt)
        run = AgentTaskExecutor(self.db).execute_chat(task.id, kernel, prompt)
        return _completed_run_to_dict(run)

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]:
        idempotency_key = new_id("local_mission")
        if is_mission_canary(
            enabled=self.settings.mission_runtime_enabled,
            percent=self.settings.mission_runtime_canary_percent,
            idempotency_key=idempotency_key,
        ):
            mission_run = asyncio.run(self._run_mission(prompt, idempotency_key=idempotency_key))
            for trace in mission_run.get("trace_events", []):
                if isinstance(trace, dict):
                    yield {
                        "event": "mission_event",
                        "mission_id": mission_run.get("mission_id", ""),
                        "tool_name": trace.get("tool_name", ""),
                        "status": trace.get("status", ""),
                    }
            yield {
                "event": "final",
                "mission_id": mission_run.get("mission_id", ""),
                "run": mission_run,
            }
            return
        events: list[dict[str, Any]] = []
        kernel = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
            provider_name=self.selected_provider,
            provider_model=self.selected_provider_model or None,
        )
        task = self._create_agent_task(prompt)
        legacy_run = AgentTaskExecutor(self.db).execute_chat(
            task.id,
            kernel,
            prompt,
            external_event_sink=events.append,
        )
        yield from events
        yield {"event": "final", "task_id": task.id, "run": _completed_run_to_dict(legacy_run)}

    async def _run_mission(self, prompt: str, *, idempotency_key: str) -> dict[str, Any]:
        runtime, store = await self._ensure_mission_runtime()
        mission = await runtime.create(
            mission_request_for_prompt(
                prompt,
                actor="local_cli",
                idempotency_key=idempotency_key,
            )
        )
        completed = await runtime.run(mission.mission_id)
        return await mission_run_projection(completed, store)

    async def _ensure_mission_runtime(
        self,
    ) -> tuple[MissionRuntime, InMemoryMissionStore | SqlAlchemyMissionStore]:
        if self._mission_runtime is not None and self._mission_store is not None:
            return self._mission_runtime, self._mission_store
        in_memory = self.db.url == "sqlite:///:memory:"
        store = InMemoryMissionStore() if in_memory else SqlAlchemyMissionStore(self.db.url)
        catalog = InMemoryCapabilityCatalog() if in_memory else SqlCapabilityCatalog(self.db.url)
        observations = InMemoryObservationStore() if in_memory else SqlObservationStore(self.db.url)
        context_store = (
            InMemoryContextArtifactStore()
            if in_memory
            else SqlContextArtifactStore(self.db.url)
        )
        await catalog.bootstrap(builtin_capabilities())
        runtime = MissionRuntime(
            store,
            ProviderBackedResearchPlanner(
                provider=ProviderRuntime(self.settings).get_chat_provider(
                    selected=self.selected_provider,
                    selected_model=self.selected_provider_model or None,
                )
            ),
            GovernedToolExecutor(
                catalog,
                builtin_handlers(self.db, knowledge_dir=str(self.settings.knowledge_dir)),
                observations=observations,
            ),
            CatalogCapabilityPolicy(catalog),
            ContextArtifactEngine(context_store),
        )
        self._mission_runtime = runtime
        self._mission_store = store
        self._mission_catalog = catalog
        self._mission_resources = (catalog, observations, context_store)
        return runtime, store

    def list_tools(self) -> list[dict[str, Any]]:
        return [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]

    def list_connectors(self) -> dict[str, Any]:
        return ConnectorRegistry.default(settings=self.settings).capabilities_payload()

    def list_runs(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            runs = session.scalars(select(AgentRun).order_by(desc(AgentRun.created_at)).limit(10))
            return [
                {
                    "id": run.id,
                    "status": run.status,
                    "prompt": run.prompt,
                    "created_at": run.created_at.isoformat(),
                }
                for run in runs
            ]

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
            provider_name=self.selected_provider,
            provider_model=self.selected_provider_model or None,
        ).get_run(run_id)
        return _completed_run_to_dict(run)

    def list_agent_sessions(self) -> list[dict[str, Any]]:
        return [session_to_dict(row) for row in AgentSessionService(self.db).list(limit=50)]

    def create_agent_session(self, title: str) -> dict[str, Any]:
        return session_to_dict(
            AgentSessionService(self.db).create(
                AgentSessionCreate(
                    title=title,
                    surface="tui",
                    created_by="tui_operator",
                )
            )
        )

    def list_agent_missions(self) -> list[dict[str, Any]]:
        async def list_rows() -> list[dict[str, Any]]:
            _, store = await self._ensure_mission_runtime()
            rows = await store.list(limit=100)
            return [row.model_dump(mode="json") for row in rows]

        return asyncio.run(list_rows())

    def create_agent_mission(self, objective: str) -> dict[str, Any]:
        async def create() -> dict[str, Any]:
            runtime, _ = await self._ensure_mission_runtime()
            mission = await runtime.create(
                mission_request_for_prompt(
                    objective,
                    actor="tui_operator",
                    idempotency_key=new_id("tui_mission"),
                )
            )
            return mission.model_dump(mode="json")

        return asyncio.run(create())

    def run_agent_mission(self, mission_id: str) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            runtime, _ = await self._ensure_mission_runtime()
            mission = await runtime.run(mission_id)
            return mission.model_dump(mode="json")

        return asyncio.run(run())

    def get_agent_mission(self, mission_id: str) -> dict[str, Any]:
        async def get() -> dict[str, Any]:
            _, store = await self._ensure_mission_runtime()
            mission = await store.get(mission_id)
            plans = await store.plans(mission_id)
            attempts = await store.attempts(mission_id)
            return {
                **mission.model_dump(mode="json"),
                "plans": [plan.model_dump(mode="json") for plan in plans],
                "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
            }

        return asyncio.run(get())

    def list_agent_mission_events(
        self,
        mission_id: str,
        *,
        after: int = 0,
    ) -> list[dict[str, Any]]:
        async def list_events() -> list[dict[str, Any]]:
            _, store = await self._ensure_mission_runtime()
            events = await store.events(mission_id, after=max(after, 0), limit=500)
            return [event.model_dump(mode="json") for event in events]

        return asyncio.run(list_events())

    def stream_agent_mission_events(
        self,
        mission_id: str,
        *,
        after: int = 0,
    ) -> Iterator[dict[str, Any]]:
        for event in self.list_agent_mission_events(mission_id, after=after):
            yield {"event": event.get("event_type", "mission_event"), **event}

    def control_agent_mission(
        self,
        mission_id: str,
        action: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        del reason

        async def control() -> dict[str, Any]:
            runtime, _ = await self._ensure_mission_runtime()
            if action == "pause":
                mission = await runtime.pause(mission_id, actor="tui_operator")
            elif action == "resume":
                mission = await runtime.resume(mission_id, actor="tui_operator")
            elif action == "cancel":
                mission = await runtime.cancel(mission_id, actor="tui_operator")
            else:
                raise ValueError(f"unsupported Mission action: {action}")
            if action in {"pause", "cancel"}:
                mission = await runtime.run(mission.mission_id)
            return mission.model_dump(mode="json")

        return asyncio.run(control())

    def list_agent_tasks(self) -> list[dict[str, Any]]:
        return [task_to_dict(row) for row in AgentTaskService(self.db).list_tasks(limit=100)]

    def create_agent_task(
        self,
        session_id: str,
        objective: str,
        *,
        kind: str = "chat_run",
    ) -> dict[str, Any]:
        if kind not in {"chat_run", "research_graph", "evaluation", "triggered_research"}:
            raise ValueError(f"unknown task kind: {kind}")
        return task_to_dict(
            AgentTaskService(self.db).create(
                AgentTaskCreate(
                    session_id=session_id,
                    kind=cast(Any, kind),
                    objective=objective,
                    idempotency_key=new_id("tui_task"),
                ),
                actor="tui_operator",
            )
        )

    def get_agent_task(self, task_id: str) -> dict[str, Any]:
        return task_to_dict(AgentTaskService(self.db).get(task_id))

    def list_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]:
        return [
            task_event_to_dict(row)
            for row in TaskEventService(self.db).list(task_id, after=max(after, 0), limit=500)
        ]

    def stream_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> Iterator[dict[str, Any]]:
        for event in self.list_agent_task_events(task_id, after=after):
            yield {"event": event["event"], **event}

    def research_graph_topology(self) -> dict[str, Any]:
        return graph_topology_projection()

    def list_research_graphs(self) -> list[dict[str, Any]]:
        return [
            task_to_dict(row)
            for row in AgentTaskService(self.db).list_tasks(kind="research_graph", limit=100)
        ]

    def get_research_graph(self, task_id: str) -> dict[str, Any]:
        return ResearchGraphRuntime(
            self.db,
            provider=DeterministicGapRoleProvider(),
            tool_runner=BuiltinResearchToolRunner(self.db),
        ).projection(task_id)

    def list_experiment_manifests(self) -> list[dict[str, Any]]:
        return ExperimentLedgerService(self.db).list(limit=100)

    def get_experiment_manifest(self, fingerprint: str) -> dict[str, Any]:
        return ExperimentLedgerService(self.db).get(fingerprint)

    def diff_experiment_manifests(
        self, left_fingerprint: str, right_fingerprint: str
    ) -> dict[str, Any]:
        return ExperimentLedgerService(self.db).diff(left_fingerprint, right_fingerprint)

    def list_robustness_validations(self) -> list[dict[str, Any]]:
        return RobustnessValidationService(self.db).list(limit=100)

    def get_robustness_validation(self, validation_id: str) -> dict[str, Any]:
        return RobustnessValidationService(self.db).get(validation_id)

    def list_research_triggers(self) -> dict[str, Any]:
        service = ResearchTriggerService(self.db, settings=self.settings)
        return {
            "items": service.list_triggers(),
            "control": service.control(),
            "feature_enabled": self.settings.research_triggers_enabled,
        }

    def list_research_trigger_fires(self, trigger_id: str = "") -> list[dict[str, Any]]:
        return ResearchTriggerService(self.db, settings=self.settings).list_fires(
            trigger_id=trigger_id
        )

    def set_research_trigger_enabled(
        self, trigger_id: str, *, enabled: bool, reason: str
    ) -> dict[str, Any]:
        return ResearchTriggerService(self.db, settings=self.settings).set_enabled(
            trigger_id,
            enabled=enabled,
            reason=reason,
            actor="cli_operator",
        )

    def set_research_trigger_control(
        self, *, kill_switch: bool, reason: str
    ) -> dict[str, Any]:
        return ResearchTriggerService(self.db, settings=self.settings).set_control(
            TriggerControlUpdate(kill_switch=kill_switch, reason=reason),
            actor="cli_operator",
        )

    def fire_research_trigger(
        self, trigger_id: str, *, reason: str = "operator_run_now"
    ) -> dict[str, Any]:
        service = ResearchTriggerService(self.db, settings=self.settings)
        trigger = service.get(trigger_id)
        return service.fire(
            trigger_id,
            TriggerEvent(
                source_type=cast(Any, trigger["trigger_type"]),
                source_id=new_id("manual"),
                metrics={"operator_reason": reason},
            ),
            actor="cli_operator",
        )

    def control_agent_task(
        self,
        task_id: str,
        action: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        service = AgentTaskService(self.db)
        if action not in {"pause", "resume", "cancel", "retry", "branch"}:
            raise ValueError(f"unknown task control action: {action}")
        row = getattr(service, action)(
            task_id,
            TaskControl(
                reason=reason,
                idempotency_key=new_id("cli"),
                actor="cli_operator",
            ),
        )
        return task_to_dict(row)

    def _create_agent_task(self, prompt: str) -> Any:
        agent_session = AgentSessionService(self.db).create(
            AgentSessionCreate(
                title=prompt.strip()[:200] or "CLI Agent Session",
                surface="cli",
                provider_config={
                    "provider": self.selected_provider,
                    "model": self.selected_provider_model,
                },
                context_policy={"legacy_adapter": True, "max_history_turns": 1},
                created_by="local_cli",
            )
        )
        return AgentTaskService(self.db).create(
            AgentTaskCreate(
                session_id=agent_session.id,
                kind="chat_run",
                objective=prompt,
                idempotency_key=new_id("cli_task"),
            ),
            actor="local_cli",
            start_immediately=True,
        )

    def list_memory(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "kind": item.kind,
                "content": item.content,
                "source_run_id": item.source_run_id,
                "tags": item.tags,
                "usage_count": item.usage_count,
            }
            for item in MemoryService(self.db).list_active()[-10:]
        ]

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "kind": item.kind,
                "content": item.content,
                "source_run_id": item.source_run_id,
                "tags": item.tags,
                "usage_count": item.usage_count,
            }
            for item in MemoryService(self.db).search(query=query)
        ]

    def disable_memory(self, memory_id: str) -> dict[str, Any]:
        MemoryService(self.db).disable(memory_id)
        return {"status": "ok"}

    def list_memory_assertions(self) -> list[dict[str, Any]]:
        return MemoryAssertionService(self.db).list_assertions()

    def review_memory_assertion(
        self, assertion_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject", "dispute"}:
            raise ValueError(f"unsupported assertion decision: {decision}")
        return MemoryAssertionService(self.db).review(
            assertion_id,
            MemoryAssertionReviewV1(
                decision=cast(Any, decision),
                reason=reason,
                idempotency_key=new_id("cli_review"),
            ),
            actor="cli_operator",
        )

    def list_skill_proposals(self) -> list[dict[str, Any]]:
        return SkillLifecycleService(self.db).list_proposals()

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any]:
        return SkillLifecycleService(self.db).get_proposal(proposal_id)

    def list_skill_releases(self) -> list[dict[str, Any]]:
        return SkillLifecycleService(self.db).list_releases()

    def decide_skill_proposal(
        self, proposal_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError(f"unsupported skill decision: {decision}")
        return SkillLifecycleService(self.db).decide(
            proposal_id,
            SkillApprovalV1(
                decision=cast(Any, decision),
                reason=reason,
                idempotency_key=new_id("cli_skill"),
            ),
            actor="cli_operator",
        )

    def rollback_skill_release(
        self, release_id: str, *, target_release_id: str, reason: str
    ) -> dict[str, Any]:
        return SkillLifecycleService(self.db).rollback(
            release_id,
            SkillRollbackV1(
                target_release_id=target_release_id,
                reason=reason,
                idempotency_key=new_id("cli_rollback"),
            ),
            actor="cli_operator",
        )

    def list_portfolio_assessments(self) -> list[dict[str, Any]]:
        return PortfolioAssessmentService(self.db).list_assessments()

    def _portfolio_evidence_service(self) -> PortfolioEvidenceService:
        from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter

        return PortfolioEvidenceService(
            self.db,
            adapter=BitProToolAdapter(BitProMcpClient(settings=self.settings)),
        )

    def list_portfolio_observation_windows(self) -> list[dict[str, Any]]:
        return self._portfolio_evidence_service().list()

    def list_paper_cohorts(self) -> list[dict[str, Any]]:
        return PaperCohortService(self.db).list()

    def list_paper_incubation_mandates(self) -> list[dict[str, Any]]:
        return AutonomousPaperIncubationService(self.db).list()

    def build_paper_cohort(self) -> dict[str, Any]:
        return PaperCohortService(self.db).build(
            PaperCohortBuildV1(idempotency_key=new_id("cli_cohort")),
            actor="cli_operator",
        )

    def get_paper_cohort(self, cohort_id: str) -> dict[str, Any]:
        return PaperCohortService(self.db).get(cohort_id)

    def diff_paper_cohorts(self, left_id: str, right_id: str) -> dict[str, Any]:
        return PaperCohortService(self.db).diff(left_id, right_id)

    def decide_paper_cohort_label(
        self,
        cohort_id: str,
        proposal_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        return PaperCohortService(self.db).decide(
            cohort_id,
            PaperCohortLabelDecisionV1(
                proposal_id=proposal_id,
                decision=cast(Any, decision),
                reason=reason,
                idempotency_key=new_id("cli_cohort_decision"),
            ),
            actor="cli_operator",
        )

    def list_shadow_portfolios(self) -> list[dict[str, Any]]:
        return ShadowPortfolioService(self.db).list_proposals()

    def build_shadow_portfolio(self) -> dict[str, Any]:
        return ShadowPortfolioService(self.db).build(
            ShadowPortfolioBuildV1(idempotency_key=new_id("cli_shadow")),
            actor="cli_operator",
        )

    def get_shadow_portfolio(self, proposal_id: str) -> dict[str, Any]:
        return ShadowPortfolioService(self.db).get(proposal_id)

    def diff_shadow_portfolios(self, left_id: str, right_id: str) -> dict[str, Any]:
        return ShadowPortfolioService(self.db).diff(left_id, right_id)

    def review_shadow_portfolio(
        self,
        proposal_id: str,
        scenario_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        return ShadowPortfolioService(self.db).review(
            proposal_id,
            ShadowPortfolioReviewV1(
                scenario_id=scenario_id,
                decision=cast(Any, decision),
                reason=reason,
                idempotency_key=new_id("cli_shadow_review"),
            ),
            actor="cli_operator",
        )

    def list_regime_shadow_targets(self) -> list[dict[str, Any]]:
        return RegimeShadowAllocatorServiceV2(self.db).list_targets()

    def build_regime_shadow_target(
        self, regime_id: str, cohort_id: str
    ) -> dict[str, Any]:
        return RegimeShadowAllocatorServiceV2(self.db).build(
            RegimeShadowBuildV2(
                decision_at=datetime.now(UTC),
                regime_snapshot_id=regime_id,
                cohort_snapshot_id=cohort_id,
                policy=_default_regime_shadow_policy(),
                idempotency_key=new_id("cli_regime_shadow"),
            ),
            actor="cli_operator",
        )

    def get_regime_shadow_target(self, target_id: str) -> dict[str, Any]:
        return RegimeShadowAllocatorServiceV2(self.db).get(target_id)

    def replay_regime_shadow_target(self, target_id: str) -> dict[str, Any]:
        return RegimeShadowAllocatorServiceV2(self.db).replay(target_id)

    def capture_portfolio_observation_window(self) -> dict[str, Any]:
        return self._portfolio_evidence_service().capture(
            PortfolioObservationCaptureV1(idempotency_key=new_id("cli_window")),
            actor="cli_operator",
        )

    def get_portfolio_observation_window(self, window_id: str) -> dict[str, Any]:
        return self._portfolio_evidence_service().get(window_id)

    def diff_portfolio_observation_windows(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]:
        return self._portfolio_evidence_service().diff(left_id, right_id)

    def create_portfolio_assessment(self) -> dict[str, Any]:
        return PortfolioAssessmentService(self.db).assess(
            PortfolioAssessmentRequestV2(idempotency_key=new_id("cli_portfolio")),
            actor="cli_operator",
        )

    def get_portfolio_assessment(self, assessment_id: str) -> dict[str, Any]:
        return PortfolioAssessmentService(self.db).get(assessment_id)

    def diff_portfolio_assessments(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]:
        return PortfolioAssessmentService(self.db).diff(left_id, right_id)

    def review_portfolio_recommendation(
        self,
        assessment_id: str,
        recommendation_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        if decision not in {"accept", "reject", "hold"}:
            raise ValueError(f"unsupported lifecycle decision: {decision}")
        return PortfolioAssessmentService(self.db).review(
            assessment_id,
            StrategyLifecycleDecisionV1(
                recommendation_id=recommendation_id,
                decision=cast(Any, decision),
                reason=reason,
                idempotency_key=new_id("cli_lifecycle_review"),
            ),
            actor="cli_operator",
        )

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        from hypertrade.rag.service import RagService

        service = RagService(self.db, knowledge_dir=str(self.settings.knowledge_dir))
        service.scan_once()
        return [
            {
                "source_path": hit.source_path,
                "title": hit.title,
                "chunk_index": hit.chunk_index,
                "score": hit.score,
                "content_preview": hit.content_preview,
            }
            for hit in service.search(query, limit=limit)
        ]

    def get_evals_status(self) -> dict[str, Any]:
        return AgentEvalSuite().status()

    def list_strategy_cards(self) -> list[dict[str, Any]]:
        return StrategyCardService(self.db).list()

    def get_research_funnel(self) -> dict[str, Any]:
        return StrategyCardService(self.db).funnel()

    def list_strategy_evolution_runs(self) -> list[dict[str, Any]]:
        from hypertrade.research.evolution import StrategyEvolutionService

        return StrategyEvolutionService(self.db).list()

    def get_strategy_evolution_run(self, run_id: str) -> dict[str, Any]:
        from hypertrade.research.evolution import StrategyEvolutionService

        return StrategyEvolutionService(self.db).get(run_id)

    def list_monitors(self) -> list[dict[str, Any]]:
        from hypertrade.monitoring import MonitorService

        return MonitorService(self.db).list_monitors()

    def run_monitor(self, monitor_id: str) -> dict[str, Any]:
        from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
        from hypertrade.monitoring import MonitorService

        adapter = BitProToolAdapter(BitProMcpClient(settings=self.settings))
        return MonitorService(self.db, bitpro_adapter=adapter).run_monitor(monitor_id)

    def list_alerts(self) -> list[dict[str, Any]]:
        from hypertrade.monitoring import MonitorService

        return MonitorService(self.db).list_alerts()

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return StrategyResearchService(self.db).list_recent(limit=10)

    def list_strategy_library(self, query: str = "") -> dict[str, Any]:
        return StrategyLibraryService(self.db).search(query=query)

    def list_backtests(self) -> list[dict[str, Any]]:
        return BacktestService(self.db).list_recent(limit=10)

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        return StrategyResearchService(self.db).create(prompt)

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]:
        return StrategyExperimentService(self.db).create(prompt)

    def create_strategy_iteration(self, prompt: str) -> dict[str, Any]:
        return StrategyExperimentService(self.db).create_iteration(prompt)

    def list_research_mandates(self) -> list[dict[str, Any]]:
        return ResearchProgramService(self.db).list_mandates()

    def create_research_mandate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ResearchProgramService(self.db).create_mandate(
            ResearchMandateCreate.model_validate(payload)
        )

    def pause_research_mandate(self, mandate_id: str) -> dict[str, Any]:
        return ResearchProgramService(self.db).pause_mandate(mandate_id)

    def resume_research_mandate(self, mandate_id: str) -> dict[str, Any]:
        return ResearchProgramService(self.db).resume_mandate(mandate_id)

    def draft_research_strategy_spec(self, mandate_id: str, prompt: str) -> dict[str, Any]:
        return ResearchProgramService(self.db).draft_strategy_spec(mandate_id, prompt)

    def list_research_jobs(self, mandate_id: str = "") -> list[dict[str, Any]]:
        return ResearchProgramService(self.db).list_jobs(mandate_id=mandate_id)

    def queue_research_job(self, mandate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return ResearchProgramService(self.db).queue_job(
            mandate_id, ResearchJobCreate.model_validate(payload)
        )

    def cancel_research_job(self, job_id: str, reason: str = "operator_canceled") -> dict[str, Any]:
        return ResearchProgramService(self.db).cancel_job(job_id, reason=reason)

    def run_research_job(self, job_id: str) -> dict[str, Any]:
        from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
        from hypertrade.research.orchestrator import ResearchOrchestrator

        return ResearchOrchestrator(
            self.db,
            bitpro_adapter=BitProToolAdapter(BitProMcpClient(settings=self.settings)),
        ).run(job_id)

    def research_job_report(self, job_id: str) -> dict[str, Any]:
        return ResearchProgramService(self.db).report(job_id)

    def list_paper_promotions(self) -> list[dict[str, Any]]:
        return PaperPromotionService(self.db).list()

    def request_paper_promotion(self, evidence_id: str, reason: str) -> dict[str, Any]:
        return PaperPromotionService(self.db).request(evidence_id=evidence_id, reason=reason)

    def approve_paper_promotion(
        self, promotion_id: str, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter

        return PaperPromotionService(
            self.db, bitpro_adapter=BitProToolAdapter(BitProMcpClient(settings=self.settings))
        ).approve(
            promotion_id=promotion_id,
            reason=reason,
            idempotency_key=idempotency_key,
            approved_by="local_operator",
        )

    def observe_paper_promotion(self, promotion_id: str) -> dict[str, Any]:
        from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter

        return PaperPromotionService(
            self.db, bitpro_adapter=BitProToolAdapter(BitProMcpClient(settings=self.settings))
        ).observe(promotion_id)

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]:
        return BacktestService(self.db, settings=self.settings).run(
            research_id=research_id,
            strategy_key=strategy_key,
            use_live_candles=use_live_candles,
            symbol=symbol,
            bar=bar,
            candle_limit=candle_limit,
            candle_source=candle_source,
        )

    def get_status(self) -> dict[str, Any]:
        return {
            "mode": "local",
            "database_url": _redact_database_url(self.settings.database_url),
            "agent_runs": len(self.list_runs()),
            "memory_items": len(self.list_memory()),
            "tools": len(self.list_tools()),
        }

    def get_model_status(self) -> dict[str, Any]:
        selected_models = (
            {self.selected_provider: self.selected_provider_model}
            if self.selected_provider_model
            else {}
        )
        providers = ProviderRuntime(self.settings).list_providers(
            selected=self.selected_provider,
            selected_models=selected_models,
        )
        provider = next(
            (item for item in providers if item.get("name") == self.selected_provider),
            providers[0],
        )
        return {
            "default_provider": provider["name"],
            "model": provider["model"],
            "providers": providers,
        }

    def set_model(self, provider: str, model: str = "") -> dict[str, Any]:
        requested = ProviderRuntime.normalize_provider_name(provider)
        runtime = ProviderRuntime(self.settings)
        providers = runtime.list_providers(selected=requested)
        if requested not in {str(item.get("name")) for item in providers}:
            raise ValueError(f"unknown provider: {provider}")
        selected_model = runtime.validate_model_choice(requested, model)
        self.selected_provider = requested
        self.selected_provider_model = selected_model
        providers = runtime.list_providers(
            selected=requested,
            selected_models={requested: selected_model} if selected_model else {},
        )
        selected = next(item for item in providers if item.get("name") == requested)
        return {
            "default_provider": requested,
            "model": selected.get("model", ""),
            "providers": providers,
        }

    def get_market_ticker(self, symbol: str) -> dict[str, Any]:
        return AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        )._market_ticker_payload(symbol)

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        )._market_candles_payload(symbol=symbol, bar=bar, limit=limit)

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        )._market_compare_payload(symbols=symbols, bar=bar, limit=limit)

    def get_paper_status(self) -> dict[str, Any]:
        from hypertrade.paper.service import PaperTradingService

        return PaperTradingService(self.db, settings=self.settings).status()

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]:
        from hypertrade.paper.service import PaperTradingService

        service = PaperTradingService(self.db, settings=self.settings)
        if action == "pause":
            return service.pause()
        if action == "resume":
            return service.resume()
        if action == "close":
            return service.close(symbol=symbol)
        if action == "reset":
            return service.reset()
        raise ValueError(f"unknown paper action: {action}")

    def list_live_order_intents(self) -> list[dict[str, Any]]:
        from hypertrade.live.service import LiveOrderIntentService

        return LiveOrderIntentService(self.db, settings=self.settings).list_recent()

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        from hypertrade.live.service import LiveOrderIntentService

        return LiveOrderIntentService(self.db, settings=self.settings).create(
            symbol=symbol,
            side=side,
            size=size,
            order_type=order_type,
            price=price,
            reason=reason,
            source="cli",
        )

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        from hypertrade.live.service import LiveOrderIntentService

        service = LiveOrderIntentService(self.db, settings=self.settings)
        if decision == "approve":
            return service.approve(intent_id, reason=reason)
        if decision == "reject":
            return service.reject(intent_id, reason=reason)
        raise ValueError(f"unknown live order decision: {decision}")

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]:
        from hypertrade.live.service import LiveOrderIntentService

        return LiveOrderIntentService(self.db, settings=self.settings).execute(intent_id)


def main(
    argv: Sequence[str] | None = None,
    *,
    client: AgentClient | None = None,
    client_factory: AgentClientFactory | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command in {"login", "/login"}:
        configure_remote_login(input_fn=input_fn, output=output)
        return 0
    config = CliConfig.from_env(api_url=args.remote)
    local = _use_local_runtime(args)
    factory = client_factory or _default_client_factory
    agent_client = client or factory(config, local)

    if args.command == "ask":
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            parser.error("ask requires a prompt")
        agent_client.login()
        if isinstance(agent_client, CanonicalThreadClient):
            thread = agent_client.create_thread(title="CLI ask", retention="ephemeral")
            thread_id = str(thread.get("thread", {}).get("thread_id") or "")
            if not thread_id:
                raise RuntimeError("canonical Thread creation returned no thread_id")
            render_thread_turn_stream(agent_client, thread_id, prompt, output=output)
        else:
            render_run_stream(agent_client, prompt, output=output)
        return 0

    if args.command == "tui":
        agent_client.login()
        try:
            from hypertrade.tui import dependency_error, launch_tui

            launch_tui(agent_client, session_id=str(args.session or ""))
        except ImportError as exc:
            from hypertrade.tui import dependency_error

            raise dependency_error(exc) from exc
        return 0

    run_chat(client=agent_client, input_fn=input_fn, output=output)
    return 0


def configure_remote_login(
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO,
) -> CliConfig:
    api_url = input_fn(f"HyperTrade API URL [{DEFAULT_REMOTE_API_URL}]: ").strip()
    username = input_fn("HyperTrade username [admin]: ").strip()
    password = _read_password(input_fn)
    config = CliConfig(
        api_url=api_url or DEFAULT_REMOTE_API_URL,
        username=username or "admin",
        password=password,
    )
    if not config.password:
        raise SystemExit("HyperTrade password cannot be empty.")
    path = write_client_env(config)
    print(f"HyperTrade login saved: {path}", file=output)
    print("Next time you can run: ht", file=output)
    print('Or one-shot: ht ask "看下 ETH 行情"', file=output)
    return config


def _read_password(input_fn: Callable[[str], str]) -> str:
    if input_fn is input and sys.stdin.isatty():
        return getpass.getpass("HyperTrade password: ").strip()
    return input_fn("HyperTrade password: ").strip()


def run_chat(
    *,
    client: AgentClient,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    client.login()
    render_welcome_banner(client=client, output=output)
    history = configure_interactive_history(enabled=input_fn is input and sys.stdin.isatty())
    thread_client = client if isinstance(client, CanonicalThreadClient) else None
    thread_id = ""
    thread_cursor = 0
    if thread_client is not None:
        thread = thread_client.create_thread(title="CLI chat", retention="durable")
        thread_id = str(thread.get("thread", {}).get("thread_id") or "")
        if not thread_id:
            raise RuntimeError("canonical Thread creation returned no thread_id")
    while True:
        try:
            prompt = input_fn("ht> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("", file=output)
            return
        if prompt.lower() in {"exit", "quit", ":q"}:
            return
        if not prompt:
            continue
        history.add(prompt)
        if prompt.startswith("/"):
            # Slash commands are deterministic shortcuts. They inspect or run a
            # specific tool surface without starting a free-form Agent run.
            handle_slash_command(prompt, client=client, output=output, input_fn=input_fn)
            continue
        if thread_client is not None:
            thread_cursor = render_thread_turn_stream(
                thread_client,
                thread_id,
                prompt,
                after=thread_cursor,
                output=output,
            )
        else:
            render_run_stream(client, prompt, output=output)


def render_welcome_banner(*, client: AgentClient, output: TextIO) -> None:
    color = _banner_colors(output)
    provider, model = _welcome_model_label(client)
    divider = f"{color['border']}{'─' * 72}{color['reset']}"
    print("", file=output)
    print(f"{color['title']}HyperTrade / Operator Console{color['reset']}", file=output)
    print(
        f"{color['subtitle']}Research, evidence, and governed execution{color['reset']}",
        file=output,
    )
    print(divider, file=output)
    print(
        f"{color['label']}MODEL{color['reset']}  {color['value']}{provider} / {model}"
        f"{color['reset']}    {color['label']}WORKSPACE{color['reset']}"
        f"  {color['value']}RESEARCH{color['reset']}",
        file=output,
    )
    print(
        f"{color['label']}EXECUTION{color['reset']}  {color['warning']}PAPER + TESTNET GATED"
        f"{color['reset']}    {color['label']}MAINNET{color['reset']}"
        f"  {color['error']}BLOCKED{color['reset']}",
        file=output,
    )
    print(divider, file=output)
    print(f"{color['section']}START WITH A TASK{color['reset']}", file=output)
    print(
        f"  {color['value']}研究 ETH 的趋势策略，限定 1H 数据并要求样本外验证。{color['reset']}",
        file=output,
    )
    print(
        f"  {color['value']}查看 momentum_breakout 的模拟盘证据，并给出是否需要人工复核。"
        f"{color['reset']}",
        file=output,
    )
    print(f"{color['section']}OPERATOR CONTROLS{color['reset']}", file=output)
    print(
        f"  {color['cmd']}/status{color['reset']}        System posture, risk gates, and session",
        file=output,
    )
    print(
        f"  {color['cmd']}/tasks{color['reset']}         Mission queue and safe-point controls",
        file=output,
    )
    print(
        f"  {color['cmd']}/runs{color['reset']}          Research evidence and trace drill-down",
        file=output,
    )
    print(
        f"  {color['cmd']}/live intents{color['reset']}  Review pending Testnet execution intents",
        file=output,
    )
    print(
        f"  {color['cmd']}/model{color['reset']}         Inspect the active model and provider",
        file=output,
    )
    print(
        f"  {color['cmd']}/help{color['reset']}          Commands, syntax, and safety guardrails",
        file=output,
    )
    print("", file=output)
    print(
        f"{color['muted']}Use natural language for research. "
        f"Type exit, quit, or :q to leave.{color['reset']}",
        file=output,
    )


def _welcome_model_label(client: AgentClient) -> tuple[str, str]:
    """Read only the selected provider label; a banner must not block chat on status failure."""

    try:
        status = client.get_model_status()
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return ("provider", "unavailable")
    provider = str(status.get("default_provider") or "provider").strip() or "provider"
    model = str(status.get("model") or "unavailable").strip() or "unavailable"
    return (provider, model)


def _banner_colors(output: TextIO) -> dict[str, str]:
    colors = _semantic_colors(output)
    return {
        "reset": colors["reset"],
        "border": colors["border"],
        "title": colors["title"],
        "subtitle": colors["subtitle"],
        "section": colors["section"],
        "cmd": colors["command"],
        "label": colors["label"],
        "value": colors["value"],
        "muted": colors["muted"],
        "warning": colors["warning"],
        "error": colors["error"],
    }


def _semantic_colors(output: TextIO) -> dict[str, str]:
    supports_color = not os.getenv("NO_COLOR") and bool(getattr(output, "isatty", lambda: False)())
    keys = (
        "reset",
        "border",
        "title",
        "subtitle",
        "section",
        "command",
        "tool",
        "category",
        "approval",
        "label",
        "value",
        "muted",
        "info",
        "success",
        "warning",
        "error",
    )
    if not supports_color:
        return dict.fromkeys(keys, "")
    return {
        "reset": "\033[0m",
        "border": "\033[38;5;81m",
        "title": "\033[1;38;5;45m",
        "subtitle": "\033[38;5;117m",
        "section": "\033[1;38;5;183m",
        "command": "\033[38;5;121m",
        "tool": "\033[38;5;111m",
        "category": "\033[38;5;110m",
        "approval": "\033[1;38;5;214m",
        "label": "\033[38;5;110m",
        "value": "\033[1;38;5;159m",
        "muted": "\033[38;5;246m",
        "info": "\033[38;5;117m",
        "success": "\033[38;5;120m",
        "warning": "\033[38;5;214m",
        "error": "\033[38;5;203m",
    }


def _paint(text: object, style: str, *, output: TextIO) -> str:
    value = str(text)
    colors = _semantic_colors(output)
    prefix = colors.get(style, "")
    reset = colors.get("reset", "")
    if not prefix:
        return value
    return f"{prefix}{value}{reset}"


def handle_slash_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
    input_fn: Callable[[str], str] | None = None,
    candidate_selected: bool = False,
) -> None:
    selected_candidate = _prompt_slash_candidate_selection(
        command,
        input_fn=input_fn,
        output=output,
    )
    if selected_candidate is not None:
        if selected_candidate:
            handle_slash_command(
                selected_candidate,
                client=client,
                output=output,
                input_fn=input_fn,
                candidate_selected=True,
            )
        return
    name = command.split(maxsplit=1)[0].lower()
    if _slash_argument_candidates(command):
        render_slash_command_candidates(command, output=output)
        return
    # Keep this dispatcher flat and explicit so CLI -> Agent/tool/API wiring is
    # easy to audit during production operations.
    if name in {"/", "/help", "/?", "/commands", "/command"}:
        render_slash_help(output=output)
    elif name == "/status":
        render_status(client.get_status(), output=output)
    elif name == "/model":
        render_model(
            command,
            client=client,
            output=output,
            input_fn=input_fn,
            prompt_model=candidate_selected,
        )
    elif name in {"/provider", "/providers"}:
        render_providers(client.get_model_status(), output=output)
    elif name == "/tools":
        render_tools(client.list_tools(), output=output)
    elif name == "/connectors":
        render_connectors(client.list_connectors(), output=output)
    elif name == "/runs":
        render_runs(client.list_runs(), output=output)
    elif name == "/run":
        handle_run_command(command, client=client, output=output)
    elif name == "/sessions":
        render_agent_sessions(client.list_agent_sessions(), output=output)
    elif name == "/tasks":
        render_agent_tasks(client.list_agent_tasks(), output=output)
    elif name == "/task":
        handle_agent_task_command(command, client=client, output=output)
    elif name in {"/research-graph", "/rg"}:
        handle_research_graph_command(command, client=client, output=output)
    elif name == "/ledger":
        handle_experiment_ledger_command(command, client=client, output=output)
    elif name == "/validations":
        handle_robustness_validation_command(command, client=client, output=output)
    elif name == "/triggers":
        handle_research_trigger_command(command, client=client, output=output)
    elif name == "/memory":
        handle_memory_command(command, client=client, output=output)
    elif name == "/assertions":
        handle_memory_assertion_command(command, client=client, output=output)
    elif name == "/skills":
        handle_skill_command(command, client=client, output=output)
    elif name in {"/portfolio-v2", "/pv2"}:
        handle_portfolio_v2_command(command, client=client, output=output)
    elif name in {"/windows", "/observation-windows"}:
        handle_portfolio_window_command(command, client=client, output=output)
    elif name in {"/cohorts", "/paper-cohorts"}:
        handle_paper_cohort_command(command, client=client, output=output)
    elif name in {"/incubation", "/paper-incubation"}:
        render_paper_incubation_mandates(
            client.list_paper_incubation_mandates(),
            output=output,
        )
    elif name in {"/shadow", "/shadow-portfolios"}:
        handle_shadow_portfolio_command(command, client=client, output=output)
    elif name in {"/regime-shadow", "/shadow-v2"}:
        handle_regime_shadow_command(command, client=client, output=output)
    elif name == "/rag":
        handle_rag_command(command, client=client, output=output)
    elif name in {"/evals", "/eval"}:
        render_evals_status(client.get_evals_status(), output=output)
    elif name in {"/cards", "/strategy-cards"}:
        render_strategy_cards(
            client.list_strategy_cards(),
            client.get_research_funnel(),
            output=output,
        )
    elif name == "/evolution":
        handle_strategy_evolution_command(command, client=client, output=output)
    elif name == "/monitors":
        render_monitors(client.list_monitors(), output=output)
    elif name == "/monitor":
        handle_monitor_command(command, client=client, output=output)
    elif name == "/alerts":
        render_alerts(client.list_alerts(), output=output)
    elif name in {"/strategy", "/strategies"}:
        handle_strategy_command(command, client=client, output=output)
    elif name == "/backtests":
        render_backtests(client.list_backtests(), output=output)
    elif name == "/backtest":
        handle_backtest_command(command, client=client, output=output)
    elif name in {"/research", "/sr"}:
        handle_research_command(command, client=client, output=output)
    elif name in {"/research-program", "/rp"}:
        handle_research_program_command(command, client=client, output=output)
    elif name in {"/experiment", "/exp"}:
        handle_experiment_command(command, client=client, output=output)
    elif name in {"/price", "/ticker"}:
        handle_price_command(command, client=client, output=output)
    elif name in {"/candles", "/kline", "/klines"}:
        handle_candles_command(command, client=client, output=output)
    elif name == "/compare":
        handle_compare_command(command, client=client, output=output)
    elif name == "/paper":
        handle_paper_command(command, client=client, output=output)
    elif name == "/live":
        handle_live_command(command, client=client, output=output)
    elif _looks_like_slash_prefix(command):
        render_slash_command_candidates(command, output=output)
    else:
        print(f"Unknown command: {name}", file=output)
        render_slash_help(output=output)


def render_slash_help(*, output: TextIO) -> None:
    print(_paint("Slash commands:", "section", output=output), file=output)
    command_width = max(len(command) for command, _ in SLASH_COMMAND_HELP)
    for command, description in SLASH_COMMAND_HELP:
        padded_command = f"{command:<{command_width}}"
        print(
            f"- {_paint(padded_command, 'command', output=output)}  "
            f"{_paint(description, 'muted', output=output)}",
            file=output,
        )


def render_slash_command_candidates(prefix: str, *, output: TextIO) -> None:
    matches = _slash_command_candidates(prefix, limit=SLASH_CANDIDATE_LIMIT)
    all_matches = _slash_command_candidates(prefix, limit=None)
    argument_matches = _slash_argument_candidates(prefix, limit=SLASH_CANDIDATE_LIMIT)
    all_argument_matches = _slash_argument_candidates(prefix, limit=None)
    display_prefix = prefix.strip() or "/"
    if all_argument_matches:
        print(
            _paint(
                f"Slash argument candidates for {display_prefix}:",
                "section",
                output=output,
            ),
            file=output,
        )
        argument_width = max(len(candidate) for candidate in argument_matches)
        for index, candidate in enumerate(argument_matches, 1):
            print(
                f"{index}. {_paint(f'{candidate:<{argument_width}}', 'command', output=output)}",
                file=output,
            )
        remaining_arguments = len(all_argument_matches) - len(argument_matches)
        if remaining_arguments > 0:
            print(
                _paint(
                    f"... {remaining_arguments} more matches. Type more characters.",
                    "muted",
                    output=output,
                ),
                file=output,
            )
        print(
            _paint(
                "Tip: press Tab to complete, or type the full argument to run it.",
                "muted",
                output=output,
            ),
            file=output,
        )
        return
    if not all_matches:
        print(
            _paint(f"No slash command matches: {display_prefix}", "warning", output=output),
            file=output,
        )
        print(
            _paint("Type /help to see all commands.", "muted", output=output),
            file=output,
        )
        return

    print(
        _paint(f"Slash command candidates for {display_prefix}:", "section", output=output),
        file=output,
    )
    command_width = max(len(command) for command, _ in matches)
    for index, (command, description) in enumerate(matches, 1):
        padded_command = f"{command:<{command_width}}"
        print(
            f"{index}. {_paint(padded_command, 'command', output=output)}  "
            f"{_paint(description, 'muted', output=output)}",
            file=output,
        )
    remaining = len(all_matches) - len(matches)
    if remaining > 0:
        print(
            _paint(
                f"... {remaining} more matches. Type more characters or use /help.",
                "muted",
                output=output,
            ),
            file=output,
        )
    print(
        _paint(
            "Tip: press Tab to complete, or type the full command to run it.",
            "muted",
            output=output,
        ),
        file=output,
    )


def _prompt_slash_candidate_selection(
    prefix: str,
    *,
    input_fn: Callable[[str], str] | None,
    output: TextIO,
) -> str | None:
    if input_fn is None:
        return None
    argument_matches = _slash_argument_candidates(prefix, limit=SLASH_CANDIDATE_LIMIT)
    if argument_matches:
        render_slash_command_candidates(prefix, output=output)
        selected = _prompt_numbered_candidate(
            argument_matches,
            input_fn=input_fn,
            output=output,
        )
        if selected is None:
            return ""
        command_name = prefix.strip().split(maxsplit=1)[0]
        return f"{command_name} {selected}"

    stripped = prefix.strip()
    name = stripped.split(maxsplit=1)[0].lower() if stripped else ""
    should_prompt_commands = stripped == "/" or (
        _looks_like_slash_prefix(stripped) and name not in SLASH_COMMAND_COMPLETIONS
    )
    if not should_prompt_commands:
        return None
    command_matches = _slash_command_candidates(stripped, limit=SLASH_CANDIDATE_LIMIT)
    if not command_matches:
        return None
    render_slash_command_candidates(stripped, output=output)
    selected = _prompt_numbered_candidate(
        [command for command, _ in command_matches],
        input_fn=input_fn,
        output=output,
    )
    if selected is None:
        return ""
    return _selectable_slash_command(selected)


def _prompt_numbered_candidate(
    candidates: Sequence[str],
    *,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> str | None:
    choice = input_fn("Candidate number (blank to cancel): ").strip()
    if not choice:
        print("Candidate selection canceled.", file=output)
        return None
    selected = _select_numbered_item(choice, candidates)
    if selected is None:
        print("Invalid candidate selection.", file=output)
        return None
    return selected


def _selectable_slash_command(command: str) -> str:
    parts = command.split()
    if not parts:
        return command
    if parts[:2] == ["/live", "intent"]:
        return "/live intent"
    selected: list[str] = []
    for part in parts:
        if any(marker in part for marker in ("<", "[", "|", "*")) or part.startswith("--"):
            break
        selected.append(part)
    return " ".join(selected) if selected else parts[0]


def handle_research_program_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    """Operate research control-plane actions with explicit paper approval only."""
    parts = shlex.split(command)
    subcommand = parts[1].lower() if len(parts) > 1 else "list"
    try:
        if subcommand in {"list", "ls"}:
            print(
                json.dumps(client.list_research_mandates(), ensure_ascii=False, indent=2),
                file=output,
            )
            return
        if subcommand == "create":
            if len(parts) != 3:
                raise ValueError("Usage: /research-program create '<json>'")
            print(
                json.dumps(
                    client.create_research_mandate(json.loads(parts[2])),
                    ensure_ascii=False,
                    indent=2,
                ),
                file=output,
            )
            return
        if subcommand in {"pause", "resume"}:
            if len(parts) != 3:
                raise ValueError(f"Usage: /research-program {subcommand} <rman_id>")
            action = (
                client.pause_research_mandate
                if subcommand == "pause"
                else client.resume_research_mandate
            )
            print(json.dumps(action(parts[2]), ensure_ascii=False, indent=2), file=output)
            return
        if subcommand == "draft":
            if len(parts) < 4:
                raise ValueError("Usage: /research-program draft <rman_id> <prompt>")
            print(
                json.dumps(
                    client.draft_research_strategy_spec(parts[2], " ".join(parts[3:])),
                    ensure_ascii=False,
                    indent=2,
                ),
                file=output,
            )
            return
        if subcommand in {"jobs", "job"}:
            mandate_id = parts[2] if len(parts) == 3 else ""
            if len(parts) > 3:
                raise ValueError("Usage: /research-program jobs [rman_id]")
            print(
                json.dumps(client.list_research_jobs(mandate_id), ensure_ascii=False, indent=2),
                file=output,
            )
            return
        if subcommand == "queue":
            if len(parts) < 5:
                raise ValueError(
                    "Usage: /research-program queue <rman_id> <idempotency_key> <prompt>"
                )
            payload = {"idempotency_key": parts[3], "prompt": " ".join(parts[4:])}
            print(
                json.dumps(
                    client.queue_research_job(parts[2], payload), ensure_ascii=False, indent=2
                ),
                file=output,
            )
            return
        if subcommand in {"run", "report"}:
            if len(parts) != 3:
                raise ValueError(f"Usage: /research-program {subcommand} <rjob_id>")
            result = (
                client.run_research_job(parts[2])
                if subcommand == "run"
                else client.research_job_report(parts[2])
            )
            print(json.dumps(result, ensure_ascii=False, indent=2), file=output)
            return
        if subcommand in {"promotions", "promotion"}:
            print(
                json.dumps(client.list_paper_promotions(), ensure_ascii=False, indent=2),
                file=output,
            )
            return
        if subcommand == "promote":
            if len(parts) < 4:
                raise ValueError("Usage: /research-program promote <rexp_id> <reason>")
            result = client.request_paper_promotion(parts[2], " ".join(parts[3:]))
            print(json.dumps(result, ensure_ascii=False, indent=2), file=output)
            return
        if subcommand == "approve-paper":
            if len(parts) < 5:
                raise ValueError(
                    "Usage: /research-program approve-paper <ppr_id> <idempotency_key> <reason>"
                )
            result = client.approve_paper_promotion(parts[2], " ".join(parts[4:]), parts[3])
            print(json.dumps(result, ensure_ascii=False, indent=2), file=output)
            return
        if subcommand == "observe-paper":
            if len(parts) != 3:
                raise ValueError("Usage: /research-program observe-paper <ppr_id>")
            print(
                json.dumps(client.observe_paper_promotion(parts[2]), ensure_ascii=False, indent=2),
                file=output,
            )
            return
        if subcommand == "cancel":
            if len(parts) < 3:
                raise ValueError("Usage: /research-program cancel <rjob_id> [reason]")
            print(
                json.dumps(
                    client.cancel_research_job(
                        parts[2], " ".join(parts[3:]) or "operator_canceled"
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                file=output,
            )
            return
        raise ValueError(
            "Usage: /research-program list|create|pause|resume|draft|jobs|queue|run|report|"
            "promotions|promote|approve-paper|observe-paper|cancel"
        )
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc), file=output)
    except Exception as exc:  # noqa: BLE001 - print CLI-safe API/service errors
        print(f"Research program command failed: {exc}", file=output)


def handle_research_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        print("Usage: /research <prompt>", file=output)
        print("Example: /research 研究BTC趋势突破策略", file=output)
        return
    try:
        research = client.create_strategy_research(parts[1].strip())
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Research failed: {exc}", file=output)
        return
    render_strategy_research_result(research, output=output)


def handle_experiment_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        print("Usage: /experiment <prompt>", file=output)
        print("Usage: /experiment iterate <prompt>", file=output)
        print("Example: /experiment 研究ETH趋势突破并给出回测改进建议", file=output)
        return
    prompt = parts[1].strip()
    if prompt.lower().startswith("iterate "):
        iteration_prompt = prompt.split(maxsplit=1)[1].strip() if " " in prompt else ""
        if not iteration_prompt:
            print("Usage: /experiment iterate <prompt>", file=output)
            return
        try:
            experiment = client.create_strategy_iteration(iteration_prompt)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Strategy iteration failed: {exc}", file=output)
            return
        render_strategy_iteration_result(experiment, output=output)
        return
    try:
        experiment = client.create_strategy_experiment(prompt)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Experiment failed: {exc}", file=output)
        return
    render_strategy_experiment_result(experiment, output=output)


def handle_monitor_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    subcommand = parts[1].lower() if len(parts) > 1 else "list"
    if subcommand in {"list", "ls"}:
        render_monitors(client.list_monitors(), output=output)
        return
    if subcommand == "run":
        if len(parts) < 3:
            print("Usage: /monitor run <monitor_id>", file=output)
            return
        try:
            result = client.run_monitor(parts[2])
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Monitor run failed: {exc}", file=output)
            return
        render_monitor_run(result, output=output)
        return
    print("Usage: /monitor list|run <monitor_id>", file=output)


def handle_backtest_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    options = _parse_backtest_options(parts)
    positional = options["positionals"]
    if len(parts) == 1:
        _run_backtest_for_target(client, target="latest", options=options, output=output)
        return
    subcommand = str(positional[1]).lower() if len(positional) > 1 else ""
    if subcommand in {"list", "ls"}:
        render_backtests(client.list_backtests(), output=output)
        return
    if subcommand == "run":
        target = str(positional[2]) if len(positional) > 2 else "latest"
        _run_backtest_for_target(client, target=target, options=options, output=output)
        return
    target = str(positional[1]) if len(positional) > 1 else "latest"
    _run_backtest_for_target(client, target=target, options=options, output=output)


def _run_backtest_for_target(
    client: AgentClient,
    *,
    target: str,
    options: dict[str, Any],
    output: TextIO,
) -> None:
    research_id = ""
    strategy_key = "momentum_breakout_v1"
    if target.startswith("srch_"):
        research_id = target
    elif target == "latest":
        latest = _latest_strategy_research(client)
        if latest is None:
            print("No strategy research found. Run /research <prompt> first.", file=output)
            return
        research_id = str(latest["id"])
    else:
        strategy_key = target
    try:
        result = client.run_backtest(
            research_id=research_id,
            strategy_key=strategy_key,
            use_live_candles=bool(options["use_live_candles"]),
            symbol=str(options["symbol"]),
            bar=str(options["bar"]),
            candle_limit=int(options["candle_limit"]),
            candle_source=str(options["candle_source"]),
        )
    except KeyError:
        print(f"Research not found: {research_id}", file=output)
        return
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Backtest failed: {exc}", file=output)
        return
    render_backtest_result(result, output=output)


def handle_price_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    if len(parts) < 2:
        print("Usage: /price <symbol>", file=output)
        print("Example: /price ETH", file=output)
        return
    try:
        render_market_ticker(client.get_market_ticker(parts[1]), output=output)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Price lookup failed: {exc}", file=output)


def handle_candles_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    if len(parts) < 2:
        print("Usage: /candles <symbol> [--bar 1H] [--limit 100]", file=output)
        print("Example: /candles ETH --bar 1H --limit 100", file=output)
        return
    options = _parse_market_options(parts[2:], default_bar="1H", default_limit=100)
    try:
        payload = client.get_market_candles(
            symbol=parts[1],
            bar=str(options["bar"]),
            limit=int(options["limit"]),
        )
        render_market_candles(payload, output=output)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Candle lookup failed: {exc}", file=output)


def handle_compare_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    symbols: list[str] = []
    option_parts: list[str] = []
    index = 1
    while index < len(parts):
        part = parts[index]
        if part.startswith("--"):
            option_parts.extend(parts[index:])
            break
        symbols.append(part)
        index += 1
    if len(symbols) < 2:
        print("Usage: /compare <symbol> <symbol> [more...] [--bar 4H] [--limit 100]", file=output)
        print("Example: /compare ETH SOL --bar 4H --limit 100", file=output)
        return
    options = _parse_market_options(option_parts, default_bar="4H", default_limit=100)
    try:
        payload = client.compare_markets(
            symbols=symbols,
            bar=str(options["bar"]),
            limit=int(options["limit"]),
        )
        render_market_compare(payload, output=output)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Compare failed: {exc}", file=output)


def handle_paper_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    subcommand = parts[1].lower() if len(parts) > 1 else "status"
    if subcommand in {"status", "show"}:
        try:
            render_paper_status(client.get_paper_status(), output=output)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper status failed: {exc}", file=output)
        return
    if subcommand in {"pause", "resume"}:
        try:
            result = client.control_paper(subcommand)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper control failed: {exc}", file=output)
            return
        session = result.get("session", {})
        status = session.get("status", "unknown") if isinstance(session, dict) else "unknown"
        print(f"Paper control: {status}", file=output)
        return
    if subcommand == "close":
        symbol = parts[2] if len(parts) > 2 else None
        try:
            result = client.control_paper("close", symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper close failed: {exc}", file=output)
            return
        print(f"Paper close: {result.get('closed_count', 0)} positions", file=output)
        closed = result.get("closed", [])
        if isinstance(closed, list):
            for row in closed[:10]:
                if not isinstance(row, dict):
                    continue
                print(
                    "- {inst_id} {side} exit={exit_price} realized_pnl={realized_pnl}".format(
                        inst_id=row.get("inst_id", "unknown"),
                        side=row.get("side", "unknown"),
                        exit_price=row.get("exit_price", "n/a"),
                        realized_pnl=row.get("realized_pnl", "n/a"),
                    ),
                    file=output,
                )
        return
    if subcommand == "reset":
        try:
            result = client.control_paper("reset")
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper reset failed: {exc}", file=output)
            return
        session = result.get("session", {})
        session_id = session.get("id", "unknown") if isinstance(session, dict) else "unknown"
        print(f"Paper reset: new session {session_id}", file=output)
        return
    print("Usage: /paper status|pause|resume|close [symbol]|reset", file=output)


def handle_live_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    subcommand = parts[1].lower() if len(parts) > 1 else "intents"
    if subcommand in {"intents", "list", "ls"}:
        try:
            render_live_order_intents(client.list_live_order_intents(), output=output)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live intents failed: {exc}", file=output)
        return
    if subcommand == "intent":
        if len(parts) < 5:
            print(
                "Usage: /live intent <symbol> <buy|sell> <size> [--type market|limit]",
                file=output,
            )
            return
        options = _parse_live_intent_options(parts[5:])
        try:
            intent = client.create_live_order_intent(
                symbol=parts[2],
                side=parts[3],
                size=parts[4],
                order_type=str(options["order_type"]),
                price=options["price"],
                reason=str(options["reason"]),
            )
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live intent failed: {exc}", file=output)
            return
        render_live_order_intent(intent, output=output)
        return
    if subcommand in {"approve", "reject"}:
        if len(parts) < 3:
            print(f"Usage: /live {subcommand} <intent_id> [--reason text]", file=output)
            return
        options = _parse_reason_option(parts[3:])
        try:
            intent = client.decide_live_order_intent(
                parts[2],
                decision=subcommand,
                reason=str(options["reason"]),
            )
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live {subcommand} failed: {exc}", file=output)
            return
        render_live_order_intent(intent, output=output)
        return
    if subcommand == "execute":
        if len(parts) < 3:
            print("Usage: /live execute <intent_id>", file=output)
            return
        try:
            intent = client.execute_live_order_intent(parts[2])
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live execute failed: {exc}", file=output)
            return
        render_live_order_intent(intent, output=output)
        return
    print("Usage: /live intents|intent|approve|reject|execute", file=output)


def _parse_backtest_options(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "positionals": [],
        "use_live_candles": False,
        "symbol": "BTC",
        "bar": "1H",
        "candle_limit": 100,
        "candle_source": "sample",
    }
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--live":
            options["use_live_candles"] = True
            options["candle_source"] = "okx"
        elif part == "--source" and index + 1 < len(parts):
            index += 1
            options["candle_source"] = parts[index].strip().lower()
        elif part == "--symbol" and index + 1 < len(parts):
            index += 1
            options["symbol"] = parts[index]
        elif part == "--bar" and index + 1 < len(parts):
            index += 1
            options["bar"] = parts[index]
        elif part == "--limit" and index + 1 < len(parts):
            index += 1
            options["candle_limit"] = int(parts[index])
        else:
            options["positionals"].append(part)
        index += 1
    return options


def _parse_market_options(
    parts: list[str],
    *,
    default_bar: str,
    default_limit: int,
) -> dict[str, Any]:
    options: dict[str, Any] = {"bar": default_bar, "limit": default_limit}
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--bar" and index + 1 < len(parts):
            index += 1
            options["bar"] = parts[index]
        elif part == "--limit" and index + 1 < len(parts):
            index += 1
            options["limit"] = int(parts[index])
        index += 1
    return options


def _parse_live_intent_options(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {"order_type": "market", "price": None, "reason": ""}
    index = 0
    while index < len(parts):
        part = parts[index]
        if part in {"--type", "--order-type"} and index + 1 < len(parts):
            index += 1
            options["order_type"] = parts[index]
        elif part == "--price" and index + 1 < len(parts):
            index += 1
            options["price"] = parts[index]
        elif part == "--reason" and index + 1 < len(parts):
            options["reason"] = " ".join(parts[index + 1 :])
            break
        index += 1
    return options


def _parse_reason_option(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {"reason": ""}
    if "--reason" in parts:
        index = parts.index("--reason")
        options["reason"] = " ".join(parts[index + 1 :])
    return options


def handle_memory_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=2)
    if len(parts) == 1:
        render_memory(client.list_memory(), output=output)
        return
    subcommand = parts[1].lower()
    if subcommand == "search":
        if len(parts) < 3 or not parts[2].strip():
            print("Usage: /memory search <query>", file=output)
            return
        render_memory(client.search_memory(parts[2].strip()), output=output)
        return
    if subcommand == "disable":
        if len(parts) < 3 or not parts[2].strip():
            print("Usage: /memory disable <mem_id>", file=output)
            return
        result = client.disable_memory(parts[2].strip())
        print(f"Memory disable: {result.get('status', 'ok')}", file=output)
        return
    print("Usage: /memory [search <query>|disable <mem_id>]", file=output)


def handle_rag_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        print("Usage: /rag <query>", file=output)
        return
    render_rag_hits(client.search_rag(parts[1].strip()), output=output)


def handle_strategy_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=2)
    if len(parts) >= 2 and parts[1].lower() in {"library", "lib", "memory"}:
        query = parts[2].strip() if len(parts) >= 3 else ""
        render_strategy_library(client.list_strategy_library(query), output=output)
        return
    render_strategy_research(client.list_strategy_research(), output=output)


def _latest_strategy_research(client: AgentClient) -> dict[str, Any] | None:
    items = client.list_strategy_research()
    return items[0] if items else None


def render_strategy_research_result(research: dict[str, Any], *, output: TextIO) -> None:
    print("Strategy research created:", file=output)
    print(f"- ID: {research.get('id', 'unknown')}", file=output)
    print(f"- Strategy: {research.get('strategy_key', 'unknown')}", file=output)
    print(f"- Title: {research.get('title', '')}", file=output)
    print("- Next: /backtest latest", file=output)
    print("", file=output)
    _render_markdown_report(
        str(research.get("report_markdown", "")),
        output=output,
        title="Strategy Research",
    )


def render_strategy_experiment_result(experiment: dict[str, Any], *, output: TextIO) -> None:
    print("Strategy experiment completed:", file=output)
    print(f"- ID: {experiment.get('id', 'unknown')}", file=output)
    print(f"- Research: {experiment.get('research_id', 'n/a')}", file=output)
    print(f"- Backtest: {experiment.get('backtest_id', 'n/a')}", file=output)
    print(f"- Status: {experiment.get('status', 'unknown')}", file=output)
    print("", file=output)
    _render_markdown_report(
        str(experiment.get("report_markdown", "")),
        output=output,
        title="Strategy Experiment",
    )


def render_strategy_iteration_result(experiment: dict[str, Any], *, output: TextIO) -> None:
    print("Strategy iteration completed:", file=output)
    print(f"- ID: {experiment.get('id', 'unknown')}", file=output)
    print(f"- Research: {experiment.get('research_id', 'n/a')}", file=output)
    print(f"- Backtest: {experiment.get('backtest_id', 'n/a')}", file=output)
    print(f"- Status: {experiment.get('status', 'unknown')}", file=output)
    print("", file=output)
    _render_markdown_report(
        str(experiment.get("report_markdown", "")),
        output=output,
        title="Strategy Iteration",
    )


def render_backtest_result(result: dict[str, Any], *, output: TextIO) -> None:
    metrics = result.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    print("Backtest completed:", file=output)
    print(f"- ID: {result.get('id', 'unknown')}", file=output)
    print(f"- Research: {result.get('research_id') or 'n/a'}", file=output)
    print(f"- Strategy: {result.get('strategy_key', 'unknown')}", file=output)
    print(f"- Return: {metrics.get('total_return_pct', 'n/a')}%", file=output)
    print(f"- Trades: {metrics.get('trade_count', 'n/a')}", file=output)
    print("", file=output)
    _render_markdown_report(
        str(result.get("report_markdown", "")),
        output=output,
        title="Backtest Report",
    )


def render_market_ticker(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Price:", file=output)
    if not payload.get("found", True):
        print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
        reason = payload.get("unavailable_reason", "not found")
        print(f"- Status: unavailable ({reason})", file=output)
        return
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Last: {payload.get('last', 'n/a')}", file=output)
    print(f"- UTC0 change: {payload.get('change_utc0_pct', 'n/a')}%", file=output)
    print(f"- 24h volume: {payload.get('volume_ccy_24h', 'n/a')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)
    print(f"- As of UTC: {payload.get('as_of_utc', 'n/a')}", file=output)


def render_market_candles(payload: dict[str, Any], *, output: TextIO) -> None:
    print("K-line trend:", file=output)
    if not payload.get("found", True):
        print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
        reason = payload.get("unavailable_reason", "not found")
        print(f"- Status: unavailable ({reason})", file=output)
        return
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Candles: {payload.get('candle_count', 'n/a')}", file=output)
    print(f"- Return: {payload.get('return_pct', 'n/a')}%", file=output)
    print(f"- Range: {payload.get('range_pct', 'n/a')}%", file=output)
    print(f"- Close position: {payload.get('close_position_pct', 'n/a')}%", file=output)
    print(f"- MA20: {payload.get('ma20', 'n/a')}", file=output)
    print(f"- MA60: {payload.get('ma60', 'n/a')}", file=output)
    print(f"- Bias: {payload.get('trend_bias', 'unknown')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)


def render_market_compare(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Relative strength:", file=output)
    if not payload.get("found", True):
        print("- Status: unavailable", file=output)
        return
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Leader: {payload.get('leader', 'unknown')}", file=output)
    rankings = payload.get("rankings", [])
    if isinstance(rankings, list):
        for row in rankings:
            if not isinstance(row, dict):
                continue
            print(
                "- {rank}. {inst_id}: score={score}, return={return_pct}%, "
                "close_position={close_position_pct}%, bias={trend_bias}".format(
                    rank=row.get("rank", "?"),
                    inst_id=row.get("inst_id", "unknown"),
                    score=row.get("strength_score", "n/a"),
                    return_pct=row.get("return_pct", "n/a"),
                    close_position_pct=row.get("close_position_pct", "n/a"),
                    trend_bias=row.get("trend_bias", "unknown"),
                ),
                file=output,
            )
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)


def render_paper_status(payload: dict[str, Any], *, output: TextIO) -> None:
    session = payload.get("session", {})
    if not isinstance(session, dict):
        session = {}
    print("Paper trading:", file=output)
    print(f"- Session: {session.get('id', 'unknown')}", file=output)
    print(f"- Status: {session.get('status', 'unknown')}", file=output)
    print(f"- Cash: {session.get('cash', 'n/a')}", file=output)
    print(f"- Equity: {session.get('equity', 'n/a')}", file=output)
    print(f"- Realized PnL: {session.get('realized_pnl', 'n/a')}", file=output)

    positions = payload.get("positions", [])
    print("Positions:", file=output)
    if isinstance(positions, list) and positions:
        for row in positions[:10]:
            if not isinstance(row, dict):
                continue
            print(
                "- {inst_id} {side} qty={quantity} entry={entry} mark={mark} pnl={pnl}".format(
                    inst_id=row.get("inst_id", "unknown"),
                    side=row.get("side", "unknown"),
                    quantity=row.get("quantity", "n/a"),
                    entry=row.get("entry_price", "n/a"),
                    mark=row.get("mark_price", "n/a"),
                    pnl=row.get("unrealized_pnl", "n/a"),
                ),
                file=output,
            )
    else:
        print("- none", file=output)

    fills = payload.get("recent_fills", [])
    print("Recent fills:", file=output)
    if isinstance(fills, list) and fills:
        for row in fills[:5]:
            if not isinstance(row, dict):
                continue
            print(
                "- {inst_id} {side} qty={quantity} price={price} fee={fee}".format(
                    inst_id=row.get("inst_id", "unknown"),
                    side=row.get("side", "unknown"),
                    quantity=row.get("quantity", "n/a"),
                    price=row.get("price", "n/a"),
                    fee=row.get("fee", "n/a"),
                ),
                file=output,
            )
    else:
        print("- none", file=output)

    events = payload.get("recent_events", [])
    print("Recent events:", file=output)
    if isinstance(events, list) and events:
        for row in events[:5]:
            if not isinstance(row, dict):
                continue
            print(f"- {row.get('kind', 'event')}: {row.get('message', '')}", file=output)
    else:
        print("- none", file=output)


def render_live_order_intents(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Live order intents:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:20]:
        render_live_order_intent(item, output=output)


def render_live_order_intent(intent: dict[str, Any], *, output: TextIO) -> None:
    print(
        "- {id} {status} {environment} {inst_id} {side} {size} {order_type}{price}".format(
            id=intent.get("id", "unknown"),
            status=intent.get("status", "unknown"),
            environment=intent.get("environment", "unknown"),
            inst_id=intent.get("inst_id", "unknown"),
            side=intent.get("side", "unknown"),
            size=intent.get("size", "n/a"),
            order_type=intent.get("order_type", "market"),
            price=f" price={intent.get('price')}" if intent.get("price") else "",
        ),
        file=output,
    )
    reason = intent.get("reason")
    if reason:
        print(f"  reason: {reason}", file=output)
    decision_reason = intent.get("decision_reason")
    if decision_reason:
        print(f"  decision: {decision_reason}", file=output)
    risk_status = intent.get("risk_status")
    if risk_status:
        print(f"  risk: {risk_status}", file=output)
    exchange_order_id = intent.get("exchange_order_id")
    if exchange_order_id:
        print(f"  exchange_order_id: {exchange_order_id}", file=output)


def render_status(status: dict[str, Any], *, output: TextIO) -> None:
    print("Status:", file=output)
    print(f"- Mode: {status.get('mode', 'unknown')}", file=output)
    if status.get("api_url"):
        print(f"- API: {status.get('api_url')}", file=output)
    if status.get("database_url"):
        print(f"- Database: {status.get('database_url')}", file=output)
    print(f"- Agent runs: {status.get('agent_runs', 'n/a')}", file=output)
    print(f"- Memory items: {status.get('memory_items', 'n/a')}", file=output)
    print(f"- Tools: {status.get('tools', 'n/a')}", file=output)
    if status.get("tickers") is not None:
        print(f"- Tickers: {status.get('tickers')}", file=output)


def render_model(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
    input_fn: Callable[[str], str] | None = None,
    prompt_model: bool = False,
) -> None:
    parts = command.split(maxsplit=1)
    status = client.get_model_status()
    if len(parts) == 1:
        print("Model:", file=output)
        print(f"- Provider: {status.get('default_provider', 'unknown')}", file=output)
        print(f"- Model: {status.get('model', 'unknown')}", file=output)
        if input_fn is None:
            print("- Switch: /model <provider>", file=output)
            _render_model_provider_list(status, output=output)
        else:
            _prompt_model_selection(status, client=client, input_fn=input_fn, output=output)
        return
    requested_provider, requested_model = _parse_model_selection_argument(parts[1].strip())
    if prompt_model and input_fn is not None and not requested_model:
        provider = _find_provider_status(status, requested_provider)
        if provider is not None:
            selected_model = _prompt_provider_model(provider, input_fn=input_fn, output=output)
            if selected_model is None:
                return
            requested_model = selected_model
    try:
        switched = client.set_model(requested_provider, requested_model)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Model switch failed: {exc}", file=output)
        return
    print(f"Model switched: {switched.get('default_provider', requested_provider)}", file=output)
    print(f"- Model: {switched.get('model', 'unknown')}", file=output)


def _prompt_model_selection(
    status: dict[str, Any],
    *,
    client: AgentClient,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> None:
    providers = _provider_options(status)
    if not providers:
        print("Select provider:", file=output)
        print("- none", file=output)
        return
    _render_model_provider_list(status, output=output)
    choice = input_fn("Provider number (blank to cancel): ").strip()
    if not choice:
        print("Model selection canceled.", file=output)
        return
    selected_provider = _select_numbered_item(choice, providers)
    if selected_provider is None:
        print("Invalid provider selection.", file=output)
        return

    provider_name = str(selected_provider.get("name", ""))
    selected_model = _prompt_provider_model(selected_provider, input_fn=input_fn, output=output)
    if selected_model is None:
        return
    try:
        switched = client.set_model(provider_name, selected_model)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Model switch failed: {exc}", file=output)
        return
    print(f"Model switched: {switched.get('default_provider', provider_name)}", file=output)
    print(f"- Model: {switched.get('model', 'unknown')}", file=output)


def _prompt_provider_model(
    provider: dict[str, Any],
    *,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> str | None:
    model_options = [str(option) for option in provider.get("model_options", []) if str(option)]
    if len(model_options) <= 1:
        return model_options[0] if model_options else ""
    display_name = str(provider.get("display_name") or provider.get("name") or "Provider")
    current_model = str(provider.get("model") or "")
    print(f"Select {display_name} model:", file=output)
    for index, model in enumerate(model_options, 1):
        current = " current" if model == current_model else ""
        print(f"{index}. {model}{current}", file=output)
    choice = input_fn("Model number (blank to cancel): ").strip()
    if not choice:
        print("Model selection canceled.", file=output)
        return None
    selected_model = _select_numbered_item(choice, model_options)
    if selected_model is None:
        print("Invalid model selection.", file=output)
        return None
    return selected_model


def _render_model_provider_list(status: dict[str, Any], *, output: TextIO) -> None:
    providers = _provider_options(status)
    print("Select provider:", file=output)
    if not providers:
        print("- none", file=output)
        return
    for index, provider in enumerate(providers, 1):
        name = provider.get("name", "unknown")
        model = provider.get("model", "unknown")
        enabled = "enabled" if provider.get("enabled") else "disabled"
        current = " current" if provider.get("default") else ""
        print(f"{index}. {name} ({model}, {enabled}{current})", file=output)


def _provider_options(status: dict[str, Any]) -> list[dict[str, Any]]:
    providers = status.get("providers", [])
    if not isinstance(providers, list):
        return []
    return [dict(provider) for provider in providers if isinstance(provider, dict)]


def _find_provider_status(status: dict[str, Any], provider_name: str) -> dict[str, Any] | None:
    normalized = ProviderRuntime.normalize_provider_name(provider_name)
    for provider in _provider_options(status):
        if ProviderRuntime.normalize_provider_name(str(provider.get("name", ""))) == normalized:
            return provider
    return None


def _select_numbered_item[T](choice: str, items: Sequence[T]) -> T | None:
    try:
        index = int(choice)
    except ValueError:
        return None
    if index < 1 or index > len(items):
        return None
    return items[index - 1]


def _parse_model_selection_argument(argument: str) -> tuple[str, str]:
    if ":" not in argument:
        return argument, ""
    provider, model = argument.split(":", 1)
    return provider.strip(), model.strip()


def render_providers(status: dict[str, Any], *, output: TextIO) -> None:
    print("Providers:", file=output)
    providers = status.get("providers", [])
    if not isinstance(providers, list) or not providers:
        print("- none", file=output)
        return
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        default = " default" if provider.get("default") else ""
        enabled = "enabled" if provider.get("enabled") else "disabled"
        print(
            f"- {provider.get('name', 'unknown')} {provider.get('model', 'unknown')} "
            f"{enabled}{default}",
            file=output,
        )


def render_tools(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print(_paint("Tools:", "section", output=output), file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items:
        description = str(item.get("description") or "No description configured.")
        policy = item.get("policy")
        policy = policy if isinstance(policy, dict) else {}
        approval = str(
            policy.get(
                "approval",
                "required" if item.get("requires_approval") else "none",
            )
        )
        policy_text = (
            f"scope={policy.get('scope', 'unknown')} "
            f"approval={approval} "
            f"idempotency={policy.get('idempotency', 'unknown')}"
        )
        policy_style = "approval" if approval == "required" else "muted"
        name = _paint(item.get("name", "unknown"), "tool", output=output)
        category = _paint(f"[{item.get('category', 'unknown')}]", "category", output=output)
        print(
            f"- {name} {category} {_paint(policy_text, policy_style, output=output)}: "
            f"{_paint(description, 'muted', output=output)}",
            file=output,
        )


def render_connectors(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Connectors:", file=output)
    connectors = payload.get("connectors", {})
    if not isinstance(connectors, dict) or not connectors:
        print("- none", file=output)
        return
    for connector_id, raw_capability in sorted(connectors.items()):
        capability = raw_capability if isinstance(raw_capability, dict) else {}
        auth = capability.get("auth", {})
        auth_payload = auth if isinstance(auth, dict) else {}
        health = capability.get("health", {})
        health_payload = health if isinstance(health, dict) else {}
        tools = capability.get("tools", [])
        tool_payloads = (
            [tool for tool in tools if isinstance(tool, dict)] if isinstance(tools, list) else []
        )
        scopes = capability.get("supported_scopes", [])
        scope_text = ",".join(str(scope) for scope in scopes) if isinstance(scopes, list) else "n/a"
        auth_status = "configured" if auth_payload.get("configured") else "not_configured"
        print(
            f"- {connector_id} {capability.get('display_name', connector_id)} "
            f"health={health_payload.get('status', 'unknown')} "
            f"auth={auth_status} scopes={scope_text}",
            file=output,
        )
        for tool in tool_payloads[:8]:
            safe_read = "yes" if tool.get("safe_read") else "no"
            idempotency = "required" if tool.get("idempotency_required") else "not_required"
            print(
                f"  - {tool.get('name', 'unknown')} scope={tool.get('scope', 'unknown')} "
                f"safe_read={safe_read} idempotency={idempotency}",
                file=output,
            )


def render_runs(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Recent runs:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            f"- {item.get('id', 'unknown')} {item.get('status', 'unknown')}: "
            f"{str(item.get('prompt', ''))[:80]}",
            file=output,
        )


def render_agent_sessions(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Agent sessions:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:20]:
        print(
            f"- {item.get('id', 'unknown')} [{item.get('status', 'unknown')}] "
            f"{item.get('surface', 'unknown')}: {str(item.get('title', ''))[:80]}",
            file=output,
        )


def render_agent_tasks(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Agent tasks:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:20]:
        resource = ""
        if item.get("resource_id"):
            resource = f" -> {item.get('resource_type')}:{item.get('resource_id')}"
        print(
            f"- {item.get('id', 'unknown')} [{item.get('status', 'unknown')}] "
            f"{item.get('kind', 'unknown')}{resource}: "
            f"{str(item.get('objective', ''))[:80]}",
            file=output,
        )


def handle_agent_task_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split(maxsplit=3)
    if len(parts) < 2:
        print(
            "Usage: /task <task_id> [pause|resume|cancel|retry|branch] [reason]",
            file=output,
        )
        return
    task_id = parts[1].strip()
    try:
        if len(parts) == 2:
            item = client.get_agent_task(task_id)
        else:
            action = parts[2].strip().lower()
            if action not in {"pause", "resume", "cancel", "retry", "branch"}:
                print(f"Unknown task action: {action}", file=output)
                return
            reason = parts[3].strip() if len(parts) == 4 else f"cli_{action}"
            item = client.control_agent_task(task_id, action, reason=reason)
    except KeyError:
        print(f"Task not found: {task_id}", file=output)
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            print(f"Task not found: {task_id}", file=output)
            return
        if exc.response.status_code == 409:
            print(f"Task control rejected: {exc.response.text}", file=output)
            return
        raise
    print(
        f"Task {item.get('id', task_id)} [{item.get('status', 'unknown')}]",
        file=output,
    )
    print(f"- objective: {item.get('objective', '')}", file=output)
    print(f"- session: {item.get('session_id') or 'background'}", file=output)
    print(f"- events: {item.get('last_event_sequence', 0)}", file=output)
    print(f"- checkpoint: {item.get('last_checkpoint_id') or 'none'}", file=output)
    if item.get("error"):
        print(f"- error: {json.dumps(item['error'], ensure_ascii=False)}", file=output)


def handle_research_graph_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split(maxsplit=2)
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "topology":
        payload = client.research_graph_topology()
        roles = payload.get("roles", [])
        print(
            f"Research graph {str(payload.get('catalog_hash', ''))[:12]} "
            f"({len(roles)} fixed roles)",
            file=output,
        )
        for role in roles:
            print(
                f"- {role.get('key')} [{role.get('version')}] "
                f"required={role.get('required')} "
                f"prompt={str(role.get('prompt_hash', ''))[:12]}",
                file=output,
            )
        return
    if action == "list":
        render_agent_tasks(client.list_research_graphs(), output=output)
        return
    if action != "show" or len(parts) < 3:
        print("Usage: /research-graph topology|list|show <task_id>", file=output)
        return
    task_id = parts[2].strip()
    payload = client.get_research_graph(task_id)
    task = dict(payload.get("task", {}))
    nodes = payload.get("nodes", [])
    evidence = payload.get("evidence", [])
    print(
        f"Research graph {task.get('id', task_id)} [{task.get('status', 'unknown')}]",
        file=output,
    )
    print(
        f"- nodes: {len(nodes)}; evidence: {len(evidence)}; "
        f"usage: {json.dumps(task.get('usage', {}), ensure_ascii=False)}",
        file=output,
    )
    for node in nodes:
        output_ref = dict(node.get("output_ref", {}))
        print(
            f"- {node.get('role_key')} attempt={node.get('attempt')} "
            f"[{node.get('status')}] "
            f"evidence={len(output_ref.get('evidence_ids', []))}",
            file=output,
        )


def handle_strategy_evolution_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_strategy_evolution_runs()
        print("Strategy evolution runs:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:20]:
            assessment = dict(row.get("assessment", {}))
            usage = dict(row.get("usage", {}))
            print(
                f"- {row.get('id')} [{row.get('status')}] "
                f"decay={assessment.get('classification', 'unknown')} "
                f"accepted={usage.get('accepted', 0)} rejected={usage.get('rejected', 0)}",
                file=output,
            )
        return
    if action == "show" and len(parts) == 3:
        row = client.get_strategy_evolution_run(parts[2])
        assessment = dict(row.get("assessment", {}))
        print(
            f"Strategy evolution {row.get('id', parts[2])} [{row.get('status')}] "
            f"decay={assessment.get('classification', 'unknown')}",
            file=output,
        )
        for candidate in row.get("candidates", []):
            print(
                f"- {str(candidate.get('fingerprint', ''))[:16]} "
                f"[{candidate.get('status')}] kind={candidate.get('proposal_kind')} "
                f"version={candidate.get('candidate_version_id') or 'none'} "
                f"rejections={','.join(candidate.get('rejection_reasons', [])) or 'none'}",
                file=output,
            )
        print("- execution_authorized=false", file=output)
        return
    print("Usage: /evolution list|show <run_id>", file=output)


def handle_experiment_ledger_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_experiment_manifests()
        print("Experiment manifests:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:20]:
            print(
                f"- {row.get('fingerprint', '')[:16]} "
                f"{row.get('strategy_key', '')} manifest={row.get('id', '')}",
                file=output,
            )
        return
    if action == "show" and len(parts) == 3:
        payload = client.get_experiment_manifest(parts[2])
        manifest = dict(payload.get("manifest", {}))
        executions = payload.get("executions", [])
        print(
            f"Experiment {manifest.get('fingerprint', parts[2])} "
            f"strategy={manifest.get('strategy_key', '')}",
            file=output,
        )
        for execution in executions:
            print(
                f"- attempt={execution.get('attempt')} [{execution.get('status')}] "
                f"execution={execution.get('id')} evidence={len(execution.get('evidence', []))}",
                file=output,
            )
        return
    if action == "diff" and len(parts) == 4:
        payload = client.diff_experiment_manifests(parts[2], parts[3])
        print(
            f"Manifest diff equal={payload.get('equal')} changes={len(payload.get('changes', []))}",
            file=output,
        )
        for change in payload.get("changes", [])[:50]:
            print(
                f"- [{change.get('category')}] {change.get('path')}: "
                f"{change.get('left')} -> {change.get('right')}",
                file=output,
            )
        return
    print("Usage: /ledger list|show <fingerprint>|diff <left> <right>", file=output)


def handle_robustness_validation_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_robustness_validations()
        print("Robustness validations:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:20]:
            print(
                f"- {row.get('id')} [{row.get('final_status')}] "
                f"fingerprint={str(row.get('fingerprint', ''))[:16]}",
                file=output,
            )
        return
    if action == "show" and len(parts) == 3:
        row = client.get_robustness_validation(parts[2])
        summary = dict(row.get("summary", {}))
        print(
            f"Validation {row.get('id')} [{row.get('final_status')}] "
            f"scenarios={summary.get('scenario_count', 0)}",
            file=output,
        )
        for name, gate in sorted(dict(row.get("gates", {})).items()):
            print(
                f"- {name}: {gate.get('outcome')} required={gate.get('required')}",
                file=output,
            )
        return
    print("Usage: /validations list|show <validation_id>", file=output)


def handle_research_trigger_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split(maxsplit=3)
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        payload = client.list_research_triggers()
        control = dict(payload.get("control", {}))
        print(
            "Research triggers: "
            f"feature_enabled={payload.get('feature_enabled', False)} "
            f"kill_switch={control.get('kill_switch', False)}",
            file=output,
        )
        rows = payload.get("items", [])
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} [{('enabled' if row.get('enabled') else 'disabled')}] "
                f"{row.get('trigger_type')} {row.get('name')} "
                f"next={row.get('next_run_at') or '-'}",
                file=output,
            )
        return
    if action == "fires":
        trigger_id = parts[2] if len(parts) > 2 else ""
        rows = client.list_research_trigger_fires(trigger_id)
        print("Research trigger fires:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} [{row.get('status')}] trigger={row.get('trigger_id')} "
                f"task={row.get('task_id') or '-'} reason={row.get('reason') or '-'}",
                file=output,
            )
        return
    if action in {"enable", "disable"} and len(parts) >= 3:
        reason = parts[3] if len(parts) > 3 else f"cli_{action}"
        row = client.set_research_trigger_enabled(
            parts[2],
            enabled=action == "enable",
            reason=reason,
        )
        print(
            f"Trigger {row.get('id')} "
            f"[{'enabled' if row.get('enabled') else 'disabled'}]",
            file=output,
        )
        return
    if action == "run" and len(parts) >= 3:
        reason = parts[3] if len(parts) > 3 else "cli_run_now"
        row = client.fire_research_trigger(parts[2], reason=reason)
        print(
            f"Trigger fire {row.get('id')} [{row.get('status')}] "
            f"task={row.get('task_id') or '-'} reason={row.get('reason') or '-'}",
            file=output,
        )
        return
    if action == "kill" and len(parts) >= 3 and parts[2].lower() in {"on", "off"}:
        reason = parts[3] if len(parts) > 3 else f"cli_kill_{parts[2].lower()}"
        row = client.set_research_trigger_control(
            kill_switch=parts[2].lower() == "on",
            reason=reason,
        )
        print(
            f"Trigger kill switch={row.get('kill_switch')} reason={row.get('reason')}",
            file=output,
        )
        return
    print(
        "Usage: /triggers list|fires [id]|enable|disable <id> [reason]|"
        "run <id>|kill on|off [reason]",
        file=output,
    )


def handle_memory_assertion_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split(maxsplit=3)
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_memory_assertions()
        print("Memory assertions:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} [{row.get('status')}] "
                f"usable={row.get('usable', False)} sources="
                f"{len(row.get('source_evidence_ids', []))} "
                f"{str(row.get('claim', ''))[:100]}",
                file=output,
            )
        return
    if action in {"approve", "reject", "dispute"} and len(parts) >= 3:
        reason = parts[3] if len(parts) > 3 else f"cli_{action}"
        row = client.review_memory_assertion(
            parts[2],
            decision=action,
            reason=reason,
        )
        print(
            f"Memory assertion {row.get('id')} [{row.get('status')}] "
            f"usable={row.get('usable', False)}",
            file=output,
        )
        return
    print(
        "Usage: /assertions list|approve|reject|dispute <assertion_id> [reason]",
        file=output,
    )


def handle_skill_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "proposals"
    if action == "proposals":
        rows = client.list_skill_proposals()
        print("Skill proposals:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} [{row.get('status')}] "
                f"{row.get('skill_key')} hash={str(row.get('definition_hash', ''))[:12]}",
                file=output,
            )
        return
    if action == "show" and len(parts) >= 3:
        row = client.get_skill_proposal(parts[2])
        print(
            f"Skill proposal {row.get('id')} [{row.get('status')}] "
            f"{row.get('skill_key')} hash={row.get('definition_hash')}",
            file=output,
        )
        print(str(row.get("diff", "")).rstrip() or "- no diff", file=output)
        for evaluation in row.get("evaluations", []):
            print(
                f"- evaluation [{evaluation.get('status')}] "
                f"suite={evaluation.get('suite_version')} artifact="
                f"{str(evaluation.get('artifact_hash', ''))[:12]}",
                file=output,
            )
        return
    if action == "releases":
        rows = client.list_skill_releases()
        print("Skill releases:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} [{row.get('status')}] "
                f"{row.get('skill_key')} v{row.get('version')}",
                file=output,
            )
        return
    if action in {"approve", "reject"} and len(parts) >= 3:
        reason = " ".join(parts[3:]) if len(parts) > 3 else f"cli_{action}"
        row = client.decide_skill_proposal(
            parts[2],
            decision=action,
            reason=reason,
        )
        release = row.get("release", {})
        print(
            f"Skill proposal {parts[2]} [{action}] "
            f"release={release.get('id', '-') if isinstance(release, dict) else '-'}",
            file=output,
        )
        return
    if action == "rollback" and len(parts) >= 4:
        reason = " ".join(parts[4:]) if len(parts) > 4 else "cli_rollback"
        row = client.rollback_skill_release(
            parts[2],
            target_release_id=parts[3],
            reason=reason,
        )
        print(
            f"Skill release restored {row.get('id')} v{row.get('version')} "
            f"[{row.get('status')}]",
            file=output,
        )
        return
    print(
        "Usage: /skills proposals|show <proposal_id>|releases|"
        "approve|reject <proposal_id> [reason]|"
        "rollback <active_release_id> <target_release_id> [reason]",
        file=output,
    )


def handle_portfolio_window_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_portfolio_observation_windows()
        print("Portfolio observation windows:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            quality = row.get("quality", {})
            quality = quality if isinstance(quality, dict) else {}
            print(
                f"- {row.get('id')} [{row.get('status')}] "
                f"cards={quality.get('denominator', 0)} "
                f"available={quality.get('available_count', 0)} "
                f"coverage={quality.get('coverage_ratio', '0')} "
                f"window={row.get('horizon_days')}d/{row.get('bucket_minutes')}m",
                file=output,
            )
        return
    if action == "capture":
        row = client.capture_portfolio_observation_window()
        quality = row.get("quality", {})
        quality = quality if isinstance(quality, dict) else {}
        print(
            f"Observation window {row.get('id')} [{row.get('status')}] "
            f"coverage={quality.get('coverage_ratio', '0')} raw_series=false",
            file=output,
        )
        return
    if action == "show" and len(parts) == 3:
        row = client.get_portfolio_observation_window(parts[2])
        print(json.dumps(row, ensure_ascii=False, indent=2), file=output)
        return
    if action == "diff" and len(parts) == 4:
        row = client.diff_portfolio_observation_windows(parts[2], parts[3])
        print(json.dumps(row, ensure_ascii=False, indent=2), file=output)
        return
    print("Usage: /windows list|capture|show <window_id>|diff <left> <right>", file=output)


def handle_paper_cohort_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_paper_cohorts()
        print("Paper cohorts:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} v{row.get('version_number')} [{row.get('status')}] "
                f"intake={row.get('intake_count', 0)} "
                f"comparable={row.get('comparable_count', 0)} "
                f"proposals={row.get('proposal_count', 0)}",
                file=output,
            )
        return
    if action == "build":
        row = client.build_paper_cohort()
        print(
            f"Paper cohort {row.get('id')} v{row.get('version_number')} "
            f"[{row.get('status')}] comparable={row.get('comparable_count', 0)} "
            "execution=false",
            file=output,
        )
        return
    if action == "show" and len(parts) == 3:
        print(
            json.dumps(
                client.get_paper_cohort(parts[2]),
                ensure_ascii=False,
                indent=2,
            ),
            file=output,
        )
        return
    if action == "diff" and len(parts) == 4:
        print(
            json.dumps(
                client.diff_paper_cohorts(parts[2], parts[3]),
                ensure_ascii=False,
                indent=2,
            ),
            file=output,
        )
        return
    if action == "decide" and len(parts) >= 6:
        decision = parts[4].lower()
        if decision not in {"accept", "reject", "hold"}:
            print("Decision must be accept, reject, or hold", file=output)
            return
        row = client.decide_paper_cohort_label(
            parts[2],
            parts[3],
            decision=decision,
            reason=" ".join(parts[5:]),
        )
        print(
            f"Cohort label review {row.get('id')} [{row.get('decision')}] "
            f"label={row.get('proposed_label')} execution=false",
            file=output,
        )
        return
    print(
        "Usage: /cohorts list|build|show <cohort_id>|diff <left> <right>|"
        "decide <cohort_id> <proposal_id> accept|reject|hold <reason>",
        file=output,
    )


def render_paper_incubation_mandates(
    rows: list[dict[str, Any]], *, output: TextIO
) -> None:
    print("Paper incubation mandates:", file=output)
    if not rows:
        print("- none", file=output)
        return
    for row in rows[:30]:
        members = list(row.get("members", []))
        actions = list(row.get("actions", []))
        unknown_count = sum(
            isinstance(action, dict) and action.get("status") == "effect_unknown"
            for action in actions
        )
        latest = actions[-1] if actions and isinstance(actions[-1], dict) else {}
        print(
            f"- {row.get('id')} [{row.get('status')}] "
            f"kill={str(bool(row.get('kill_switch'))).lower()} "
            f"members={len(members)}/{row.get('fixed_denominator', 0)} "
            f"actions={len(actions)} unknown={unknown_count} "
            f"latest={latest.get('action', 'none')}:{latest.get('status', 'none')} "
            "paper_only=true live=false",
            file=output,
        )


def handle_shadow_portfolio_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_shadow_portfolios()
        print("Shadow portfolios (hypothetical only):", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} v{row.get('version_number')} [{row.get('status')}] "
                f"eligible={row.get('eligible_count', 0)}/{row.get('intake_count', 0)} "
                f"scenarios={row.get('scenario_count', 0)} execution=false",
                file=output,
            )
        return
    if action == "build":
        row = client.build_shadow_portfolio()
        print(
            f"Shadow portfolio {row.get('id')} v{row.get('version_number')} "
            f"[{row.get('status')}] scenarios={row.get('scenario_count', 0)} "
            "hypothetical=true capital=false execution=false",
            file=output,
        )
        return
    if action == "show" and len(parts) == 3:
        print(
            json.dumps(client.get_shadow_portfolio(parts[2]), ensure_ascii=False, indent=2),
            file=output,
        )
        return
    if action == "diff" and len(parts) == 4:
        print(
            json.dumps(
                client.diff_shadow_portfolios(parts[2], parts[3]),
                ensure_ascii=False,
                indent=2,
            ),
            file=output,
        )
        return
    if action == "review" and len(parts) >= 6:
        decision = parts[4].lower()
        if decision not in {"accept", "reject", "hold"}:
            print("Decision must be accept, reject, or hold", file=output)
            return
        row = client.review_shadow_portfolio(
            parts[2],
            parts[3],
            decision=decision,
            reason=" ".join(parts[5:]),
        )
        print(
            f"Shadow review {row.get('id')} [{row.get('decision')}] "
            "hypothetical=true capital=false execution=false",
            file=output,
        )
        return
    print(
        "Usage: /shadow list|build|show <proposal_id>|diff <left> <right>|"
        "review <proposal_id> <scenario_id> accept|reject|hold <reason>",
        file=output,
    )


def handle_regime_shadow_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_regime_shadow_targets()
        print("Regime-aware Shadow V2 targets:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} v{row.get('version_number')} "
                f"[{row.get('status')}] "
                f"eligible={row.get('eligible_count', 0)}/"
                f"{row.get('intake_denominator', 0)} "
                f"template={row.get('selected_template') or 'none'} "
                "hypothetical=true execution=false",
                file=output,
            )
        return
    if action == "build" and len(parts) == 4:
        row = client.build_regime_shadow_target(parts[2], parts[3])
        print(
            f"Regime Shadow target {row.get('id')} "
            f"[{row.get('status')}] "
            f"template={row.get('selected_template') or 'none'} "
            f"turnover={row.get('estimated_turnover', 'unknown')} "
            f"cost_bps={row.get('estimated_cost_bps', 'unknown')} "
            "capital=false execution=false",
            file=output,
        )
        return
    if action == "show" and len(parts) == 3:
        print(
            json.dumps(
                client.get_regime_shadow_target(parts[2]),
                ensure_ascii=False,
                indent=2,
            ),
            file=output,
        )
        return
    if action == "replay" and len(parts) == 3:
        print(
            json.dumps(
                client.replay_regime_shadow_target(parts[2]),
                ensure_ascii=False,
                indent=2,
            ),
            file=output,
        )
        return
    print(
        "Usage: /regime-shadow list|build <regime_id> <cohort_id>|"
        "show <target_id>|replay <target_id>",
        file=output,
    )


def _default_regime_shadow_policy() -> ShadowAllocationPolicyV2:
    return ShadowAllocationPolicyV2(
        templates=[
            "equal_weight",
            "inverse_volatility",
            "capped_risk_contribution",
            "constrained_risk_adjusted",
        ],
        hypothetical_notional=Decimal("100000"),
        min_members=2,
        max_members=8,
        max_strategy_weight=Decimal("0.60"),
        max_symbol_weight=Decimal("0.80"),
        max_pair_correlation=Decimal("0.80"),
        max_turnover=Decimal("0.50"),
        max_weight_delta=Decimal("0.20"),
        max_estimated_cost_bps=Decimal("50"),
        entry_threshold=Decimal("0.20"),
        exit_threshold=Decimal("0.10"),
        confirmation_windows=2,
        minimum_dwell_hours=24,
        cooldown_hours=24,
        valid_minutes=60,
    )


def handle_portfolio_v2_command(
    command: str,
    *,
    client: AgentClient,
    output: TextIO,
) -> None:
    parts = command.split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action == "list":
        rows = client.list_portfolio_assessments()
        print("Portfolio lifecycle assessments:", file=output)
        if not rows:
            print("- none", file=output)
        for row in rows[:30]:
            print(
                f"- {row.get('id')} [{row.get('status')}] "
                f"strategies={len(row.get('strategies', []))} "
                f"unknowns={len(row.get('unknowns', []))} valid={row.get('valid_until')}",
                file=output,
            )
        return
    if action == "assess":
        row = client.create_portfolio_assessment()
        print(
            f"Portfolio assessment {row.get('id')} [{row.get('status')}] "
            f"recommendations={len(row.get('recommendations', []))}",
            file=output,
        )
        return
    if action == "show" and len(parts) == 3:
        row = client.get_portfolio_assessment(parts[2])
        print(
            f"Portfolio assessment {row.get('id')} [{row.get('status')}] "
            f"policy={row.get('policy_version')}",
            file=output,
        )
        for recommendation in row.get("recommendations", []):
            print(
                f"- {recommendation.get('recommendation_id')} "
                f"{recommendation.get('action')} "
                f"card={recommendation.get('strategy_card_id') or '-'}",
                file=output,
            )
        for unknown in row.get("unknowns", [])[:20]:
            print(f"  unknown: {unknown}", file=output)
        return
    if action == "diff" and len(parts) == 4:
        row = client.diff_portfolio_assessments(parts[2], parts[3])
        print(json.dumps(row, ensure_ascii=False, indent=2), file=output)
        return
    if action == "review" and len(parts) >= 6:
        decision = parts[4].lower()
        if decision not in {"accept", "reject", "hold"}:
            print("Decision must be accept, reject, or hold", file=output)
            return
        row = client.review_portfolio_recommendation(
            parts[2],
            parts[3],
            decision=decision,
            reason=" ".join(parts[5:]),
        )
        print(
            f"Lifecycle review {row.get('id')} [{row.get('decision')}] "
            f"action={row.get('recommendation_action')}",
            file=output,
        )
        return
    print(
        "Usage: /portfolio-v2 list|assess|show <assessment_id>|"
        "diff <left> <right>|review <assessment_id> <recommendation_id> "
        "accept|reject|hold <reason>",
        file=output,
    )


def handle_run_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    """Load one historical run through the same renderer as a live completion.

    The run payload contains the persisted report and trace evidence, but never
    needs to expose credentials or private model reasoning to the terminal.
    """
    parts = command.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        print("Usage: /run <run_id>  (find ids with /runs)", file=output)
        return
    run_id = parts[1].strip()
    try:
        run = client.get_run(run_id)
    except KeyError:
        print(f"Run not found: {run_id}", file=output)
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            print(f"Run not found: {run_id}", file=output)
            return
        raise
    render_run(run, output=output)


def render_memory(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Memory:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        tags = item.get("tags", [])
        tag_text = ",".join(str(tag) for tag in tags) if isinstance(tags, list) else ""
        print(
            f"- {item.get('id', 'unknown')} [{item.get('kind', 'unknown')}] "
            f"{str(item.get('content', ''))[:100]}",
            file=output,
        )
        if tag_text:
            print(
                f"  tags: {tag_text} usage={item.get('usage_count', 0)}",
                file=output,
            )


def render_rag_hits(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("RAG hits:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            "- {title} {source_path}#{chunk_index} score={score}".format(
                title=item.get("title", "Knowledge"),
                source_path=item.get("source_path", "unknown"),
                chunk_index=item.get("chunk_index", 0),
                score=item.get("score", "n/a"),
            ),
            file=output,
        )
        preview = str(item.get("content_preview", "")).replace("\n", " ")[:160]
        if preview:
            print(f"  {preview}", file=output)


def render_evals_status(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Eval suite:", file=output)
    print(f"- Status: {payload.get('status', 'unknown')}", file=output)
    research_os = payload.get("research_os")
    if isinstance(research_os, dict):
        print(
            f"- Research OS: {research_os.get('status', 'unknown')} "
            f"suite={research_os.get('suite_version', 'unknown')} "
            f"cases={research_os.get('case_count', 0)}",
            file=output,
        )
        categories = research_os.get("categories")
        if isinstance(categories, dict):
            summary = " ".join(f"{name}={count}" for name, count in sorted(categories.items()))
            print(f"  categories: {summary}", file=output)
    quality = payload.get("quality")
    if isinstance(quality, dict):
        print(
            f"- Quality: {quality.get('status', 'unknown')} "
            f"contract={quality.get('metric_contract', 'unknown')} "
            f"provider={quality.get('provider_baseline', 'unknown')}",
            file=output,
        )
        cohorts = quality.get("cohorts")
        if isinstance(cohorts, dict):
            summary = " ".join(f"{name}={count}" for name, count in sorted(cohorts.items()))
            print(f"  cohorts: {summary}", file=output)
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or not cases:
        print("- no cases", file=output)
        return
    for case in cases:
        if not isinstance(case, dict):
            continue
        print(
            f"- {case.get('name', 'unknown')} {case.get('status', 'unknown')}",
            file=output,
        )


def render_strategy_cards(
    cards: list[dict[str, Any]],
    funnel: dict[str, Any],
    *,
    output: TextIO,
) -> None:
    print(
        "Research Funnel: "
        f"denominator={funnel.get('denominator', 0)} "
        f"unit={funnel.get('denominator_unit', 'unknown')}",
        file=output,
    )
    stages = funnel.get("stages", {})
    if isinstance(stages, dict):
        print(
            "Stages: " + " · ".join(f"{key}={value}" for key, value in stages.items()),
            file=output,
        )
    if not cards:
        print("No StrategyCards.", file=output)
        return
    for card in cards:
        version = card.get("version", {})
        version = version if isinstance(version, dict) else {}
        print(
            f"- {card.get('card_id', '-')} {card.get('strategy_key', '-')} "
            f"v{version.get('version_number', '-')} "
            f"status={card.get('lifecycle_status', card.get('paper_status', 'unknown'))} "
            f"complete={card.get('completeness_score', 'unknown')}",
            file=output,
        )
        missing = card.get("missing_fields", [])
        if isinstance(missing, list) and missing:
            print(f"  missing={','.join(str(value) for value in missing)}", file=output)


def render_monitors(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Monitors:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:20]:
        enabled = "enabled" if item.get("enabled", True) else "disabled"
        last_status = item.get("last_status") or "never"
        last_run_id = item.get("last_run_id") or "n/a"
        print(
            "- {id} [{kind}] {enabled} last={last_status} run={last_run}: {name}".format(
                id=item.get("id", "unknown"),
                kind=item.get("monitor_type", "unknown"),
                enabled=enabled,
                last_status=last_status,
                last_run=last_run_id,
                name=item.get("name", ""),
            ),
            file=output,
        )


def render_monitor_run(payload: dict[str, Any], *, output: TextIO) -> None:
    print(f"Monitor run: {payload.get('run_id', 'unknown')}", file=output)
    print(f"- Monitor: {payload.get('monitor_id', 'unknown')}", file=output)
    print(f"- Status: {payload.get('status', 'unknown')}", file=output)
    previous = payload.get("previous_run_id")
    if previous:
        print(f"- Previous: {previous}", file=output)
    metrics = payload.get("metric_snapshot")
    metrics = metrics if isinstance(metrics, dict) else {}
    if metrics:
        print("- Metrics:", file=output)
        for key in sorted(metrics):
            print(f"  {key}: {metrics[key]}", file=output)
    alerts = payload.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    print("- Alerts:", file=output)
    if alerts:
        for alert in alerts[:10]:
            if not isinstance(alert, dict):
                continue
            print(
                "  [{level}] {code}: {message}".format(
                    level=alert.get("level", "warning"),
                    code=alert.get("code", "monitor_alert"),
                    message=alert.get("message", ""),
                ),
                file=output,
            )
    else:
        print("  none", file=output)
    data_gaps = payload.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []
    if data_gaps:
        print("- Data gaps:", file=output)
        for gap in data_gaps[:10]:
            print(f"  {gap}", file=output)
    actions = payload.get("recommended_actions")
    actions = actions if isinstance(actions, list) else []
    if actions:
        print("- Recommended read-only actions:", file=output)
        for action in actions[:5]:
            print(f"  {action}", file=output)


def render_alerts(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Recent alerts:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:20]:
        print(
            "- {id} [{level}] {code} monitor={monitor} run={run}: {message}".format(
                id=item.get("id", "unknown"),
                level=item.get("level", "warning"),
                code=item.get("code", "monitor_alert"),
                monitor=item.get("monitor_id", "unknown"),
                run=item.get("run_id", "unknown"),
                message=item.get("message", ""),
            ),
            file=output,
        )


def render_strategy_research(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Strategy research:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            f"- {item.get('id', 'unknown')} {item.get('strategy_key', 'unknown')}: "
            f"{item.get('title', '')}",
            file=output,
        )


def render_strategy_library(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Strategy library:", file=output)
    print(f"- Source: {payload.get('source', 'unknown')}", file=output)
    print(f"- Memory evidence: {payload.get('memory_count', 0)}", file=output)
    items = payload.get("items")
    items = items if isinstance(items, list) else []
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        print(
            "- {strategy}: evidence={evidence} pass={passed} fail={failed}".format(
                strategy=item.get("strategy_key", "unknown"),
                evidence=item.get("evidence_count", 0),
                passed=item.get("passed_count", 0),
                failed=item.get("failed_count", 0),
            ),
            file=output,
        )
        best = item.get("best")
        best = best if isinstance(best, dict) else {}
        if best:
            print(
                (
                    "  best: memory={memory} experiment={experiment} "
                    "backtest={backtest} winner={winner}"
                ).format(
                    memory=best.get("memory_id", "n/a"),
                    experiment=best.get("experiment_id", "n/a"),
                    backtest=best.get("backtest_id", "n/a"),
                    winner=best.get("variant_id", "n/a"),
                ),
                file=output,
            )
            print(
                (
                    "  metrics: return={return_pct}% drawdown={drawdown}% "
                    "trades={trades} score={score}"
                ).format(
                    return_pct=best.get("total_return_pct", "n/a"),
                    drawdown=best.get("max_drawdown_pct", "n/a"),
                    trades=best.get("trade_count", "n/a"),
                    score=best.get("score", "n/a"),
                ),
                file=output,
            )
        failure_reasons = item.get("failure_reasons")
        if isinstance(failure_reasons, list) and failure_reasons:
            print(
                f"  failure reasons: {', '.join(str(value) for value in failure_reasons)}",
                file=output,
            )
        next_steps = item.get("next_experiments")
        if isinstance(next_steps, list) and next_steps:
            print(f"  next: {next_steps[0]}", file=output)
        source_ids = item.get("source_memory_ids")
        if isinstance(source_ids, list) and source_ids:
            print(
                f"  source memories: {', '.join(str(value) for value in source_ids)}",
                file=output,
            )


def render_backtests(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Backtests:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        metrics = item.get("metrics", {})
        return_pct = metrics.get("total_return_pct", "n/a") if isinstance(metrics, dict) else "n/a"
        trades = metrics.get("trade_count", "n/a") if isinstance(metrics, dict) else "n/a"
        print(
            f"- {item.get('id', 'unknown')} {item.get('strategy_key', 'unknown')} "
            f"{item.get('status', 'unknown')} return={return_pct}% trades={trades}",
            file=output,
        )


def render_run(run: dict[str, Any], *, output: TextIO | None = None) -> None:
    output = output or sys.stdout

    if _should_render_rich(output) and _render_rich_run(run, output=output):
        return
    trace_events = run.get("trace_events", [])
    if _show_trace_output():
        print(f"Run: {run.get('id', 'unknown')}", file=output)
        print(f"Status: {run.get('status', 'unknown')}", file=output)
        _render_observability_plain(run, output=output)
    if _show_trace_output() and isinstance(trace_events, list) and trace_events:
        print("Tools:", file=output)
        for event in trace_events:
            if not isinstance(event, dict):
                continue
            print(
                f"- {event.get('tool_name', 'unknown')}: {event.get('status', 'unknown')}"
                f"{_trace_duration_label(event)}",
                file=output,
            )
        print("", file=output)
    if _prefer_final_agent_report(run):
        _render_markdown_report(
            str(run.get("report_markdown", "")),
            output=output,
            title="Agent Report",
        )
        return
    if _render_structured_report(run, output=output):
        return
    _render_markdown_report(
        str(run.get("report_markdown", "")),
        output=output,
        title="Agent Report",
    )


def _run_observability(run: dict[str, Any]) -> dict[str, Any]:
    """Read the additive, trace-safe observability projection from a run."""
    state = run.get("run_state_json")
    if isinstance(state, dict):
        observability = state.get("observability")
        if isinstance(observability, dict):
            return observability
    report = run.get("report_json")
    if isinstance(report, dict):
        observability = report.get("observability")
        if isinstance(observability, dict):
            return observability
    return {}


def _render_observability_plain(run: dict[str, Any], *, output: TextIO) -> None:
    """Render a compact terminal Flight Recorder without raw trace payloads."""
    observability = _run_observability(run)
    if not observability:
        print("Flight Recorder: unavailable for this run", file=output)
        return

    usage = observability.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    tools = observability.get("tools")
    tools = tools if isinstance(tools, dict) else {}
    memory = observability.get("memory")
    memory = memory if isinstance(memory, dict) else {}

    provider = str(observability.get("provider") or "unavailable")
    model = str(observability.get("model") or "unavailable")
    duration = _format_duration_ms(observability.get("duration_ms"))
    print("Flight Recorder:", file=output)
    print(f"- runtime: {provider} / {model} · duration={duration}", file=output)
    print(f"- tokens: {_token_usage_label(usage)}", file=output)
    print(
        "- tools: "
        f"calls={_integer_value(tools.get('call_count'))} "
        f"errors={_integer_value(tools.get('error_count'))} "
        f"execution={_format_duration_ms(tools.get('total_execution_ms'))}"
        f"{_slowest_tool_label(tools.get('slowest'))}",
        file=output,
    )
    print(
        "- memory: "
        f"read={_integer_value(memory.get('read_count'))} "
        f"written={_integer_value(memory.get('write_count'))}",
        file=output,
    )
    print("- safety: prompts, credentials, and private reasoning are not displayed", file=output)


def _token_usage_label(usage: dict[str, Any]) -> str:
    requests = _integer_value(usage.get("request_count"))
    if not bool(usage.get("reported")):
        return f"unavailable · model_calls={requests}"
    return (
        f"total={_integer_value(usage.get('total_tokens'))} "
        f"input={_integer_value(usage.get('input_tokens'))} "
        f"output={_integer_value(usage.get('output_tokens'))} "
        f"cached={_integer_value(usage.get('cached_input_tokens'))} "
        f"reasoning={_integer_value(usage.get('reasoning_tokens'))} "
        f"model_calls={requests}"
    )


def _slowest_tool_label(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    tool_name = str(value.get("tool_name") or "")
    if not tool_name:
        return ""
    return f" · slowest={tool_name} ({_format_duration_ms(value.get('execution_ms'))})"


def _integer_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        with suppress(ValueError):
            return int(float(value))
    return 0


def _format_duration_ms(value: object) -> str:
    if isinstance(value, bool):
        return "n/a"
    if not isinstance(value, int | float | str):
        return "n/a"
    try:
        duration_ms = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if duration_ms < 1000:
        return f"{duration_ms:.0f}ms"
    return f"{duration_ms / 1000:.2f}s"


def _trace_duration_label(event: dict[str, Any]) -> str:
    payload = event.get("output_json")
    if not isinstance(payload, dict):
        return ""
    value = payload.get("duration_ms", payload.get("execution_ms"))
    if value is None:
        return ""
    return f" · {_format_duration_ms(value)}"


def _should_render_rich(output: TextIO) -> bool:
    renderer = os.getenv("HYPERTRADE_RENDERER", "auto").strip().lower()
    if renderer in {"plain", "text"}:
        return False
    if renderer in {"enhanced", "rich"}:
        return True
    return bool(getattr(output, "isatty", lambda: False)())


def _render_rich_run(run: dict[str, Any], *, output: TextIO) -> bool:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return False

    console = Console(
        file=output,
        force_terminal=True,
        color_system=_rich_color_system(),
        width=120,
    )
    trace_events = run.get("trace_events", [])
    report = run.get("report_json", {})
    has_structured_market_summary = isinstance(report, dict) and isinstance(
        report.get("top_movers"),
        list,
    )
    report_blocks = report.get("report_blocks") if isinstance(report, dict) else None
    has_report_blocks = isinstance(report_blocks, list) and bool(report_blocks)
    has_structured_tools = isinstance(trace_events, list) and _has_structured_market_tool_output(
        trace_events
    )
    raw_markdown = _strip_report_icons(str(run.get("report_markdown", ""))).strip()
    if (
        not has_report_blocks
        and not has_structured_market_summary
        and not has_structured_tools
        and not raw_markdown
    ):
        return False

    if _show_trace_output():
        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(justify="right")
        header.add_row(
            Text(str(run.get("id", "unknown")), style="bold"),
            Text(str(run.get("status", "unknown")), style="green"),
        )
        console.print(Panel(header, title="HyperTrade Run", border_style="cyan"))
        _render_rich_observability(run, console=console)

    if _show_trace_output() and isinstance(trace_events, list) and trace_events:
        _render_rich_trace_summary(trace_events, console=console)

    if _prefer_final_agent_report(run):
        console.print(Markdown(raw_markdown))
        return True
    # Report blocks preserve structured tool evidence for audit and UI consumers.
    # They are not the default operator answer when the Agent already produced one.
    if has_report_blocks:
        report_block_items = cast(list[ReportBlock | dict[str, Any]], report_blocks)
        console.print(render_report_blocks(report_block_items, audit=_show_report_block_audit()))
        return True
    if _prefer_final_report(run):
        console.print(Markdown(raw_markdown))
        return True
    if _prefer_compact_paper_report(run):
        _render_rich_compact_bitpro_paper_report(run, console=console)
        return True
    if _prefer_market_final_report(run):
        console.print(Markdown(raw_markdown))
        return True
    if has_structured_market_summary and isinstance(report, dict):
        _render_rich_market_summary(report, console=console)
    elif has_structured_tools and isinstance(trace_events, list):
        _render_rich_tool_report(trace_events, report=report, console=console)
    else:
        console.print(Markdown(raw_markdown))

    return True


def _render_rich_trace_summary(trace_events: list[Any], *, console: Any) -> None:
    from rich.table import Table
    from rich.text import Text

    full_trace = _show_full_trace()
    visible_events, folded_events = _partition_trace_events(trace_events, full_trace=full_trace)
    if not visible_events and folded_events:
        console.print(
            Text(
                "Trace folded: "
                f"{len(folded_events)} internal events hidden "
                "(graph/preflight/nested BitPro). "
                "Set HYPERTRADE_TRACE=full to show all.",
                style="dim",
            )
        )
        return

    title = "Tool Trace" if full_trace else "Tool Trace Summary"
    tools = Table(title=title, show_header=True, header_style="bold")
    tools.add_column("Tool")
    tools.add_column("Status")
    if not full_trace:
        tools.add_column("Calls", justify="right")
        for row in _aggregate_trace_events(visible_events):
            tools.add_row(row["tool"], row["status"], str(row["count"]))
    else:
        tools.add_column("Duration", justify="right")
        for event in visible_events:
            tools.add_row(
                str(event.get("tool_name", "unknown")),
                str(event.get("status", "n/a")),
                _trace_duration_label(event).removeprefix(" · ") or "n/a",
            )
    console.print(tools)
    if folded_events:
        console.print(
            Text(
                "Trace folded: "
                f"{len(folded_events)} internal events hidden "
                "(graph/preflight/nested BitPro). "
                "Set HYPERTRADE_TRACE=full to show all.",
                style="dim",
            )
        )


def _render_rich_observability(run: dict[str, Any], *, console: Any) -> None:
    """Render the redacted Flight Recorder ledger above the optional trace table."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    observability = _run_observability(run)
    if not observability:
        console.print(Text("Flight Recorder unavailable for this run", style="dim"))
        return
    usage = observability.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    tools = observability.get("tools")
    tools = tools if isinstance(tools, dict) else {}
    memory = observability.get("memory")
    memory = memory if isinstance(memory, dict) else {}

    ledger = Table.grid(expand=True, padding=(0, 1))
    ledger.add_column(style="cyan", no_wrap=True)
    ledger.add_column()
    ledger.add_row(
        "Runtime",
        f"{observability.get('provider') or 'unavailable'} / "
        f"{observability.get('model') or 'unavailable'} · "
        f"{_format_duration_ms(observability.get('duration_ms'))}",
    )
    ledger.add_row("Tokens", _token_usage_label(usage))
    ledger.add_row(
        "Tools",
        f"calls={_integer_value(tools.get('call_count'))} · "
        f"errors={_integer_value(tools.get('error_count'))} · "
        f"execution={_format_duration_ms(tools.get('total_execution_ms'))}"
        f"{_slowest_tool_label(tools.get('slowest'))}",
    )
    ledger.add_row(
        "Memory",
        f"read={_integer_value(memory.get('read_count'))} · "
        f"written={_integer_value(memory.get('write_count'))}",
    )
    ledger.add_row("Safety", "Prompts, credentials, and private reasoning are redacted")
    console.print(Panel(ledger, title="Flight Recorder", border_style="blue"))


def _show_full_trace() -> bool:
    value = _trace_display_mode()
    return value in {"all", "debug", "full", "verbose"}


def _show_trace_output() -> bool:
    return _trace_display_mode() in {
        "all",
        "compact",
        "debug",
        "folded",
        "full",
        "summary",
        "verbose",
    }


def _trace_display_mode() -> str:
    return os.getenv("HYPERTRADE_TRACE", "off").strip().lower()


def _partition_trace_events(
    trace_events: list[Any],
    *,
    full_trace: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = [event for event in trace_events if isinstance(event, dict)]
    if full_trace:
        return events, []
    high_level_bitpro = {
        str(event.get("tool_name", ""))
        for event in events
        if str(event.get("tool_name", "")).startswith("bitpro_")
    }
    visible: list[dict[str, Any]] = []
    folded: list[dict[str, Any]] = []
    for event in events:
        if _is_folded_trace_event(event, high_level_bitpro=high_level_bitpro):
            folded.append(event)
        else:
            visible.append(event)
    return visible, folded


def _is_folded_trace_event(
    event: dict[str, Any],
    *,
    high_level_bitpro: set[str],
) -> bool:
    tool_name = str(event.get("tool_name", ""))
    if tool_name.startswith("graph."):
        return True
    if tool_name in {
        "bitpro.capabilities",
        "bitpro.health",
        "bitpro_capabilities",
        "bitpro_health",
    }:
        return True
    return tool_name.startswith("bitpro.") and bool(high_level_bitpro)


def _aggregate_trace_events(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for event in trace_events:
        tool_name = str(event.get("tool_name", "unknown"))
        status = str(event.get("status", "n/a"))
        key = (tool_name, status)
        if key not in index:
            row = {"tool": tool_name, "status": status, "count": 0}
            index[key] = row
            rows.append(row)
        index[key]["count"] += 1
    return rows


def _render_markdown_report(markdown: str, *, output: TextIO, title: str) -> None:
    markdown = _strip_report_icons(markdown)
    if _should_render_rich(output) and _render_rich_markdown(markdown, output=output, title=title):
        return
    print(markdown, file=output)


def _render_rich_markdown(markdown: str, *, output: TextIO, title: str) -> bool:
    markdown = _strip_report_icons(markdown).strip()
    if not markdown:
        return False
    try:
        from rich.console import Console
        from rich.markdown import Markdown
    except ImportError:
        return False

    console = Console(
        file=output,
        force_terminal=True,
        color_system=_rich_color_system(),
        width=120,
    )
    console.print(Markdown(markdown))
    return True


def _rich_color_system() -> Literal["standard"] | None:
    return None if os.getenv("NO_COLOR") else "standard"


def _strip_report_icons(markdown: str) -> str:
    lines = [
        "".join(ch for ch in line if not _is_report_icon_char(ch)) for line in markdown.splitlines()
    ]
    normalized = "\n".join(_normalize_markdown_line_spacing(line) for line in lines)
    return _compact_markdown_report(_remove_non_core_report_sections(normalized))


def _remove_non_core_report_sections(markdown: str) -> str:
    lines = markdown.splitlines()
    kept: list[str] = []
    skip_level: int | None = None
    for line in lines:
        heading_level, heading_text = _markdown_heading(line)
        if heading_level is not None and skip_level is not None and heading_level <= skip_level:
            skip_level = None
        if skip_level is not None:
            continue
        if heading_level is not None and heading_text in {"引用来源", "References", "Sources"}:
            skip_level = heading_level
            continue
        kept.append(line)
    return "\n".join(kept)


def _markdown_heading(line: str) -> tuple[int | None, str]:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None, ""
    marker_length = 0
    while marker_length < len(stripped) and stripped[marker_length] == "#":
        marker_length += 1
    if marker_length == 0 or marker_length >= len(stripped):
        return None, ""
    if stripped[marker_length] != " ":
        return None, ""
    return marker_length, stripped[marker_length:].strip()


def _compact_markdown_report(markdown: str) -> str:
    compact_lines: list[str] = []
    previous_blank = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if _is_markdown_horizontal_rule(stripped):
            continue
        if not stripped:
            if compact_lines and not previous_blank:
                compact_lines.append("")
            previous_blank = True
            continue
        compact_lines.append(line)
        previous_blank = False
    while compact_lines and compact_lines[-1] == "":
        compact_lines.pop()
    return "\n".join(compact_lines)


def _is_markdown_horizontal_rule(stripped: str) -> bool:
    if len(stripped) < 3:
        return False
    return set(stripped) in ({"-"}, {"_"}, {"*"})


def _is_report_icon_char(ch: str) -> bool:
    codepoint = ord(ch)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or codepoint == 0x20E3
        or 0xFE00 <= codepoint <= 0xFE0F
    )


def _normalize_markdown_line_spacing(line: str) -> str:
    if not line:
        return line
    if line.startswith("#"):
        marker_length = 0
        while marker_length < len(line) and line[marker_length] == "#":
            marker_length += 1
        marker = line[:marker_length]
        body = line[marker_length:].strip()
        return f"{marker} {body}" if body else marker
    if line.startswith("-"):
        body = line[1:].strip()
        return f"- {body}" if body else "-"
    return line


def _render_rich_market_summary(report: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    meta = Table.grid(expand=True)
    meta.add_column()
    meta.add_column()
    meta.add_row("Scope", str(report.get("market_scope", "unknown")))
    meta.add_row("Source", str(report.get("data_source", "unknown")))
    meta.add_row("As of UTC", str(report.get("as_of_utc", "n/a")))
    console.print(Panel(meta, title="Market Report", border_style="green"))

    heat = report.get("heat_summary")
    if isinstance(heat, dict):
        heat_text = "\n".join(
            [
                f"结论: {heat.get('conclusion', '当前市场热度暂不可用。')}",
                (
                    "样本: {sample_count} | 上涨 {advancers_count}({advancers_pct}%) | "
                    "下跌 {decliners_count}({decliners_pct}%) | 平均 {average_change_pct}%"
                ).format(
                    sample_count=heat.get("sample_count", 0),
                    advancers_count=heat.get("advancers_count", 0),
                    advancers_pct=heat.get("advancers_pct", "0.000000"),
                    decliners_count=heat.get("decliners_count", 0),
                    decliners_pct=heat.get("decliners_pct", "0.000000"),
                    average_change_pct=heat.get("average_change_pct", "0.000000"),
                ),
                ("最强/最弱: {top_gainer} / {top_loser}").format(
                    top_gainer=heat.get("top_gainer", "n/a"),
                    top_loser=heat.get("top_loser", "n/a"),
                ),
            ]
        )
        console.print(Panel(heat_text, title="市场热度", border_style="yellow"))

    movers = Table(title="Top Movers", show_header=True, header_style="bold")
    movers.add_column("Instrument")
    movers.add_column("Last", justify="right")
    movers.add_column("UTC0 %", justify="right")
    movers.add_column("24h Volume", justify="right")
    raw_movers = report.get("top_movers", [])
    if isinstance(raw_movers, list):
        for mover in raw_movers[:10]:
            if not isinstance(mover, dict):
                continue
            movers.add_row(
                str(mover.get("inst_id", "unknown")),
                str(mover.get("last", "n/a")),
                str(mover.get("change_utc0_pct", "n/a")),
                str(mover.get("volume_ccy_24h", "n/a")),
            )
    console.print(movers)


def _render_rich_tool_report(
    trace_events: list[Any],
    *,
    report: object,
    console: Any,
) -> None:
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("output_json", {})
        if not isinstance(payload, dict) or not payload.get("found", True):
            continue
        tool_name = str(event.get("tool_name", ""))
        if tool_name == "market_ticker":
            _render_rich_ticker(payload, console=console)
        elif tool_name == "market_candles":
            _render_rich_candles(payload, console=console)
        elif tool_name == "market_compare":
            _render_rich_compare(payload, console=console)
        elif tool_name == "bitpro_backtest_list_results":
            _render_rich_bitpro_backtest_results(payload, console=console)
        elif tool_name == "bitpro_backtest_get_result":
            _render_rich_bitpro_backtest_detail(payload, console=console)
        elif tool_name == "bitpro_paper_dashboard":
            _render_rich_bitpro_paper_dashboard(payload, console=console)
        elif tool_name == "bitpro_paper_strategy_performance":
            _render_rich_bitpro_paper_strategy_performance(payload, console=console)
        elif tool_name == "bitpro_paper_events":
            _render_rich_bitpro_paper_events(payload, console=console)
        elif tool_name == "bitpro_paper_equity_curve":
            _render_rich_bitpro_paper_equity_curve(payload, console=console)
        elif tool_name == "bitpro_paper_monitor_snapshot":
            _render_rich_bitpro_paper_monitor_snapshot(payload, console=console)


def _render_rich_ticker(payload: dict[str, Any], *, console: Any) -> None:
    from rich.table import Table

    table = Table(title="Ticker", show_header=True, header_style="bold")
    table.add_column("Instrument")
    table.add_column("Last", justify="right")
    table.add_column("UTC0 %", justify="right")
    table.add_column("24h Volume", justify="right")
    table.add_column("Source")
    table.add_row(
        str(payload.get("inst_id", "unknown")),
        str(payload.get("last", "n/a")),
        str(payload.get("change_utc0_pct", "n/a")),
        str(payload.get("volume_ccy_24h", "n/a")),
        str(payload.get("data_source", "unknown")),
    )
    console.print(table)


def _render_rich_candles(payload: dict[str, Any], *, console: Any) -> None:
    from rich.table import Table

    table = Table(title=f"Trend {payload.get('bar', 'n/a')}", show_header=True, header_style="bold")
    table.add_column("Instrument")
    table.add_column("Candles", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("Bias")
    table.add_column("Source")
    table.add_row(
        str(payload.get("inst_id", "unknown")),
        str(payload.get("candle_count", "n/a")),
        str(payload.get("return_pct", "n/a")),
        str(payload.get("trend_bias", "unknown")),
        str(payload.get("data_source", "unknown")),
    )
    console.print(table)


def _render_rich_compare(payload: dict[str, Any], *, console: Any) -> None:
    from rich.table import Table

    table = Table(title="Relative Strength", show_header=True, header_style="bold")
    table.add_column("Rank", justify="right")
    table.add_column("Instrument")
    table.add_column("Score", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("Bias")
    rankings = payload.get("rankings", [])
    if isinstance(rankings, list):
        for row in rankings:
            if not isinstance(row, dict):
                continue
            table.add_row(
                str(row.get("rank", "?")),
                str(row.get("inst_id", "unknown")),
                str(row.get("strength_score", "n/a")),
                str(row.get("return_pct", "n/a")),
                str(row.get("trend_bias", "unknown")),
            )
    console.print(table)


def _render_rich_bitpro_paper_dashboard(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    dashboard = payload.get("dashboard")
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    system = dashboard.get("system")
    system = system if isinstance(system, dict) else {}
    equity = dashboard.get("equity")
    equity = equity if isinstance(equity, dict) else {}
    performance = dashboard.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    scope = payload.get("paper_scope")
    scope = scope if isinstance(scope, dict) else {}
    running = payload.get("running_strategies")
    running = running if isinstance(running, dict) else {}
    monitor = payload.get("monitor_summary")
    monitor = monitor if isinstance(monitor, dict) else {}
    inventory = monitor.get("running_inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    alerts = monitor.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    data_gaps = monitor.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []
    actions = monitor.get("recommended_actions")
    actions = actions if isinstance(actions, list) else []

    listed = inventory.get("listed_count", 0)
    total = inventory.get("reported_total", running.get("total", listed))
    coverage = "truncated" if inventory.get("is_truncated") else "complete"
    summary = "\n".join(
        [
            f"合同: {payload.get('contract_version', 'unknown')}",
            f"范围: {scope.get('dashboard_scope', 'unknown')}",
            (
                "当前: strategy_id={strategy_id}, {name}, state={state}, "
                "mode={mode}, uptime={uptime}"
            ).format(
                strategy_id=system.get("strategy_id", "n/a"),
                name=system.get("strategy", "n/a"),
                state=system.get("state", "n/a"),
                mode=system.get("mode", "n/a"),
                uptime=system.get("uptime", "n/a"),
            ),
            ("绩效: equity={equity}, pnl={pnl}, sharpe={sharpe}, drawdown={drawdown}").format(
                equity=_format_number(equity.get("current")),
                pnl=_format_percent(performance.get("total_pnl_pct")),
                sharpe=_format_number(performance.get("sharpe_ratio"), digits=4),
                drawdown=_format_percent(performance.get("max_drawdown")),
            ),
            (
                f"监控: {monitor.get('mode', 'unknown')} | "
                f"running listed={listed}, total={total}, {coverage}"
            ),
        ]
    )
    console.print(Panel(summary, title="BitPro 模拟盘监控", border_style="green"))

    if alerts or data_gaps or actions:
        table = Table(title="Monitor Findings", show_header=True, header_style="bold", expand=True)
        table.add_column("Type", ratio=2)
        table.add_column("Code", ratio=3)
        table.add_column("Message", ratio=7, overflow="fold")
        for alert in alerts:
            if isinstance(alert, dict):
                table.add_row(
                    str(alert.get("level", "info")),
                    str(alert.get("code", "unknown")),
                    str(alert.get("message", "n/a")),
                )
        for gap in data_gaps:
            table.add_row("gap", "-", str(gap))
        for action in actions:
            if isinstance(action, dict):
                table.add_row(
                    "action",
                    str(action.get("action", "observe")),
                    str(action.get("message", "n/a")),
                )
        console.print(table)


def _render_rich_bitpro_paper_events(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    summary = payload.get("event_summary")
    summary = summary if isinstance(summary, dict) else {}
    events = payload.get("events")
    events = events if isinstance(events, list) else []
    summary_text = "\n".join(
        [
            f"策略: {payload.get('strategy_id', 'all')}",
            ("事件: count={count}, sample={sample}, errors={errors}, latest={latest}").format(
                count=summary.get("count", len(events)),
                sample=summary.get("sample_count", len(events)),
                errors=summary.get("error_count", 0),
                latest=summary.get("latest_event_at", "n/a"),
            ),
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary_text, title="BitPro 模拟盘事件", border_style="yellow"))
    if events:
        table = Table(title="Paper Events", show_header=True, header_style="bold", expand=True)
        table.add_column("ID", ratio=1)
        table.add_column("Level", ratio=1)
        table.add_column("Type", ratio=2)
        table.add_column("Message", ratio=5, overflow="fold")
        table.add_column("Time", ratio=2)
        for event in events[:10]:
            if not isinstance(event, dict):
                continue
            table.add_row(
                str(event.get("id", "n/a")),
                str(event.get("level", "info")),
                str(event.get("type", "event")),
                str(event.get("message", "n/a")),
                str(event.get("timestamp", "n/a")),
            )
        console.print(table)


def _render_rich_bitpro_paper_equity_curve(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    summary = payload.get("equity_summary")
    summary = summary if isinstance(summary, dict) else {}
    points = payload.get("equity_curve")
    points = points if isinstance(points, list) else []
    summary_text = "\n".join(
        [
            f"策略: {payload.get('strategy_id', 'all')}",
            (
                "权益: points={count}, sample={sample}, latest={latest}, "
                "latest_drawdown={latest_dd}, max_drawdown={max_dd}"
            ).format(
                count=summary.get("count", len(points)),
                sample=summary.get("sample_count", len(points)),
                latest=summary.get("latest_equity", "n/a"),
                latest_dd=_format_percent(summary.get("latest_drawdown_pct")),
                max_dd=_format_percent(summary.get("max_drawdown_pct")),
            ),
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary_text, title="BitPro 模拟盘权益曲线", border_style="cyan"))
    if points:
        table = Table(
            title="Paper Equity Curve",
            show_header=True,
            header_style="bold",
            expand=True,
        )
        table.add_column("Time", ratio=2)
        table.add_column("Equity", justify="right", ratio=2)
        table.add_column("Drawdown", justify="right", ratio=2)
        for point in points[:10]:
            if not isinstance(point, dict):
                continue
            table.add_row(
                str(point.get("timestamp", "n/a")),
                str(point.get("equity", "n/a")),
                _format_percent(point.get("drawdown_pct")),
            )
        console.print(table)


def _render_rich_bitpro_paper_monitor_snapshot(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    drift = payload.get("drift")
    drift = drift if isinstance(drift, dict) else {}
    alerts = drift.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    data_gaps = drift.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []

    summary_text = "\n".join(
        [
            ("快照: {snapshot}, strategy={strategy}, previous={previous}").format(
                snapshot=payload.get("snapshot_id", "n/a"),
                strategy=payload.get("strategy_id", "all"),
                previous=payload.get("previous_snapshot_id") or "none",
            ),
            ("指标: equity={equity}, pnl={pnl}, drawdown={drawdown}, errors={errors}").format(
                equity=_format_number(metrics.get("latest_equity")),
                pnl=_format_percent(metrics.get("total_pnl_pct")),
                drawdown=_format_percent(metrics.get("max_drawdown_pct")),
                errors=metrics.get("error_count", "n/a"),
            ),
            (
                "漂移: mode={mode}, equity_delta={equity_delta}, pnl_delta={pnl_delta}, "
                "drawdown_delta={drawdown_delta}, error_delta={error_delta}"
            ).format(
                mode=drift.get("mode", "unknown"),
                equity_delta=_format_number(drift.get("equity_delta")),
                pnl_delta=_format_percent(drift.get("total_pnl_delta_pct")),
                drawdown_delta=_format_percent(drift.get("max_drawdown_delta_pct")),
                error_delta=drift.get("error_count_delta", "n/a"),
            ),
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary_text, title="BitPro 模拟盘监控快照", border_style="magenta"))

    if alerts or data_gaps:
        table = Table(title="Snapshot Findings", show_header=True, header_style="bold", expand=True)
        table.add_column("Type", ratio=2)
        table.add_column("Code", ratio=3)
        table.add_column("Message", ratio=7, overflow="fold")
        for alert in alerts:
            if isinstance(alert, dict):
                table.add_row(
                    str(alert.get("level", "info")),
                    str(alert.get("code", "unknown")),
                    str(alert.get("message", "n/a")),
                )
        for gap in data_gaps:
            table.add_row("gap", "-", str(gap))
        console.print(table)


def _render_rich_bitpro_backtest_results(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    result_filter = payload.get("filter")
    result_filter = result_filter if isinstance(result_filter, dict) else {}
    metric = str(result_filter.get("metric", "total_return_pct"))
    min_return = result_filter.get("min_total_return_pct")
    filter_text = (
        f"{metric} > {_format_percent(min_return)}" if min_return is not None else "未设置收益阈值"
    )
    results = payload.get("results")
    results = results if isinstance(results, list) else []
    top_result = next((row for row in results if isinstance(row, dict)), None)
    top_line = "最高: n/a"
    if top_result is not None:
        top_line = (
            "最高: result #{id} / strategy #{strategy_id} | "
            "总收益 {total_return} | 回撤 {drawdown} | 交易 {trades}"
        ).format(
            id=top_result.get("id", "n/a"),
            strategy_id=top_result.get("strategy_id", "n/a"),
            total_return=_format_percent(top_result.get("total_return_pct")),
            drawdown=_format_percent(top_result.get("max_drawdown_pct")),
            trades=top_result.get("trade_count", "n/a"),
        )
    summary = "\n".join(
        [
            f"总收益口径: {metric}",
            f"筛选: {filter_text}",
            (
                f"命中 {payload.get('result_count', 0)} / "
                f"原始 {payload.get('raw_result_count', 'n/a')}"
            ),
            top_line,
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary, title="BitPro 回测排行", border_style="green"))

    if not results:
        console.print(Panel("没有匹配的 BitPro 回测结果。", border_style="yellow"))
        return

    table = Table(title="Top Results", show_header=True, header_style="bold", expand=True)
    table.add_column("#", justify="right", no_wrap=True, ratio=1)
    table.add_column("策略", ratio=6, overflow="fold")
    table.add_column("收益", ratio=2, overflow="fold")
    table.add_column("风险/质量", ratio=3, overflow="fold")
    table.add_column("区间", ratio=3, overflow="fold")
    for index, row in enumerate(results[:20], start=1):
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(index),
            (
                f"result #{row.get('id', 'n/a')} / strategy #{row.get('strategy_id', 'n/a')}\n"
                f"{_format_strategy_name(row.get('strategy_name', 'n/a'))}"
            ),
            (
                f"总 {_format_percent(row.get('total_return_pct'))}\n"
                f"年 {_format_percent(row.get('annual_return_pct'))}"
            ),
            (
                f"回撤 {_format_percent(row.get('max_drawdown_pct'))}\n"
                f"夏普 {_format_number(row.get('sharpe_ratio'))}\n"
                f"胜率 {_format_percent(row.get('win_rate_pct'))}\n"
                f"交易 {row.get('trade_count', 'n/a')}"
            ),
            _format_period(row.get("start_date"), row.get("end_date")),
        )
    console.print(table)


def _render_rich_bitpro_paper_strategy_performance(
    payload: dict[str, Any], *, console: Any
) -> None:
    from rich.table import Table

    summary = payload.get("performance_summary")
    summary = summary if isinstance(summary, dict) else {}
    table = Table(
        title=("模拟盘策略绩效 · {comparable}/{total} 可比 · {status}").format(
            comparable=summary.get("comparable_count", 0),
            total=summary.get("reported_total", 0),
            status=summary.get("ranking_status", "partial"),
        )
    )
    for column in ("排名", "策略", "收益", "回撤", "Sharpe"):
        table.add_column(column)
    strategies = payload.get("strategies")
    strategies = strategies if isinstance(strategies, list) else []
    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue
        table.add_row(
            str(strategy.get("rank", "-")),
            f"#{strategy.get('strategy_id', 'n/a')} {strategy.get('strategy_name', 'n/a')}",
            _format_percent(strategy.get("return_pct")),
            _format_percent(strategy.get("max_drawdown_pct")),
            _format_number(strategy.get("sharpe_ratio")),
        )
    console.print(table)


_BITPRO_ARTIFACT_LABELS = {
    "equity_curve": "权益曲线",
    "trades": "交易",
    "orders": "订单",
    "fills": "成交",
    "drawdown_series": "回撤序列",
}


def _render_rich_bitpro_backtest_detail(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    result = payload.get("result")
    result = result if isinstance(result, dict) else {}
    metrics = result.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    summary = "\n".join(
        [
            (
                f"result #{result.get('id', payload.get('backtest_id', 'n/a'))} / "
                f"strategy #{result.get('strategy_id', 'n/a')}"
            ),
            _format_strategy_name(result.get("strategy_name", "n/a")),
            (
                f"状态 {result.get('status', 'n/a')} | 周期 {result.get('timeframe', 'n/a')} | "
                f"区间 {_format_period(result.get('start_date'), result.get('end_date'))}"
            ),
        ]
    )
    console.print(Panel(summary, title="BitPro 回测详情", border_style="green"))

    metric_table = Table(title="核心指标", show_header=True, header_style="bold")
    metric_table.add_column("指标", no_wrap=True)
    metric_table.add_column("数值", justify="right")
    metric_table.add_row(
        "收益",
        Text(
            _format_percent(metrics.get("total_return_pct")),
            style=_rich_numeric_style(metrics.get("total_return_pct"), positive="green"),
        ),
    )
    metric_table.add_row(
        "最大回撤",
        Text(
            _format_percent(metrics.get("max_drawdown_pct")),
            style=_rich_drawdown_style(metrics.get("max_drawdown_pct")),
        ),
    )
    metric_table.add_row(
        "夏普",
        Text(
            _format_number(metrics.get("sharpe_ratio")),
            style=_rich_numeric_style(metrics.get("sharpe_ratio"), positive="cyan"),
        ),
    )
    metric_table.add_row(
        "胜率",
        Text(_format_percent(metrics.get("win_rate_pct")), style="cyan"),
    )
    metric_table.add_row("交易次数", Text(str(metrics.get("trade_count", "n/a")), style="white"))
    console.print(metric_table)

    artifact_summary = payload.get("artifact_summary")
    artifact_summary = artifact_summary if isinstance(artifact_summary, dict) else {}
    if not artifact_summary:
        return
    table = Table(title="数据样本", show_header=True, header_style="bold")
    table.add_column("数据")
    table.add_column("状态")
    table.add_column("条数", justify="right")
    table.add_column("展示", justify="right")
    for key, label in _BITPRO_ARTIFACT_LABELS.items():
        info = artifact_summary.get(key)
        if not isinstance(info, dict):
            continue
        table.add_row(
            label,
            "可用" if info.get("available") else "不可用",
            str(info.get("count", 0)),
            str(info.get("sample_count", 0)),
        )
    console.print(table)


def _rich_numeric_style(value: object, *, positive: str) -> str:
    number = _coerce_float(value)
    if number is None:
        return "dim"
    if number > 0:
        return positive
    if number < 0:
        return "red"
    return "white"


def _rich_drawdown_style(value: object) -> str:
    number = _coerce_float(value)
    if number is None:
        return "dim"
    if abs(number) <= 5:
        return "green"
    if abs(number) <= 15:
        return "yellow"
    return "red"


def _render_structured_report(run: dict[str, Any], *, output: TextIO) -> bool:
    if _prefer_final_agent_report(run):
        return False
    report = run.get("report_json", {})
    if isinstance(report, dict):
        report_blocks = report.get("report_blocks")
        if isinstance(report_blocks, list) and report_blocks:
            rendered = render_report_blocks(report_blocks, audit=_show_report_block_audit())
            if rendered.strip():
                print(rendered, file=output)
                return True
    if _prefer_final_report(run):
        return False
    if _prefer_compact_paper_report(run):
        _render_compact_bitpro_paper_report(run, output=output)
        return True
    if _prefer_market_final_report(run):
        return False
    if not isinstance(report, dict) or not report:
        return False
    if isinstance(report.get("top_movers"), list):
        _render_structured_market_summary(report, output=output)
        return True
    trace_events = run.get("trace_events", [])
    if isinstance(trace_events, list) and _has_structured_market_tool_output(trace_events):
        _render_structured_tool_report(trace_events, report=report, output=output)
        return True
    return False


def _prefer_final_report(run: dict[str, Any]) -> bool:
    if _report_source_forces_tool_output():
        return False
    markdown = str(run.get("report_markdown", "")).strip()
    if not markdown or _is_noisy_paper_markdown(markdown):
        return False
    return bool(_paper_tool_outputs_by_tool(run))


def _prefer_final_agent_report(run: dict[str, Any]) -> bool:
    """Use the completed Agent answer by default; audit modes opt into tool blocks."""
    if _report_source_forces_tool_output():
        return False
    markdown = str(run.get("report_markdown", "")).strip()
    if not markdown or _is_noisy_paper_markdown(markdown):
        return False
    if _prefer_final_world_model_report(run) or _prefer_final_report(run):
        return True
    report = run.get("report_json")
    report_blocks = report.get("report_blocks") if isinstance(report, dict) else None
    return isinstance(report_blocks, list) and bool(report_blocks)


def _prefer_final_world_model_report(run: dict[str, Any]) -> bool:
    """Keep the operator-facing conclusion ahead of WorldState audit blocks.

    WorldState blocks remain persisted for the web console and explicit audit
    views. In a terminal's default answer mode, the planner's final response is
    the concise interpretation the operator actually requested.
    """
    if _report_source_forces_tool_output():
        return False
    markdown = str(run.get("report_markdown", "")).strip()
    if not markdown:
        return False
    report = run.get("report_json")
    if isinstance(report, dict):
        calls = report.get("tool_calls")
        if isinstance(calls, list) and any(
            isinstance(call, dict) and call.get("tool") == "world_model_snapshot" for call in calls
        ):
            return True
    trace_events = run.get("trace_events")
    return isinstance(trace_events, list) and any(
        isinstance(event, dict) and event.get("tool_name") == "world_model_snapshot"
        for event in trace_events
    )


def _prefer_compact_paper_report(run: dict[str, Any]) -> bool:
    if _report_source_forces_tool_output():
        return False
    if _prefer_final_report(run):
        return False
    return bool(_paper_tool_outputs_by_tool(run))


def _prefer_market_final_report(run: dict[str, Any]) -> bool:
    if _report_source_forces_tool_output():
        return False
    markdown = str(run.get("report_markdown", "")).strip()
    if not markdown:
        return False
    return bool(_market_detail_tool_outputs(run))


def _report_source_forces_tool_output() -> bool:
    source = os.getenv("HYPERTRADE_REPORT_SOURCE", "final").strip().lower()
    return source in {"tool", "tools", "trace", "structured", "audit", "provenance"}


def _show_report_block_audit() -> bool:
    source = os.getenv("HYPERTRADE_REPORT_SOURCE", "final").strip().lower()
    if source in {"audit", "audits", "provenance", "source", "sources"}:
        return True
    return _show_full_trace()


def _market_detail_tool_outputs(run: dict[str, Any]) -> list[dict[str, Any]]:
    trace_events = run.get("trace_events", [])
    if not isinstance(trace_events, list):
        return []
    outputs: list[dict[str, Any]] = []
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        if event.get("tool_name") not in {"market_ticker", "market_candles", "market_compare"}:
            continue
        payload = event.get("output_json", {})
        if isinstance(payload, dict) and payload.get("found", True):
            outputs.append(payload)
    return outputs


def _paper_tool_outputs_by_tool(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    trace_events = run.get("trace_events", [])
    if not isinstance(trace_events, list):
        return {}
    outputs: dict[str, dict[str, Any]] = {}
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        tool_name = str(event.get("tool_name", ""))
        if tool_name not in _FINAL_REPORT_FIRST_TOOLS:
            continue
        payload = event.get("output_json", {})
        if isinstance(payload, dict) and payload.get("found", True):
            outputs[tool_name] = payload
    return outputs


def _is_noisy_paper_markdown(markdown: str) -> bool:
    if "BitPro 模拟盘状态" not in markdown:
        return False
    noisy_markers = (
        "权益点 ",
        "运行策略清单:",
        "Paper Equity Curve",
        "还有 ",
    )
    if any(marker in markdown for marker in noisy_markers):
        return True
    if any("|" in line for line in markdown.splitlines()):
        return True
    bullet_count = sum(1 for line in markdown.splitlines() if line.lstrip().startswith("- "))
    return bullet_count > 14


_FINAL_REPORT_FIRST_TOOLS = {
    "bitpro_paper_dashboard",
    "bitpro_paper_strategy_performance",
    "bitpro_paper_events",
    "bitpro_paper_equity_curve",
    "bitpro_paper_monitor_snapshot",
}


def _render_compact_bitpro_paper_report(run: dict[str, Any], *, output: TextIO) -> None:
    lines = _compact_bitpro_paper_lines(run)
    print("", file=output)
    print("BitPro 模拟盘摘要:", file=output)
    for line in lines:
        print(f"- {line}", file=output)


def _render_rich_compact_bitpro_paper_report(run: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel

    lines = _compact_bitpro_paper_lines(run)
    console.print(Panel("\n".join(lines), title="BitPro 模拟盘摘要", border_style="cyan"))


def _compact_bitpro_paper_lines(run: dict[str, Any]) -> list[str]:
    payloads = _paper_tool_outputs_by_tool(run)
    lines: list[str] = []

    matrix = payloads.get("bitpro_paper_strategy_performance")
    if matrix:
        summary = matrix.get("performance_summary")
        summary = summary if isinstance(summary, dict) else {}
        strategies = matrix.get("strategies")
        strategies = strategies if isinstance(strategies, list) else []
        lines.append(
            "绩效排名: comparable={comparable}/{total}, status={status}".format(
                comparable=summary.get("comparable_count", len(strategies)),
                total=summary.get("reported_total", len(strategies)),
                status=summary.get("ranking_status", "partial"),
            )
        )
        for strategy in strategies[:5]:
            if not isinstance(strategy, dict):
                continue
            lines.append(
                "#{rank} strategy={strategy_id} {name}, return={return_pct}, "
                "drawdown={drawdown}, sharpe={sharpe}".format(
                    rank=strategy.get("rank", "-"),
                    strategy_id=strategy.get("strategy_id", "n/a"),
                    name=strategy.get("strategy_name", "n/a"),
                    return_pct=_format_percent(strategy.get("return_pct")),
                    drawdown=_format_percent(strategy.get("max_drawdown_pct")),
                    sharpe=_format_number(strategy.get("sharpe_ratio")),
                )
            )

    dashboard = payloads.get("bitpro_paper_dashboard")
    if dashboard:
        dashboard_payload = dashboard.get("dashboard")
        dashboard_payload = dashboard_payload if isinstance(dashboard_payload, dict) else {}
        system = dashboard_payload.get("system")
        system = system if isinstance(system, dict) else {}
        equity = dashboard_payload.get("equity")
        equity = equity if isinstance(equity, dict) else {}
        performance = dashboard_payload.get("performance")
        performance = performance if isinstance(performance, dict) else {}
        lines.append(
            (
                "运行: strategy_id={strategy_id}, {state}/{mode}, equity={equity}, "
                "PnL={pnl}, drawdown={drawdown}"
            ).format(
                strategy_id=_display_value(system.get("strategy_id")),
                state=_display_value(system.get("state")),
                mode=_display_value(system.get("mode")),
                equity=_format_number(equity.get("current")),
                pnl=_format_percent(performance.get("total_pnl_pct")),
                drawdown=_format_percent(performance.get("max_drawdown")),
            )
        )
        monitor = dashboard.get("monitor_summary")
        monitor = monitor if isinstance(monitor, dict) else {}
        inventory = monitor.get("running_inventory")
        inventory = inventory if isinstance(inventory, dict) else {}
        if inventory:
            coverage = "truncated" if inventory.get("is_truncated") else "complete"
            lines.append(
                "覆盖: running listed={listed}, total={total}, {coverage}".format(
                    listed=inventory.get("listed_count", "n/a"),
                    total=inventory.get("reported_total", "n/a"),
                    coverage=coverage,
                )
            )
        _append_compact_paper_findings(lines, monitor)

    equity_payload = payloads.get("bitpro_paper_equity_curve")
    if equity_payload:
        summary = equity_payload.get("equity_summary")
        summary = summary if isinstance(summary, dict) else {}
        points = equity_payload.get("equity_curve")
        points = points if isinstance(points, list) else []
        lines.append(
            (
                "权益曲线: strategy={strategy}, points={points}, latest={latest}, "
                "latest_drawdown={latest_dd}, max_drawdown={max_dd}"
            ).format(
                strategy=_display_value(equity_payload.get("strategy_id"), default="all"),
                points=summary.get("count", len(points)),
                latest=_format_number(summary.get("latest_equity")),
                latest_dd=_format_percent(summary.get("latest_drawdown_pct")),
                max_dd=_format_percent(summary.get("max_drawdown_pct")),
            )
        )

    events_payload = payloads.get("bitpro_paper_events")
    if events_payload:
        summary = events_payload.get("event_summary")
        summary = summary if isinstance(summary, dict) else {}
        events = events_payload.get("events")
        events = events if isinstance(events, list) else []
        lines.append(
            "事件: strategy={strategy}, count={count}, errors={errors}, latest={latest}".format(
                strategy=_display_value(events_payload.get("strategy_id"), default="all"),
                count=summary.get("count", len(events)),
                errors=summary.get("error_count", 0),
                latest=_display_value(summary.get("latest_event_at")),
            )
        )

    snapshot = payloads.get("bitpro_paper_monitor_snapshot")
    if snapshot:
        metrics = snapshot.get("metrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        drift = snapshot.get("drift")
        drift = drift if isinstance(drift, dict) else {}
        lines.append(
            (
                "快照: strategy={strategy}, equity={equity}, PnL={pnl}, drawdown={drawdown}, "
                "error_delta={error_delta}"
            ).format(
                strategy=_display_value(snapshot.get("strategy_id"), default="all"),
                equity=_format_number(metrics.get("latest_equity")),
                pnl=_format_percent(metrics.get("total_pnl_pct")),
                drawdown=_format_percent(metrics.get("max_drawdown_pct")),
                error_delta=drift.get("error_count_delta", "n/a"),
            )
        )
        _append_compact_paper_findings(lines, drift)

    return lines or ["暂无可用的模拟盘摘要。"]


def _append_compact_paper_findings(lines: list[str], payload: dict[str, Any]) -> None:
    findings: list[str] = []
    alerts = payload.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    for alert in alerts[:2]:
        if isinstance(alert, dict):
            findings.append(
                "{level}/{code}: {message}".format(
                    level=alert.get("level", "info"),
                    code=alert.get("code", "unknown"),
                    message=alert.get("message", "n/a"),
                )
            )
    gaps = payload.get("data_gaps")
    gaps = gaps if isinstance(gaps, list) else []
    for gap in gaps[:2]:
        findings.append(f"gap: {gap}")
    if findings:
        lines.append("提醒: " + "；".join(findings))


def _display_value(value: object, *, default: str = "n/a") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _render_structured_market_summary(report: dict[str, Any], *, output: TextIO) -> None:
    print("Market Report", file=output)
    print(f"Scope: {report.get('market_scope', 'unknown')}", file=output)
    print(f"Trigger: {report.get('trigger', 'unknown')}", file=output)
    print(f"Source: {report.get('data_source', 'unknown')}", file=output)
    print(f"As of UTC: {report.get('as_of_utc', 'n/a')}", file=output)
    print("", file=output)

    heat = report.get("heat_summary")
    if isinstance(heat, dict):
        print("Market heat:", file=output)
        print(f"- Conclusion: {heat.get('conclusion', '当前市场热度暂不可用。')}", file=output)
        print(
            (
                "- Sample: {sample_count}; advancers={advancers_count} "
                "({advancers_pct}%); decliners={decliners_count} "
                "({decliners_pct}%); average_change={average_change_pct}%"
            ).format(
                sample_count=heat.get("sample_count", 0),
                advancers_count=heat.get("advancers_count", 0),
                advancers_pct=heat.get("advancers_pct", "0.000000"),
                decliners_count=heat.get("decliners_count", 0),
                decliners_pct=heat.get("decliners_pct", "0.000000"),
                average_change_pct=heat.get("average_change_pct", "0.000000"),
            ),
            file=output,
        )
        print(
            "- Strongest/weakest: {top_gainer} / {top_loser}".format(
                top_gainer=heat.get("top_gainer", "n/a"),
                top_loser=heat.get("top_loser", "n/a"),
            ),
            file=output,
        )
        print("", file=output)

    movers = report.get("top_movers", [])
    print("Top movers:", file=output)
    if isinstance(movers, list) and movers:
        for mover in movers[:10]:
            if not isinstance(mover, dict):
                continue
            print(
                "- {inst_id}: last={last}, utc0_change={change}%, volume_24h={volume}".format(
                    inst_id=mover.get("inst_id", "unknown"),
                    last=mover.get("last", "n/a"),
                    change=mover.get("change_utc0_pct", "n/a"),
                    volume=mover.get("volume_ccy_24h", "n/a"),
                ),
                file=output,
            )
    else:
        reason = report.get("unavailable_reason", "no movers available")
        print(f"- unavailable: {reason}", file=output)

    hits = report.get("rag_hits", [])
    if isinstance(hits, list) and hits:
        print("", file=output)
        print("Knowledge hits:", file=output)
        for hit in hits[:5]:
            if not isinstance(hit, dict):
                continue
            print(
                f"- {hit.get('source_path', 'unknown')} score={hit.get('score', 'n/a')}",
                file=output,
            )


def _has_structured_market_tool_output(trace_events: list[Any]) -> bool:
    supported_tools = {
        "market_ticker",
        "market_candles",
        "market_compare",
        "bitpro_backtest_list_results",
        "bitpro_backtest_get_result",
        "bitpro_paper_dashboard",
        "bitpro_paper_strategy_performance",
        "bitpro_paper_events",
        "bitpro_paper_equity_curve",
        "bitpro_paper_monitor_snapshot",
    }
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("output_json")
        if (
            event.get("tool_name") in supported_tools
            and isinstance(payload, dict)
            and payload.get("found", True)
        ):
            return True
    return False


def _render_structured_tool_report(
    trace_events: list[Any],
    *,
    report: dict[str, Any],
    output: TextIO,
) -> None:
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("output_json", {})
        if not isinstance(payload, dict) or not payload.get("found", True):
            continue
        tool_name = str(event.get("tool_name", ""))
        if tool_name == "market_ticker":
            _render_tool_ticker_block(payload, output=output)
        elif tool_name == "market_candles":
            _render_tool_candles_block(payload, output=output)
        elif tool_name == "market_compare":
            _render_tool_compare_block(payload, output=output)
        elif tool_name == "bitpro_backtest_list_results":
            _render_tool_bitpro_backtest_block(payload, output=output)
        elif tool_name == "bitpro_backtest_get_result":
            _render_tool_bitpro_backtest_detail_block(payload, output=output)
        elif tool_name == "bitpro_paper_dashboard":
            _render_tool_bitpro_paper_block(payload, output=output)
        elif tool_name == "bitpro_paper_strategy_performance":
            _render_tool_bitpro_paper_strategy_performance_block(payload, output=output)
        elif tool_name == "bitpro_paper_events":
            _render_tool_bitpro_paper_events_block(payload, output=output)
        elif tool_name == "bitpro_paper_equity_curve":
            _render_tool_bitpro_paper_equity_block(payload, output=output)
        elif tool_name == "bitpro_paper_monitor_snapshot":
            _render_tool_bitpro_paper_monitor_snapshot_block(payload, output=output)


def _render_tool_ticker_block(payload: dict[str, Any], *, output: TextIO) -> None:
    print("", file=output)
    print("Ticker:", file=output)
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Last: {payload.get('last', 'n/a')}", file=output)
    print(f"- UTC0 change: {payload.get('change_utc0_pct', 'n/a')}%", file=output)
    print(f"- 24h volume: {payload.get('volume_ccy_24h', 'n/a')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)


def _render_tool_candles_block(payload: dict[str, Any], *, output: TextIO) -> None:
    print("", file=output)
    print("Trend:", file=output)
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Candles: {payload.get('candle_count', 'n/a')}", file=output)
    print(f"- Return: {payload.get('return_pct', 'n/a')}%", file=output)
    print(f"- Bias: {payload.get('trend_bias', 'unknown')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)


def _render_tool_compare_block(payload: dict[str, Any], *, output: TextIO) -> None:
    print("", file=output)
    print("Relative strength:", file=output)
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Leader: {payload.get('leader', 'unknown')}", file=output)
    rankings = payload.get("rankings", [])
    if isinstance(rankings, list):
        for row in rankings:
            if not isinstance(row, dict):
                continue
            print(
                "- {rank}. {inst_id}: score={score}, return={return_pct}%, bias={bias}".format(
                    rank=row.get("rank", "?"),
                    inst_id=row.get("inst_id", "unknown"),
                    score=row.get("strength_score", "n/a"),
                    return_pct=row.get("return_pct", "n/a"),
                    bias=row.get("trend_bias", "unknown"),
                ),
                file=output,
            )


def _render_tool_bitpro_paper_block(payload: dict[str, Any], *, output: TextIO) -> None:
    dashboard = payload.get("dashboard")
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    system = dashboard.get("system")
    system = system if isinstance(system, dict) else {}
    equity = dashboard.get("equity")
    equity = equity if isinstance(equity, dict) else {}
    performance = dashboard.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    scope = payload.get("paper_scope")
    scope = scope if isinstance(scope, dict) else {}
    running = payload.get("running_strategies")
    running = running if isinstance(running, dict) else {}
    monitor = payload.get("monitor_summary")
    monitor = monitor if isinstance(monitor, dict) else {}
    inventory = monitor.get("running_inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    alerts = monitor.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    data_gaps = monitor.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []
    actions = monitor.get("recommended_actions")
    actions = actions if isinstance(actions, list) else []

    print("", file=output)
    print("BitPro Paper Monitor:", file=output)
    print(f"- Contract: {payload.get('contract_version', 'unknown')}", file=output)
    print(f"- Dashboard scope: {scope.get('dashboard_scope', 'unknown')}", file=output)
    print(
        "- Current dashboard: strategy_id={strategy_id}, {name}, "
        "state={state}, mode={mode}, uptime={uptime}".format(
            strategy_id=system.get("strategy_id", "n/a"),
            name=system.get("strategy", "n/a"),
            state=system.get("state", "n/a"),
            mode=system.get("mode", "n/a"),
            uptime=system.get("uptime", "n/a"),
        ),
        file=output,
    )
    print(
        "- Performance: equity={equity}, pnl={pnl}, sharpe={sharpe}, drawdown={drawdown}".format(
            equity=_format_number(equity.get("current")),
            pnl=_format_percent(performance.get("total_pnl_pct")),
            sharpe=_format_number(performance.get("sharpe_ratio"), digits=4),
            drawdown=_format_percent(performance.get("max_drawdown")),
        ),
        file=output,
    )
    if monitor:
        listed = inventory.get("listed_count", 0)
        total = inventory.get("reported_total", running.get("total", listed))
        state = "truncated" if inventory.get("is_truncated") else "complete"
        print(f"- Monitor: {monitor.get('mode', 'unknown')}", file=output)
        print(
            f"- Running coverage: listed={listed}, reported_total={total}, state={state}",
            file=output,
        )
        if alerts:
            print("- Alerts:", file=output)
            for alert in alerts:
                if isinstance(alert, dict):
                    print(
                        "  - {level}/{code}: {message}".format(
                            level=alert.get("level", "info"),
                            code=alert.get("code", "unknown"),
                            message=alert.get("message", "n/a"),
                        ),
                        file=output,
                    )
        if data_gaps:
            print("- Data gaps:", file=output)
            for gap in data_gaps:
                print(f"  - {gap}", file=output)
        if actions:
            print("- Suggested read-only actions:", file=output)
            for action in actions:
                if isinstance(action, dict):
                    print(
                        "  - {action}: {message}".format(
                            action=action.get("action", "observe"),
                            message=action.get("message", "n/a"),
                        ),
                        file=output,
                    )


def _render_tool_bitpro_paper_strategy_performance_block(
    payload: dict[str, Any], *, output: TextIO
) -> None:
    summary = payload.get("performance_summary")
    summary = summary if isinstance(summary, dict) else {}
    print("BitPro Paper Strategy Performance:", file=output)
    print(
        "- coverage={comparable}/{total}, ranking_status={status}".format(
            comparable=summary.get("comparable_count", 0),
            total=summary.get("reported_total", 0),
            status=summary.get("ranking_status", "partial"),
        ),
        file=output,
    )
    strategies = payload.get("strategies")
    strategies = strategies if isinstance(strategies, list) else []
    for strategy in strategies[:10]:
        if not isinstance(strategy, dict):
            continue
        print(
            "- #{rank} strategy_id={strategy_id}, return={return_pct}, "
            "drawdown={drawdown}, sharpe={sharpe}".format(
                rank=strategy.get("rank", "-"),
                strategy_id=strategy.get("strategy_id", "n/a"),
                return_pct=_format_percent(strategy.get("return_pct")),
                drawdown=_format_percent(strategy.get("max_drawdown_pct")),
                sharpe=_format_number(strategy.get("sharpe_ratio")),
            ),
            file=output,
        )
    print("", file=output)


def _render_tool_bitpro_paper_events_block(payload: dict[str, Any], *, output: TextIO) -> None:
    summary = payload.get("event_summary")
    summary = summary if isinstance(summary, dict) else {}
    events = payload.get("events")
    events = events if isinstance(events, list) else []

    print("", file=output)
    print("BitPro Paper Events:", file=output)
    print(f"- Strategy: {payload.get('strategy_id', 'all')}", file=output)
    print(
        "- Events: count={count}, sample={sample}, errors={errors}, latest={latest}".format(
            count=summary.get("count", len(events)),
            sample=summary.get("sample_count", len(events)),
            errors=summary.get("error_count", 0),
            latest=summary.get("latest_event_at", "n/a"),
        ),
        file=output,
    )
    for event in events[:10]:
        if not isinstance(event, dict):
            continue
        print(
            "- {id} {level}/{type}: {message} ({timestamp})".format(
                id=event.get("id", "n/a"),
                level=event.get("level", "info"),
                type=event.get("type", "event"),
                message=event.get("message", "n/a"),
                timestamp=event.get("timestamp", "n/a"),
            ),
            file=output,
        )


def _render_tool_bitpro_paper_equity_block(payload: dict[str, Any], *, output: TextIO) -> None:
    summary = payload.get("equity_summary")
    summary = summary if isinstance(summary, dict) else {}
    points = payload.get("equity_curve")
    points = points if isinstance(points, list) else []

    print("", file=output)
    print("BitPro Paper Equity Curve:", file=output)
    print(f"- Strategy: {payload.get('strategy_id', 'all')}", file=output)
    print(
        "- Equity: points={count}, sample={sample}, latest={latest}, "
        "max_drawdown={max_drawdown}%".format(
            count=summary.get("count", len(points)),
            sample=summary.get("sample_count", len(points)),
            latest=summary.get("latest_equity", "n/a"),
            max_drawdown=summary.get("max_drawdown_pct", "n/a"),
        ),
        file=output,
    )
    for point in points[:10]:
        if not isinstance(point, dict):
            continue
        print(
            "- {timestamp}: equity={equity}, drawdown={drawdown}%".format(
                timestamp=point.get("timestamp", "n/a"),
                equity=point.get("equity", "n/a"),
                drawdown=point.get("drawdown_pct", "n/a"),
            ),
            file=output,
        )


def _render_tool_bitpro_paper_monitor_snapshot_block(
    payload: dict[str, Any],
    *,
    output: TextIO,
) -> None:
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    drift = payload.get("drift")
    drift = drift if isinstance(drift, dict) else {}
    alerts = drift.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    data_gaps = drift.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []

    print("", file=output)
    print("BitPro Paper Monitor Snapshot:", file=output)
    print(
        "- Snapshot: {snapshot}, strategy={strategy}, previous={previous}".format(
            snapshot=payload.get("snapshot_id", "n/a"),
            strategy=payload.get("strategy_id", "all"),
            previous=payload.get("previous_snapshot_id") or "none",
        ),
        file=output,
    )
    print(
        "- Metrics: equity={equity}, pnl={pnl}, drawdown={drawdown}, errors={errors}".format(
            equity=_format_number(metrics.get("latest_equity")),
            pnl=_format_percent(metrics.get("total_pnl_pct")),
            drawdown=_format_percent(metrics.get("max_drawdown_pct")),
            errors=metrics.get("error_count", "n/a"),
        ),
        file=output,
    )
    print(
        "- Drift: mode={mode}, equity_delta={equity_delta}, pnl_delta={pnl_delta}, "
        "drawdown_delta={drawdown_delta}, error_delta={error_delta}".format(
            mode=drift.get("mode", "unknown"),
            equity_delta=_format_number(drift.get("equity_delta")),
            pnl_delta=_format_percent(drift.get("total_pnl_delta_pct")),
            drawdown_delta=_format_percent(drift.get("max_drawdown_delta_pct")),
            error_delta=drift.get("error_count_delta", "n/a"),
        ),
        file=output,
    )
    if alerts:
        print("- Alerts:", file=output)
        for alert in alerts:
            if isinstance(alert, dict):
                print(
                    "  - {level}/{code}: {message}".format(
                        level=alert.get("level", "info"),
                        code=alert.get("code", "unknown"),
                        message=alert.get("message", "n/a"),
                    ),
                    file=output,
                )
    if data_gaps:
        print("- Data gaps:", file=output)
        for gap in data_gaps:
            print(f"  - {gap}", file=output)


def _render_tool_bitpro_backtest_block(payload: dict[str, Any], *, output: TextIO) -> None:
    result_filter = payload.get("filter")
    result_filter = result_filter if isinstance(result_filter, dict) else {}
    metric = str(result_filter.get("metric", "total_return_pct"))
    min_return = result_filter.get("min_total_return_pct")
    filter_text = (
        f"{metric} > {_format_percent(min_return)}"
        if min_return is not None
        else "no return threshold"
    )
    print("", file=output)
    print("BitPro backtest ranking:", file=output)
    print(f"- Metric: {metric} (actual total backtest return)", file=output)
    print(f"- Filter: {filter_text}", file=output)
    print(
        "- Matches: {result_count} / raw {raw_count}".format(
            result_count=payload.get("result_count", 0),
            raw_count=payload.get("raw_result_count", "n/a"),
        ),
        file=output,
    )
    results = payload.get("results")
    results = results if isinstance(results, list) else []
    if not results:
        print("- No matching BitPro backtest results.", file=output)
        return
    print("Top results:", file=output)
    for index, row in enumerate(results[:20], start=1):
        if not isinstance(row, dict):
            continue
        print(
            (
                "- {rank}. result #{id} / strategy #{strategy_id}: {name} | "
                "return {total_return}, annual {annual_return}, "
                "drawdown {drawdown}, sharpe {sharpe}, win {win_rate}, "
                "trades {trades}, period {period}"
            ).format(
                rank=index,
                id=row.get("id", "n/a"),
                strategy_id=row.get("strategy_id", "n/a"),
                name=row.get("strategy_name", "n/a"),
                total_return=_format_percent(row.get("total_return_pct")),
                annual_return=_format_percent(row.get("annual_return_pct")),
                drawdown=_format_percent(row.get("max_drawdown_pct")),
                sharpe=_format_number(row.get("sharpe_ratio")),
                win_rate=_format_percent(row.get("win_rate_pct")),
                trades=row.get("trade_count", "n/a"),
                period=_format_period(row.get("start_date"), row.get("end_date")),
            ),
            file=output,
        )


def _render_tool_bitpro_backtest_detail_block(
    payload: dict[str, Any],
    *,
    output: TextIO,
) -> None:
    result = payload.get("result")
    result = result if isinstance(result, dict) else {}
    metrics = result.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    print("", file=output)
    print("BitPro 回测详情:", file=output)
    print(
        "- 结果: #{id} / strategy #{strategy_id}: {name}".format(
            id=result.get("id", payload.get("backtest_id", "n/a")),
            strategy_id=result.get("strategy_id", "n/a"),
            name=_format_strategy_name(result.get("strategy_name", "n/a")),
        ),
        file=output,
    )
    print(
        "- 状态: {status} | 周期: {timeframe} | 区间: {period}".format(
            status=result.get("status", "n/a"),
            timeframe=result.get("timeframe", "n/a"),
            period=_format_period(result.get("start_date"), result.get("end_date")),
        ),
        file=output,
    )
    print("- 核心指标:", file=output)
    print(f"  - 收益: {_format_percent(metrics.get('total_return_pct'))}", file=output)
    print(f"  - 最大回撤: {_format_percent(metrics.get('max_drawdown_pct'))}", file=output)
    print(f"  - 夏普: {_format_number(metrics.get('sharpe_ratio'))}", file=output)
    print(f"  - 胜率: {_format_percent(metrics.get('win_rate_pct'))}", file=output)
    print(f"  - 交易次数: {metrics.get('trade_count', 'n/a')}", file=output)
    artifact_summary = payload.get("artifact_summary")
    artifact_summary = artifact_summary if isinstance(artifact_summary, dict) else {}
    if artifact_summary:
        print("- 数据样本:", file=output)
        for key, label in _BITPRO_ARTIFACT_LABELS.items():
            info = artifact_summary.get(key)
            if not isinstance(info, dict):
                continue
            state = "可用" if info.get("available") else "不可用"
            print(
                "  - {label}: {state}，{count} 条，展示 {sample_count} 条样本".format(
                    label=label,
                    state=state,
                    count=info.get("count", 0),
                    sample_count=info.get("sample_count", 0),
                ),
                file=output,
            )


def _format_number(value: object, *, digits: int = 2) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "n/a"}:
        return "n/a"
    number = _coerce_float(value)
    if number is None:
        return str(value)
    formatted = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _coerce_float(value: object) -> float | None:
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "n/a"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _format_percent(value: object, *, digits: int = 2) -> str:
    text = _format_number(value, digits=digits)
    if text == "n/a":
        return text
    return f"{text}%"


def _format_strategy_name(value: object) -> str:
    text = str(value or "n/a").strip()
    parts = [part.strip() for part in text.split("·") if part.strip()]
    if len(parts) >= 2:
        return f"{parts[0]}\n{' · '.join(parts[1:])}"
    return text


def _format_period(start: object, end: object) -> str:
    start_text = str(start or "n/a")
    end_text = str(end or "n/a")
    if start_text == "n/a" and end_text == "n/a":
        return "n/a"
    return f"{start_text}\n{end_text}"


def render_thread_turn_stream(
    client: CanonicalThreadClient,
    thread_id: str,
    prompt: str,
    *,
    after: int = 0,
    output: TextIO | None = None,
) -> int:
    """Render one canonical Turn and reject an SSE EOF without terminal state."""

    output = output or sys.stdout
    created = client.start_thread_turn(
        thread_id,
        prompt,
        client_message_id=new_id("cli_msg"),
    )
    turn = created.get("turn")
    if not isinstance(turn, dict) or not str(turn.get("turn_id") or ""):
        raise RuntimeError("canonical Turn creation returned no turn_id")
    turn_id = str(turn["turn_id"])
    cursor = max(after, 0)
    terminal = ""
    answer = ""
    animator = _ThinkingAnimator(output)
    animator.start("Thinking")
    try:
        for attempt in range(3):
            for event in client.stream_thread_events(thread_id, after=cursor):
                cursor = max(cursor, int(event.get("cursor") or 0))
                payload = event.get("payload")
                if not isinstance(payload, dict) or str(payload.get("turn_id") or "") != turn_id:
                    continue
                event_name = str(event.get("event") or event.get("event_type") or "")
                if event_name == "turn.accepted":
                    animator.update("Turn accepted")
                elif event_name == "turn.started":
                    animator.update("Running governed Mission")
                elif event_name == "tool_call.started":
                    content = payload.get("content")
                    capability = (
                        str(content.get("capability_id") or "governed_read")
                        if isinstance(content, dict)
                        else "governed_read"
                    )
                    animator.update(f"Executing {capability}")
                elif event_name == "evidence_ready.completed":
                    animator.update("Evidence ready")
                elif event_name == "agent_message.completed":
                    content = payload.get("content")
                    if isinstance(content, dict):
                        answer = str(content.get("text") or "")
                    animator.update("Rendering answer")
                elif event_name in {
                    "turn.completed",
                    "turn.failed",
                    "turn.cancelled",
                    "turn.expired",
                }:
                    terminal = event_name
                    break
            if terminal:
                break
            durable = client.get_thread_turn(thread_id, turn_id)
            durable_turn = durable.get("turn")
            status = str(durable_turn.get("status") or "") if isinstance(durable_turn, dict) else ""
            if status in {"completed", "failed", "cancelled", "expired"}:
                terminal = f"turn.{status}"
                answer = answer or _canonical_answer(durable)
                break
            if status in {"waiting_input", "waiting_approval"}:
                animator.stop()
                print(_canonical_waiting_message(durable, status), file=output)
                return cursor
            if attempt < 2:
                animator.update("Reconnecting event stream")
    except httpx.HTTPError as exc:
        animator.stop()
        _print_remote_api_error(exc, output=output)
        return cursor
    finally:
        animator.stop()

    if not terminal:
        print(
            _paint(
                "Protocol error: canonical Turn stream ended without a terminal event.",
                "warning",
                output=output,
            ),
            file=output,
        )
        return cursor
    durable = client.get_thread_turn(thread_id, turn_id)
    answer = answer or _canonical_answer(durable)
    if answer:
        print("", file=output)
        print(answer, file=output)
    elif terminal != "turn.completed":
        print(_paint(f"Agent Turn ended as {terminal}.", "warning", output=output), file=output)
    return cursor


def _canonical_answer(payload: dict[str, Any]) -> str:
    items = payload.get("items")
    if not isinstance(items, list):
        return ""
    for item in reversed(items):
        if not isinstance(item, dict) or item.get("item_type") != "agent_message":
            continue
        content = item.get("content")
        if isinstance(content, dict):
            return str(content.get("text") or "")
    return ""


def _canonical_waiting_message(payload: dict[str, Any], status: str) -> str:
    items = payload.get("items")
    if isinstance(items, list):
        for item in reversed(items):
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, dict) and content.get("message"):
                return str(content["message"])
    return f"Agent Turn is {status}."


def render_run_stream(
    client: AgentClient,
    prompt: str,
    *,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    animator = _ThinkingAnimator(output)
    try:
        events = client.run_agent_events(prompt)
    except AttributeError:
        animator.start("Thinking")
        try:
            run = client.run_agent(prompt)
        except httpx.HTTPError as exc:
            animator.stop()
            _print_remote_api_error(exc, output=output)
            return
        finally:
            animator.stop()
        render_run(run, output=output)
        return
    final_run: dict[str, Any] | None = None
    stream_failed = False
    terminal_error: dict[str, str] | None = None
    stream_run_ids: list[str] = []
    animator.start("Thinking")
    try:
        for event in events:
            if not isinstance(event, dict):
                continue
            event_name = str(event.get("event", "message"))
            for key in ("mission_id", "task_id", "run_id"):
                value = str(event.get(key) or "").strip()
                if value and value not in stream_run_ids:
                    stream_run_ids.append(value)
            if event_name == "run_started":
                if _show_full_progress():
                    animator.print_line(
                        _status_line(
                            f"Agent status: run created ({event.get('run_id', 'pending')})",
                            "info",
                            output=output,
                        )
                    )
                    animator.print_line(
                        _status_line(
                            "Agent status: planning next tool call",
                            "muted",
                            output=output,
                        )
                    )
                else:
                    animator.print_line(
                        _status_line(
                            f"Agent: running ({event.get('run_id', 'pending')})",
                            "info",
                            output=output,
                        )
                    )
                animator.update("Planning next tool call")
            elif event_name == "tool_started":
                tool_name = event.get("tool_name", "unknown")
                if _show_full_progress():
                    animator.print_line(
                        _status_line(
                            f"Agent status: executing tool {tool_name}",
                            "tool",
                            output=output,
                        )
                    )
                animator.update(f"Executing tool {tool_name}")
            elif event_name == "tool_completed":
                tool_name = event.get("tool_name", "unknown")
                status = event.get("status", "completed")
                style = "success" if status == "completed" else "warning"
                if _show_full_progress() or status != "completed":
                    animator.print_line(
                        _status_line(
                            f"Agent status: tool {tool_name} {status}",
                            style,
                            output=output,
                        )
                    )
                if _show_full_progress():
                    animator.print_line(
                        _status_line("Agent status: planning next step", "muted", output=output)
                    )
                animator.update("Planning next step")
            elif event_name == "run_completed":
                if _show_full_progress():
                    animator.print_line(
                        _status_line(
                            "Agent status: generating final report",
                            "info",
                            output=output,
                        )
                    )
                    animator.print_line(
                        _status_line(
                            f"Agent status: run completed ({event.get('run_id', 'unknown')})",
                            "success",
                            output=output,
                        )
                    )
                else:
                    animator.print_line(
                        _status_line(
                            f"Agent: completed ({event.get('run_id', 'unknown')})",
                            "success",
                            output=output,
                        )
                    )
                animator.update("Generating final report")
                if isinstance(event.get("run"), dict):
                    final_run = dict(event["run"])
            elif event_name == "final":
                if isinstance(event.get("run"), dict):
                    animator.update("Rendering final report")
                    final_run = dict(event["run"])
                else:
                    terminal_error = _stream_terminal_error(event)
            elif event_name == "error" or (event_name == "warning" and event.get("code")):
                terminal_error = _stream_terminal_error(event)
    except httpx.HTTPError as exc:
        stream_failed = True
        animator.print_line(_status_line(_format_remote_api_error(exc), "error", output=output))
    finally:
        animator.stop()
    if stream_failed:
        return
    recovered_run_id = ""
    if final_run is None:
        final_run, recovered_run_id = _recover_stream_final_run(client, stream_run_ids)
        if final_run is not None:
            print(
                _status_line(
                    f"Recovered final report ({recovered_run_id}).",
                    "warning",
                    output=output,
                ),
                file=output,
            )
    if final_run is not None:
        print("", file=output)
        render_run(final_run, output=output)
    else:
        print(
            _paint(
                _stream_terminal_error_message(terminal_error, stream_run_ids),
                "warning",
                output=output,
            ),
            file=output,
        )


def _stream_terminal_error(event: dict[str, Any]) -> dict[str, str]:
    """Keep terminal error output actionable without exposing internal failures."""

    error = event.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "stream_runtime_error")
    else:
        code = str(event.get("code") or "stream_runtime_error")
    return {"code": code[:96]}


def _recover_stream_final_run(
    client: AgentClient,
    run_ids: Sequence[str],
) -> tuple[dict[str, Any] | None, str]:
    """Read the durable run projection after an SSE EOF before declaring loss."""

    terminal_statuses = {"completed", "failed", "canceled", "cancelled", "budget_exhausted"}
    for run_id in reversed(run_ids):
        try:
            candidate = client.get_run(run_id)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            continue
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("status") or "").casefold() in terminal_statuses:
            return candidate, run_id
    return None, ""


def _stream_terminal_error_message(
    error: dict[str, str] | None,
    run_ids: Sequence[str],
) -> str:
    reference = run_ids[-1] if run_ids else "unavailable"
    if error is not None:
        return (
            f"本次运行未生成最终报告（{error['code']}），跟踪编号：{reference}。"
            "请执行 /runs 查看状态后重试。"
        )
    return (
        f"流式连接在最终报告前结束，跟踪编号：{reference}。"
        "请执行 /runs 查看状态后重试。"
    )


def _status_line(text: str, style: str, *, output: TextIO) -> str:
    return _paint(text, style, output=output)


def _show_full_progress() -> bool:
    value = os.getenv("HYPERTRADE_PROGRESS", "compact").strip().lower()
    return value in {"all", "debug", "full", "verbose"}


def _format_remote_api_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 401:
            return (
                "Remote API request failed (401). "
                "Run ht /login again and confirm the username/password."
            )
        return (
            f"Remote API request failed ({status_code}). "
            "The service may be deploying, or the credentials may be invalid."
        )
    if isinstance(exc, httpx.ReadTimeout):
        return (
            "Remote API connection timed out while waiting for the run. "
            "The run may still be continuing remotely; retry in a moment or check /runs."
        )
    return (
        "Remote API connection failed. The run may still be continuing remotely; "
        "the network or service may have restarted. Retry in a moment or check /runs."
    )


def _print_remote_api_error(exc: httpx.HTTPError, *, output: TextIO) -> None:
    print(_paint(_format_remote_api_error(exc), "error", output=output), file=output)


class _ThinkingAnimator:
    def __init__(self, output: TextIO, *, interval_seconds: float = 0.12) -> None:
        self.output = output
        self.interval_seconds = interval_seconds
        self.enabled = _should_render_thinking_animation(output)
        self.started_at = 0.0
        self.frame_index = 0
        self.message = "Thinking"
        self.rendered = False
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def start(self, message: str) -> None:
        self.message = message
        self.started_at = time.monotonic()
        if not self.enabled:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        with self.lock:
            self._render_locked()
        self.thread.start()

    def update(self, message: str) -> None:
        self.message = message
        if not self.enabled:
            return
        with self.lock:
            self._render_locked()

    def print_line(self, text: str) -> None:
        if not self.enabled:
            print(text, file=self.output)
            return
        with self.lock:
            self._clear_locked()
            print(text, file=self.output)
            self._render_locked()

    def stop(self) -> None:
        if not self.enabled:
            return
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=self.interval_seconds * 2)
        with self.lock:
            self._clear_locked()
            self.output.flush()

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            with self.lock:
                self.frame_index += 1
                self._render_locked()

    def _render_locked(self) -> None:
        elapsed_ms = int((time.monotonic() - self.started_at) * 1000)
        frame = THINKING_FRAMES[self.frame_index % len(THINKING_FRAMES)]
        first = f"+ Thought: {elapsed_ms}ms"
        second = f": {frame} {self.message}"
        if self.rendered:
            self.output.write("\x1b[2A")
        self.output.write(f"\r\x1b[2K{first}\n")
        self.output.write(f"\r\x1b[2K{second}\n")
        self.output.flush()
        self.rendered = True

    def _clear_locked(self) -> None:
        if not self.rendered:
            return
        self.output.write("\x1b[2A\r\x1b[2K\x1b[1B\r\x1b[2K\x1b[1A\r")
        self.output.flush()
        self.rendered = False


def _should_render_thinking_animation(output: TextIO) -> bool:
    override = os.getenv("HYPERTRADE_THINKING_ANIMATION", "").strip().lower()
    if override in {"0", "false", "off", "no"}:
        return False
    if override in {"1", "true", "on", "yes"}:
        return True
    return bool(getattr(output, "isatty", lambda: False)())


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hypertrade",
        description="HyperTrade Agent CLI conversation harness.",
    )
    runtime_group = parser.add_mutually_exclusive_group()
    runtime_group.add_argument(
        "--remote",
        metavar="URL",
        help="Connect to a running HyperTrade API instead of using the local Agent runtime.",
    )
    runtime_group.add_argument(
        "--local",
        action="store_true",
        help="Force the local standalone Agent runtime.",
    )
    subparsers = parser.add_subparsers(dest="command")
    ask = subparsers.add_parser("ask", help="Run one Agent prompt through the HyperTrade API.")
    ask.add_argument("prompt", nargs="+")
    subparsers.add_parser("chat", help="Start an interactive Agent conversation loop.")
    tui = subparsers.add_parser("tui", help="Start the optional Textual research workbench.")
    tui.add_argument("--session", default="", help="Initially select tasks from this session.")
    subparsers.add_parser("login", help="Save remote HyperTrade API login for this machine.")
    subparsers.add_parser("/login", help="Save remote HyperTrade API login for this machine.")
    return parser


def _use_local_runtime(args: argparse.Namespace) -> bool:
    if args.local:
        return True
    if args.remote:
        return False
    return "HYPERTRADE_API_URL" not in os.environ and "HYPERTRADE_API_URL" not in read_client_env()


def _default_client_factory(config: CliConfig, local: bool) -> AgentClient:
    if local:
        return LocalAgentClient(settings=_local_runtime_settings())
    return AgentApiClient(config)


def _completed_run_to_dict(run: CompletedAgentRun) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": run.id,
        "status": run.status,
        "report_markdown": run.report_markdown,
        "report_json": run.report_json,
        "run_state_json": run.run_state_json,
        "trace_events": [_trace_to_dict(event) for event in run.trace_events],
    }
    task_meta = run.report_json.get("task")
    payload["legacy_run"] = not isinstance(task_meta, dict)
    if isinstance(task_meta, dict):
        payload["task_id"] = task_meta.get("task_id")
        payload["session_id"] = task_meta.get("session_id")
    return payload


def _tool_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "requires_approval": tool.requires_approval,
        "policy": tool.policy.to_dict(),
    }


def _nested_value(payload: dict[str, Any], section: str, key: str) -> Any:
    value = payload.get(section, {})
    if not isinstance(value, dict):
        return None
    return value.get(key)


def _nested_int(payload: dict[str, Any], section: str, key: str) -> int:
    value = _nested_value(payload, section, key)
    return int(value) if isinstance(value, int | float | str) and str(value).isdigit() else 0


def _redact_database_url(database_url: str) -> str:
    if "@" not in database_url or "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.rsplit("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _trace_to_dict(event: TraceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "tool_name": event.tool_name,
        "status": event.status,
        "input_json": event.input_json,
        "output_json": event.output_json,
        "created_at": event.created_at.isoformat(),
    }


def _parse_sse_event(event_name: str, data_lines: list[str]) -> dict[str, Any]:
    payload = json.loads("\n".join(data_lines))
    if isinstance(payload, dict):
        payload.setdefault("event", event_name)
        return payload
    return {"event": event_name, "data": payload}
