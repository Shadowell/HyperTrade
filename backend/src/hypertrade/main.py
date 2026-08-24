"""FastAPI application wiring for the HyperTrade harness.

The API is the bridge between the operator surfaces (frontend `/harness`, CLI
remote mode, tests) and the backend services. Endpoints stay thin: they validate
HTTP input, call the Agent/tool service, and return redacted runtime state.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from queue import Queue
from threading import Thread
from typing import Annotated, Any, Literal, Protocol, cast

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from hypertrade.agent.checkpoints import TaskCheckpointService, checkpoint_to_dict
from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.agent.observability import AgentObservabilityService
from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService, session_to_dict
from hypertrade.agent.task_events import TaskEventService, task_event_to_dict
from hypertrade.agent.task_executor import (
    AgentTaskExecutor,
    TaskControlInterrupted,
    TaskExecutionError,
)
from hypertrade.agent.tasks import (
    AgentTaskCreate,
    AgentTaskService,
    InvalidTaskTransition,
    TaskControl,
    task_to_dict,
)
from hypertrade.arc.router import router as arc_router
from hypertrade.arc.store import configure_store
from hypertrade.backtest.service import BacktestService
from hypertrade.bitpro.mcp import (
    BitProMcpClient,
    BitProMcpError,
    BitProToolAdapter,
    bitpro_capabilities,
)
from hypertrade.config import Settings, get_settings
from hypertrade.connectors.registry import ConnectorRegistry
from hypertrade.db import (
    AgentRun,
    Database,
    LiveOrderIntent,
    MarketTicker,
    MemoryItem,
    RagChunk,
    RagDocument,
    TraceEvent,
    new_id,
    utc_now,
)
from hypertrade.evals.service import AgentEvalSuite
from hypertrade.global_market.service import GlobalMarketService
from hypertrade.live.service import LiveOrderIntentService
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.governance import (
    MemoryAssertionRelationV1,
    MemoryAssertionReviewV1,
    MemoryAssertionService,
    MemoryAssertionV1,
)
from hypertrade.memory.service import MemoryService
from hypertrade.monitoring import MonitorService
from hypertrade.paper.service import PaperTradingService
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
from hypertrade.portfolio.market_regime_v2 import MarketRegimeSnapshotServiceV2
from hypertrade.portfolio.regime_shadow import RegimeShadowAllocatorServiceV2
from hypertrade.portfolio.regime_shadow_schemas import (
    MarketRegimeCaptureV2,
    RegimeShadowBuildV2,
)
from hypertrade.portfolio.shadow import ShadowPortfolioService
from hypertrade.portfolio.shadow_schemas import (
    ShadowPortfolioBuildV1,
    ShadowPortfolioReviewV1,
)
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.rag.service import RagHit, RagService
from hypertrade.research.discovery import StrategyDiscoveryService
from hypertrade.research.evidence import EvidenceService, EvidenceSourceUnavailable
from hypertrade.research.evidence_schemas import (
    EvidenceLifecycleRequest,
    EvidenceSupersedeRequest,
    ResearchEvidenceInput,
)
from hypertrade.research.evolution import StrategyEvolutionService
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import ExperimentRegister
from hypertrade.research.graph import (
    ResearchGraphCreate,
    ResearchGraphRuntime,
    ResearchGraphTaskService,
    graph_topology_projection,
)
from hypertrade.research.graph_tools import (
    BuiltinResearchToolRunner,
    ResearchBitProReadAdapter,
)
from hypertrade.research.legacy_evidence import LegacyEvidenceAdapter
from hypertrade.research.orchestrator import BitProResearchAdapter, ResearchOrchestrator
from hypertrade.research.paper_incubation import (
    AutonomousPaperIncubationService,
    PaperIncubationAdapter,
)
from hypertrade.research.paper_incubation_schemas import (
    PaperIncubationActionV1,
    PaperIncubationCaptureV1,
    PaperMandateCreateV1,
)
from hypertrade.research.paper_observation import PaperObservationService
from hypertrade.research.paper_promotion import PaperPromotionAdapter, PaperPromotionService
from hypertrade.research.robustness import RobustnessValidationService
from hypertrade.research.role_provider import (
    ChatResearchRoleProvider,
    DeterministicGapRoleProvider,
)
from hypertrade.research.schemas import ResearchJobCreate, ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.strategy_card_schemas import StrategyCardDecisionRequestV1
from hypertrade.research.strategy_cards import StrategyCardService
from hypertrade.research.triggers import (
    ResearchTriggerCreate,
    ResearchTriggerService,
    TriggerControlUpdate,
    TriggerEvent,
)
from hypertrade.research.validation_v2 import UnifiedStrategyValidationService
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
from hypertrade.runtime.adapters.effect_store import (
    InMemoryEffectGovernanceStore,
    SqlEffectGovernanceStore,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.research_planner import build_mission_planner
from hypertrade.runtime.adapters.sandbox import (
    InMemorySandboxStore,
    SqlSandboxStore,
    StrategySandbox,
    UdsSandboxRunner,
    is_pinned_oci_image,
)
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.adapters.supervisor import (
    BoundedSupervisor,
    InMemorySupervisionStore,
    RoleCatalog,
    SqlSupervisionStore,
    deterministic_worker,
)
from hypertrade.runtime.adapters.thread_store import (
    InMemoryThreadStore,
    SqlAlchemyThreadStore,
)
from hypertrade.runtime.adapters.tool_runtime import (
    GovernedToolExecutor,
    InMemoryObservationStore,
    SqlObservationStore,
    builtin_handlers,
)
from hypertrade.runtime.api.thread_turn import build_thread_turn_router
from hypertrade.runtime.application.effect_governance import EffectGovernanceService
from hypertrade.runtime.application.entrypoint import (
    is_mission_canary,
    mission_request_for_prompt,
    mission_run_projection,
)
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.application.thread_service import ThreadTurnService
from hypertrade.runtime.domain.capabilities import (
    CapabilityProposalV1,
    CapabilityReviewV1,
)
from hypertrade.runtime.domain.context import MissionArtifactCreateV1
from hypertrade.runtime.domain.models import (
    TERMINAL_STATUSES,
    MissionCreate,
    MissionStatus,
    SteeringEventV1,
)
from hypertrade.runtime.domain.sandbox import ImportReviewV1, SandboxRequestV1
from hypertrade.runtime.domain.supervision import TeamRunRequestV1
from hypertrade.skills.lifecycle import (
    ApprovedSkillLoader,
    SkillApprovalV1,
    SkillEvaluationV1,
    SkillLifecycleService,
    SkillProposalV1,
    SkillRollbackV1,
)
from hypertrade.strategy.experiment import StrategyExperimentService
from hypertrade.strategy.library import StrategyLibraryService
from hypertrade.strategy.sdk import Candle
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolDefinition, ToolRegistry
from hypertrade.world_model.defensive_actions import DefensiveActionEngine
from hypertrade.world_model.service import WorldModelService

SESSION_COOKIE = "hypertrade_session"
logger = logging.getLogger("hypertrade.main")


class BitProApiAdapter(Protocol):
    def health(self) -> dict[str, Any]:
        """Return BitPro capability and health preflight state."""
        ...

    def market_klines(self, *, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        """Read BitPro K-lines through the MCP tool contract."""
        ...

    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        """Read BitPro paper/simulation dashboard state."""
        ...

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        """Read one immutable BitPro paper evidence snapshot."""
        ...

    def paper_events(
        self,
        *,
        strategy_id: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read BitPro paper/simulation events."""
        ...

    def paper_equity_curve(
        self,
        *,
        strategy_id: int | None = None,
        sample_limit: int = 50,
    ) -> dict[str, Any]:
        """Read BitPro paper/simulation equity curve."""
        ...

    def live_positions(
        self,
        *,
        exchange: str = "okx",
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Read BitPro live positions for diagnostics only."""
        ...


def _bitpro_read_or_502(
    adapter: BitProApiAdapter,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        return operation()
    except BitProMcpError as exc:
        tool_calls = getattr(adapter, "last_tool_calls", [])
        if not isinstance(tool_calls, list):
            tool_calls = []
        raise HTTPException(
            status_code=502,
            detail={
                "status": "unavailable",
                "service": "bitpro_mcp",
                "message": str(exc),
                "status_code": exc.status_code,
                "tool_calls": tool_calls,
            },
        ) from exc


class LoginPayload(BaseModel):
    username: str
    password: str


class AgentRunPayload(BaseModel):
    prompt: str
    evaluation_mode: bool = False
    evaluation_case_id: str = Field(default="", max_length=96)
    prior_turns: list[str] = Field(default_factory=list, max_length=8)


class MissionControlPayload(BaseModel):
    action: Literal["pause", "resume", "cancel"]
    reason: str = Field(default="operator_control", max_length=500)


class ProviderSelectionPayload(BaseModel):
    provider: str
    model: str = ""


class PaperControlPayload(BaseModel):
    action: Literal["pause", "resume", "close", "reset"]
    symbol: str | None = None


class StrategyResearchPayload(BaseModel):
    prompt: str


class ResearchJobCancelPayload(BaseModel):
    reason: str = "operator_canceled"


class TriggerEnabledPayload(BaseModel):
    enabled: bool
    reason: str = Field(min_length=1, max_length=1000)


class PaperPromotionRequestPayload(BaseModel):
    evidence_id: str
    reason: str


class PaperPromotionApprovalPayload(BaseModel):
    reason: str
    idempotency_key: str


class PaperMandateStatePayload(BaseModel):
    status: Literal["active", "paused", "revoked"]
    reason: str = Field(min_length=1, max_length=1000)


class BacktestPayload(BaseModel):
    research_id: str = ""
    strategy_key: str = "momentum_breakout_v1"
    initial_cash: str = "100000"
    candles: list[Candle] | None = None
    use_live_candles: bool = False
    symbol: str = "BTC"
    bar: str = "1H"
    candle_limit: int = 100
    candle_source: str = "sample"


class MarketComparePayload(BaseModel):
    symbols: list[str]
    bar: str = "4H"
    limit: int = 100


class LiveOrderIntentPayload(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    size: str
    order_type: Literal["market", "limit"] = "market"
    price: str | None = None
    reason: str = ""


class LiveOrderDecisionPayload(BaseModel):
    reason: str = ""


class DefensiveActionPayload(BaseModel):
    action_id: str
    idempotency_key: str = ""
    world_state: dict[str, Any] | None = None


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    bitpro_adapter: BitProApiAdapter | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    database = db or Database(app_settings.database_url)
    configure_store(database)
    mission_store = (
        InMemoryMissionStore()
        if database.url == "sqlite:///:memory:"
        else SqlAlchemyMissionStore(database.url)
    )
    thread_store = (
        InMemoryThreadStore()
        if database.url == "sqlite:///:memory:"
        else SqlAlchemyThreadStore(database.url)
    )
    capability_catalog = (
        InMemoryCapabilityCatalog()
        if database.url == "sqlite:///:memory:"
        else SqlCapabilityCatalog(database.url)
    )
    observation_store = (
        InMemoryObservationStore()
        if database.url == "sqlite:///:memory:"
        else SqlObservationStore(database.url)
    )
    paper_effect_store = (
        InMemoryEffectGovernanceStore()
        if database.url == "sqlite:///:memory:"
        else SqlEffectGovernanceStore(database.url)
    )
    paper_effect_governance = EffectGovernanceService(
        paper_effect_store,
        enabled_write_environments=frozenset({"paper"}),
    )
    context_artifact_store = (
        InMemoryContextArtifactStore()
        if database.url == "sqlite:///:memory:"
        else SqlContextArtifactStore(database.url)
    )
    context_engine = ContextArtifactEngine(context_artifact_store)
    supervision_store = (
        InMemorySupervisionStore()
        if database.url == "sqlite:///:memory:"
        else SqlSupervisionStore(database.url)
    )
    role_catalog = RoleCatalog()
    supervisor = BoundedSupervisor(supervision_store, role_catalog)
    sandbox_store = (
        InMemorySandboxStore()
        if database.url == "sqlite:///:memory:"
        else SqlSandboxStore(database.url)
    )
    production_sandbox = app_settings.app_env.casefold() in {"production", "staging"}
    sandbox_runner = (
        UdsSandboxRunner(
            app_settings.strategy_sandbox_image,
            app_settings.strategy_sandbox_socket_path,
        )
        if production_sandbox and is_pinned_oci_image(app_settings.strategy_sandbox_image)
        else None
    )
    strategy_sandbox = StrategySandbox(
        sandbox_store,
        production=production_sandbox,
        runner=sandbox_runner,
    )
    # Evaluation fixtures are an explicit, environment-gated read source.  A
    # production process cannot select them even if its feature flag is set.
    from hypertrade.runtime.application.evaluation_fixtures import (
        IsolatedLiveStrategyFixtureAdapter,
        operator_eval_fixture_enabled,
    )

    def mission_bitpro_adapter() -> Any:
        if operator_eval_fixture_enabled(
            app_env=app_settings.app_env,
            enabled=app_settings.operator_eval_fixtures_enabled,
        ):
            return IsolatedLiveStrategyFixtureAdapter()
        return BitProToolAdapter(BitProMcpClient(settings=app_settings))

    tool_executor = GovernedToolExecutor(
        capability_catalog,
        builtin_handlers(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            bitpro_adapter_factory=mission_bitpro_adapter,
        ),
        observations=observation_store,
    )
    # A provider may propose a plan but never gains dispatch authority. The
    # fallback is deterministic and the catalog remains the pre-dispatch gate.
    mission_runtime = MissionRuntime(
        mission_store,
        build_mission_planner(
            app_settings,
            ProviderRuntime(app_settings).get_chat_provider(
                selected=app_settings.active_chat_provider,
            ),
        ),
        tool_executor,
        CatalogCapabilityPolicy(capability_catalog),
        context_engine,
    )
    thread_turn_service = ThreadTurnService(
        thread_store,
        mission_store,
        mission_runtime,
        worker_enabled=app_settings.mission_runtime_worker_enabled,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if app_settings.database_url.startswith("sqlite"):
            database.create_all()
        await capability_catalog.bootstrap(builtin_capabilities())
        try:
            yield
        finally:
            for resource in (
                mission_store,
                thread_store,
                capability_catalog,
                observation_store,
                paper_effect_store,
                context_artifact_store,
                supervision_store,
                sandbox_store,
            ):
                dispose = getattr(resource, "dispose", None)
                if dispose is not None:
                    await dispose()

    app = FastAPI(title="HyperTrade API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.db = database
    app.state.active_chat_provider = app_settings.active_chat_provider
    app.state.active_chat_model = ""
    app.state.bitpro_adapter = bitpro_adapter
    app.state.mission_store = mission_store
    app.state.mission_runtime = mission_runtime
    app.state.thread_store = thread_store
    app.state.thread_turn_service = thread_turn_service
    app.state.capability_catalog = capability_catalog
    app.state.tool_executor = tool_executor
    app.state.paper_effect_governance = paper_effect_governance
    app.state.context_engine = context_engine
    app.state.context_artifact_store = context_artifact_store
    app.state.supervisor = supervisor
    app.state.supervision_store = supervision_store
    app.state.strategy_sandbox = strategy_sandbox
    app.state.sandbox_store = sandbox_store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            app_settings.frontend_origin,
            "http://localhost:3333",
            "http://127.0.0.1:3333",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def serializer() -> URLSafeSerializer:
        return URLSafeSerializer(app_settings.session_secret, salt="hypertrade-session")

    def require_admin(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            username = serializer().loads(token)
        except BadSignature as exc:
            raise HTTPException(status_code=401, detail="Invalid session") from exc
        if username != app_settings.admin_username:
            raise HTTPException(status_code=403, detail="Forbidden")
        # ARC records who decided a live promote. Reading the identity off the verified
        # session rather than a client-supplied header keeps that audit trail unforgeable.
        request.state.admin_user = str(username)
        return str(username)

    AdminUser = Annotated[str, Depends(require_admin)]
    app.include_router(build_thread_turn_router(thread_turn_service, require_admin))
    # Per-route scopes live on the ARC router. A blanket require_admin would block
    # the service-token surface; mounting bare would reopen live-approval to anyone.
    app.include_router(arc_router)

    def mission_request_key(request: Request) -> str:
        supplied = request.headers.get("Idempotency-Key", "").strip()
        return supplied[:128] if supplied else new_id("missionreq")

    def legacy_agent_writes_disabled() -> bool:
        """At 100% Mission rollout, old Task state is a read-only archive."""

        return (
            app_settings.mission_runtime_enabled
            and app_settings.mission_runtime_canary_percent >= 100
        )

    def require_legacy_agent_write_enabled() -> None:
        if legacy_agent_writes_disabled():
            raise HTTPException(
                status_code=410,
                detail="Legacy AgentTask writes are disabled; create a Mission instead",
            )

    async def create_prompt_mission(
        prompt: str,
        *,
        actor: str,
        idempotency_key: str,
        evaluation_case_id: str = "",
        prior_turns: tuple[str, ...] = (),
    ) -> Any:
        return await mission_runtime.create(
            mission_request_for_prompt(
                prompt,
                actor=actor,
                idempotency_key=idempotency_key,
                evaluation_case_id=evaluation_case_id,
                prior_turns=prior_turns,
            )
        )

    def evaluation_case_id(payload: AgentRunPayload) -> str:
        """Allow deterministic fault fixtures only on the explicit isolated target."""

        case_id = payload.evaluation_case_id.strip()
        fixtures_disabled = (
            not payload.evaluation_mode or not app_settings.operator_eval_fixtures_enabled
        )
        if case_id and fixtures_disabled:
            raise HTTPException(status_code=409, detail="operator evaluation fixtures are disabled")
        return case_id

    async def await_worker_mission(mission_id: str) -> Any:
        """Follow the canonical event-backed projection; the worker owns dispatch."""

        while True:
            mission = await mission_store.get(mission_id)
            if mission.status in TERMINAL_STATUSES:
                return mission
            await asyncio.sleep(0.25)

    async def fail_mission_execution(mission_id: str) -> Any:
        """Terminalize an API-owned failure so public delivery never leaves a ghost run.

        The concrete exception is logged only on the server. The public projection
        remains a bounded failure response without provider, tool, or stack details.
        """

        current = await mission_store.get(mission_id)
        if current.status in TERMINAL_STATUSES:
            return current
        try:
            return await mission_store.transition(
                mission_id,
                expected_version=current.version,
                target=MissionStatus.FAILED,
                actor="mission_delivery",
                reason="mission_execution_failure",
                terminal_summary="Mission execution failed before validated evidence was produced.",
            )
        except ValueError:
            # A concurrent worker/control action may have terminalized the Mission.
            return await mission_store.get(mission_id)

    async def run_prompt_as_mission(
        prompt: str,
        *,
        actor: str,
        idempotency_key: str,
        evaluation_case_id: str = "",
        prior_turns: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        mission = await create_prompt_mission(
            prompt,
            actor=actor,
            idempotency_key=idempotency_key,
            evaluation_case_id=evaluation_case_id,
            prior_turns=prior_turns,
        )
        try:
            completed = (
                await await_worker_mission(mission.mission_id)
                if app_settings.mission_runtime_worker_enabled
                else await mission_runtime.run(mission.mission_id)
            )
        except Exception:  # noqa: BLE001 - boundary must retain a terminal public projection
            logger.exception("mission execution failed mission_id=%s", mission.mission_id)
            completed = await fail_mission_execution(mission.mission_id)
        return await mission_run_projection(completed, mission_store)

    def get_bitpro_adapter() -> BitProApiAdapter:
        if app.state.bitpro_adapter is None:
            app.state.bitpro_adapter = BitProToolAdapter(BitProMcpClient(settings=app_settings))
        adapter: BitProApiAdapter = app.state.bitpro_adapter
        return adapter

    def paper_incubation_service(
        *, external_access: bool = False
    ) -> AutonomousPaperIncubationService:
        return AutonomousPaperIncubationService(
            database,
            effect_governance=paper_effect_governance if external_access else None,
            bitpro_adapter=(
                cast(PaperIncubationAdapter, get_bitpro_adapter()) if external_access else None
            ),
        )

    def active_provider_models() -> dict[str, str]:
        active_model = str(getattr(app.state, "active_chat_model", "") or "")
        if not active_model:
            return {}
        return {str(app.state.active_chat_provider): active_model}

    def research_graph_runtime() -> ResearchGraphRuntime:
        chat_provider = ProviderRuntime(app_settings).get_chat_provider(
            selected=str(app.state.active_chat_provider),
            selected_model=str(app.state.active_chat_model),
        )
        role_provider = (
            ChatResearchRoleProvider(
                chat_provider,
                skill_loader=ApprovedSkillLoader(database),
            )
            if chat_provider is not None
            else DeterministicGapRoleProvider()
        )
        return ResearchGraphRuntime(
            database,
            provider=role_provider,
            tool_runner=BuiltinResearchToolRunner(
                database,
                bitpro_adapter=cast(ResearchBitProReadAdapter, get_bitpro_adapter()),
                knowledge_dir=app_settings.knowledge_dir,
            ),
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "hypertrade-api"}

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, response: Response) -> dict[str, str]:
        valid_username = payload.username == app_settings.admin_username
        valid_password = payload.password == app_settings.admin_password
        if not valid_username or not valid_password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        response.set_cookie(
            SESSION_COOKIE,
            serializer().dumps(payload.username),
            httponly=True,
            samesite="lax",
            secure=app_settings.cookie_secure,
        )
        return {"status": "ok", "username": payload.username}

    @app.post("/api/auth/logout")
    def logout(_: AdminUser, response: Response) -> dict[str, str]:
        response.delete_cookie(SESSION_COOKIE)
        return {"status": "ok"}

    @app.get("/api/auth/me")
    def me(username: AdminUser) -> dict[str, str]:
        return {"username": username}

    @app.get("/api/harness/providers")
    def providers() -> dict[str, list[dict[str, object]]]:
        return {
            "providers": ProviderRuntime(app_settings).list_providers(
                selected=str(app.state.active_chat_provider),
                selected_models=active_provider_models(),
            )
        }

    @app.post("/api/harness/provider-selection")
    def select_provider(payload: ProviderSelectionPayload, _: AdminUser) -> dict[str, Any]:
        requested = ProviderRuntime.normalize_provider_name(payload.provider)
        runtime = ProviderRuntime(app_settings)
        known = {str(provider["name"]) for provider in runtime.list_providers()}
        if requested not in known:
            raise HTTPException(status_code=400, detail="Unknown provider")
        try:
            selected_model = runtime.validate_model_choice(requested, payload.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app.state.active_chat_provider = requested
        app.state.active_chat_model = selected_model
        providers_payload = runtime.list_providers(
            selected=requested,
            selected_models=active_provider_models(),
        )
        selected = next(
            (provider for provider in providers_payload if provider["name"] == requested),
            providers_payload[0],
        )
        return {
            "default_provider": requested,
            "model": selected.get("model", ""),
            "providers": providers_payload,
        }

    @app.get("/api/harness/tools")
    def tools() -> dict[str, list[dict[str, object]]]:
        return {"tools": [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]}

    @app.get("/api/connectors/capabilities")
    def connector_capabilities() -> dict[str, object]:
        return ConnectorRegistry.default(settings=app_settings).capabilities_payload()

    @app.get("/api/evals/status")
    def eval_status() -> dict[str, Any]:
        return AgentEvalSuite().status()

    @app.get("/api/harness/overview")
    def harness_overview() -> dict[str, Any]:
        providers_payload = ProviderRuntime(app_settings).list_providers(
            selected=str(app.state.active_chat_provider),
            selected_models=active_provider_models(),
        )
        tools_payload = [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]
        connectors_payload = ConnectorRegistry.default(settings=app_settings).capabilities_payload()
        top_movers = [
            {
                "inst_id": row.inst_id,
                "last": str(row.last),
                "volume_ccy_24h": str(row.volume_ccy_24h),
                "change_utc0_pct": str(row.change_utc0_pct),
            }
            for row in MarketRepository(database).top_movers(limit=8)
        ]
        observability_summary = AgentObservabilityService(database).recent_summary()

        with database.session() as session:
            latest_market_at = session.scalar(select(func.max(MarketTicker.updated_at)))
            latest_memory_at = session.scalar(select(func.max(MemoryItem.created_at)))
            runs = session.scalars(
                select(AgentRun).order_by(desc(AgentRun.created_at)).limit(6)
            ).all()
            trace_events = session.scalars(
                select(TraceEvent).order_by(desc(TraceEvent.created_at)).limit(12)
            ).all()
            bitpro_contract = bitpro_capabilities()
            return {
                "generated_at": utc_now().isoformat(),
                "providers": providers_payload,
                "tools": tools_payload,
                "connectors": connectors_payload["connectors"],
                "market": {
                    "ticker_count": _count_rows(session, MarketTicker),
                    "latest_ticker_at": _iso_or_none(latest_market_at),
                    "latest_update_age_seconds": _age_seconds(latest_market_at),
                    "top_movers": top_movers,
                },
                "agent_runs": {
                    "total_count": _count_rows(session, AgentRun),
                    "recent": [_run_summary_to_dict(run) for run in runs],
                },
                "rag": {
                    "document_count": _count_rows(session, RagDocument),
                    "chunk_count": _count_rows(session, RagChunk),
                },
                "memory": {
                    "active_count": _count_rows(
                        session,
                        MemoryItem,
                        MemoryItem.disabled.is_(False),
                    ),
                    "total_count": _count_rows(session, MemoryItem),
                    "latest_created_at": _iso_or_none(latest_memory_at),
                },
                "trace": {
                    "total_count": _count_rows(session, TraceEvent),
                    "recent_events": [_trace_to_dict(event) for event in trace_events],
                },
                "observability": observability_summary,
                "paper": PaperTradingService(database, settings=app_settings).status(),
                "strategy_lab": {
                    "latest_research": StrategyResearchService(database).latest(),
                    "latest_backtest": BacktestService(database).latest(),
                    "latest_experiment": StrategyExperimentService(database).latest(),
                },
                "live_orders": {
                    "total_count": _count_rows(session, LiveOrderIntent),
                    "pending_approval_count": _count_rows(
                        session,
                        LiveOrderIntent,
                        LiveOrderIntent.status == "pending_approval",
                    ),
                    "recent": LiveOrderIntentService(database, settings=app_settings).list_recent(
                        limit=5
                    ),
                },
                "bitpro": {
                    "adapter": "mcp_non_live_lifecycle",
                    "configured": bool(app_settings.bitpro_mcp_api_base),
                    "api_base": app_settings.bitpro_mcp_api_base,
                    "auth_header": app_settings.bitpro_mcp_auth_header,
                    "token_configured": bool(app_settings.bitpro_mcp_api_token),
                    "token_source": "bitpro_settings_agent_token_or_server_env",
                    "remote_mcp": bitpro_contract["remote_mcp"],
                    "agent_auth": bitpro_contract["agent_auth"],
                    "tool_groups": bitpro_contract["tool_groups"],
                    "live_write_enabled": False,
                    "live_write_scope": "hypertrade_mcp_live_write_gate",
                    "live_write_note": (
                        "HyperTrade currently blocks BitPro MCP live write/order tools; "
                        "this is not BitPro runtime mode. Use BitPro live dashboard "
                        "or live read tools to inspect paper/live strategy state."
                    ),
                    "tools": [
                        "bitpro_capabilities",
                        "bitpro_health",
                        "market_klines",
                        "strategy_search",
                        "strategy_generate",
                        "strategy_create",
                        "strategy_update",
                        "backtest_start_job",
                        "backtest_get_job",
                        "paper_configure",
                        "paper_start",
                        "paper_pause",
                        "paper_resume",
                        "paper_stop",
                        "paper_dashboard",
                        "paper_events",
                        "paper_equity_curve",
                        "paper_monitor_snapshot",
                        "trading_positions",
                    ],
                },
                "evals": AgentEvalSuite().status(),
            }

    @app.get("/api/world-model/snapshot")
    def world_model_snapshot() -> dict[str, Any]:
        return WorldModelService(database, settings=app_settings).snapshot()

    @app.get("/api/world-model/portfolio")
    def world_model_portfolio() -> dict[str, Any]:
        portfolio = (
            WorldModelService(database, settings=app_settings)
            .snapshot()
            .get(
                "portfolio",
                {},
            )
        )
        return portfolio if isinstance(portfolio, dict) else {}

    @app.get("/api/research/strategy-cards")
    def list_strategy_cards(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyCardService(database).list()}

    @app.get("/api/research/evolution-runs")
    def list_strategy_evolution_runs(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyEvolutionService(database).list()}

    @app.get("/api/research/evolution-runs/{run_id}")
    def get_strategy_evolution_run(run_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return StrategyEvolutionService(database).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Strategy evolution run not found") from exc

    @app.get("/api/research/discovery-runs")
    def list_strategy_discovery_runs(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyDiscoveryService(database).list()}

    @app.get("/api/research/discovery-runs/{run_id}")
    def get_strategy_discovery_run(run_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return StrategyDiscoveryService(database).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Strategy discovery run not found") from exc

    @app.get("/api/research/unified-validations")
    def list_unified_validations(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": UnifiedStrategyValidationService(database).list()}

    @app.get("/api/research/unified-validations/{validation_id}")
    def get_unified_validation(validation_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return UnifiedStrategyValidationService(database).get(validation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unified validation not found") from exc

    @app.get("/api/research/unified-validations/{left_id}/diff/{right_id}")
    def diff_unified_validations(
        left_id: str, right_id: str, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return UnifiedStrategyValidationService(database).diff(left_id, right_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unified validation not found") from exc

    @app.get("/api/research/strategy-cards/funnel")
    def strategy_card_funnel(_: AdminUser) -> dict[str, Any]:
        return StrategyCardService(database).funnel()

    @app.post("/api/research/strategy-cards/reconcile")
    def reconcile_strategy_cards(username: AdminUser) -> dict[str, Any]:
        return StrategyCardService(database).reconcile_all(actor=username)

    @app.get("/api/research/strategy-cards/{card_id}/snapshots")
    def strategy_card_snapshots(card_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return {"items": StrategyCardService(database).snapshots(card_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="StrategyCard not found") from exc

    @app.post("/api/research/strategy-cards/{card_id}/decisions")
    def record_strategy_card_decision(
        card_id: str,
        payload: StrategyCardDecisionRequestV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return StrategyCardService(database).decide(card_id, payload, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="StrategyCard not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/portfolio/assessments")
    def create_portfolio_assessment(
        payload: PortfolioAssessmentRequestV2,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PortfolioAssessmentService(database).assess(payload, actor=username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/portfolio/paper-cohorts")
    def build_paper_cohort(
        payload: PaperCohortBuildV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PaperCohortService(database).build(payload, actor=username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/portfolio/paper-cohorts")
    def list_paper_cohorts(_: AdminUser) -> dict[str, Any]:
        return {"items": PaperCohortService(database).list()}

    @app.get("/api/portfolio/paper-cohorts/{cohort_id}")
    def get_paper_cohort(cohort_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return PaperCohortService(database).get(cohort_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper cohort not found") from exc

    @app.get("/api/portfolio/paper-cohorts/{left_id}/diff/{right_id}")
    def diff_paper_cohorts(left_id: str, right_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return PaperCohortService(database).diff(left_id, right_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper cohort not found") from exc

    @app.post("/api/portfolio/paper-cohorts/{cohort_id}/decisions")
    def decide_paper_cohort_label(
        cohort_id: str,
        payload: PaperCohortLabelDecisionV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PaperCohortService(database).decide(cohort_id, payload, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper cohort not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/portfolio/shadow-portfolios")
    def build_shadow_portfolio(
        payload: ShadowPortfolioBuildV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return ShadowPortfolioService(database).build(payload, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper cohort not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/portfolio/market-regimes-v2")
    def capture_market_regime_v2(
        payload: MarketRegimeCaptureV2,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return MarketRegimeSnapshotServiceV2(database).capture(
                payload, actor=username
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/portfolio/market-regimes-v2")
    def list_market_regimes_v2(_: AdminUser) -> dict[str, Any]:
        return {"items": MarketRegimeSnapshotServiceV2(database).list()}

    @app.get("/api/portfolio/market-regimes-v2/{snapshot_id}")
    def get_market_regime_v2(
        snapshot_id: str, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return MarketRegimeSnapshotServiceV2(database).get(snapshot_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Market regime snapshot not found"
            ) from exc

    @app.get(
        "/api/portfolio/market-regimes-v2/{left_id}/diff/{right_id}"
    )
    def diff_market_regimes_v2(
        left_id: str, right_id: str, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return MarketRegimeSnapshotServiceV2(database).diff(
                left_id, right_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Market regime snapshot not found"
            ) from exc

    @app.post("/api/portfolio/regime-shadow-targets-v2")
    def build_regime_shadow_target_v2(
        payload: RegimeShadowBuildV2,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return RegimeShadowAllocatorServiceV2(database).build(
                payload, actor=username
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Regime shadow source not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/portfolio/regime-shadow-targets-v2")
    def list_regime_shadow_targets_v2(_: AdminUser) -> dict[str, Any]:
        return {
            "items": RegimeShadowAllocatorServiceV2(database).list_targets()
        }

    @app.get("/api/portfolio/regime-shadow-targets-v2/{target_id}")
    def get_regime_shadow_target_v2(
        target_id: str, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return RegimeShadowAllocatorServiceV2(database).get(target_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Regime shadow target not found"
            ) from exc

    @app.get(
        "/api/portfolio/regime-shadow-targets-v2/{target_id}/replay"
    )
    def replay_regime_shadow_target_v2(
        target_id: str, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return RegimeShadowAllocatorServiceV2(database).replay(target_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Regime shadow target not found"
            ) from exc

    @app.get("/api/portfolio/shadow-portfolios")
    def list_shadow_portfolios(_: AdminUser) -> dict[str, Any]:
        return {"items": ShadowPortfolioService(database).list_proposals()}

    @app.get("/api/portfolio/shadow-portfolios/{proposal_id}")
    def get_shadow_portfolio(proposal_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ShadowPortfolioService(database).get(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Shadow proposal not found") from exc

    @app.get("/api/portfolio/shadow-portfolios/{left_id}/diff/{right_id}")
    def diff_shadow_portfolios(left_id: str, right_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ShadowPortfolioService(database).diff(left_id, right_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Shadow proposal not found") from exc

    @app.post("/api/portfolio/shadow-portfolios/{proposal_id}/reviews")
    def review_shadow_portfolio(
        proposal_id: str,
        payload: ShadowPortfolioReviewV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return ShadowPortfolioService(database).review(proposal_id, payload, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Shadow proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/portfolio/observation-windows")
    def capture_portfolio_observation_window(
        payload: PortfolioObservationCaptureV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PortfolioEvidenceService(
                database,
                adapter=get_bitpro_adapter(),
            ).capture(payload, actor=username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/portfolio/observation-windows")
    def list_portfolio_observation_windows(_: AdminUser) -> dict[str, Any]:
        return {
            "items": PortfolioEvidenceService(
                database,
                adapter=get_bitpro_adapter(),
            ).list()
        }

    @app.get("/api/portfolio/observation-windows/{window_id}")
    def get_portfolio_observation_window(window_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return PortfolioEvidenceService(
                database,
                adapter=get_bitpro_adapter(),
            ).get(window_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Observation window not found") from exc

    @app.get("/api/portfolio/observation-windows/{left_id}/diff/{right_id}")
    def diff_portfolio_observation_windows(
        left_id: str,
        right_id: str,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PortfolioEvidenceService(
                database,
                adapter=get_bitpro_adapter(),
            ).diff(left_id, right_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Observation window not found") from exc

    @app.get("/api/portfolio/assessments")
    def list_portfolio_assessments(_: AdminUser) -> dict[str, Any]:
        return {"items": PortfolioAssessmentService(database).list_assessments()}

    @app.get("/api/portfolio/assessments/{assessment_id}")
    def get_portfolio_assessment(assessment_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return PortfolioAssessmentService(database).get(assessment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assessment not found") from exc

    @app.get("/api/portfolio/assessments/{left_id}/diff/{right_id}")
    def diff_portfolio_assessments(
        left_id: str,
        right_id: str,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PortfolioAssessmentService(database).diff(left_id, right_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assessment not found") from exc

    @app.post("/api/portfolio/assessments/{assessment_id}/reviews")
    def review_portfolio_recommendation(
        assessment_id: str,
        payload: StrategyLifecycleDecisionV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return PortfolioAssessmentService(database).review(
                assessment_id,
                payload,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assessment not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/global-market/snapshot")
    def global_market_snapshot() -> dict[str, Any]:
        """Get current global market state snapshot with regime classifications."""
        service = GlobalMarketService()
        snapshot = service.get_snapshot()
        return snapshot.model_dump()

    @app.get("/api/global-market/tickers")
    def global_market_tickers() -> dict[str, Any]:
        """Get list of supported global market tickers."""
        service = GlobalMarketService()
        return {"tickers": service.get_supported_tickers()}

    @app.get("/api/world-model/defensive-actions")
    def world_model_defensive_actions(_: AdminUser) -> dict[str, Any]:
        return DefensiveActionEngine(database, settings=app_settings).status()

    @app.get("/api/world-model/defensive-action-attempts")
    def world_model_defensive_action_attempts(
        _: AdminUser,
        limit: int = 25,
    ) -> dict[str, Any]:
        return {
            "attempts": DefensiveActionEngine(database, settings=app_settings).list_attempts(
                limit=limit,
            )
        }

    @app.post("/api/world-model/defensive-actions/execute")
    def execute_world_model_defensive_action(
        payload: DefensiveActionPayload,
        _: AdminUser,
    ) -> dict[str, Any]:
        world_state = (
            payload.world_state
            or WorldModelService(
                database,
                settings=app_settings,
            ).snapshot()
        )
        return DefensiveActionEngine(database, settings=app_settings).execute(
            action_id=payload.action_id,
            idempotency_key=payload.idempotency_key,
            world_state=world_state,
        )

    @app.post("/api/agent/missions")
    async def create_agent_mission(
        payload: MissionCreate,
        request: Request,
        _: AdminUser,
    ) -> dict[str, Any]:
        header_key = request.headers.get("Idempotency-Key", "").strip()
        if header_key:
            payload = payload.model_copy(update={"idempotency_key": header_key[:128]})
        mission = await mission_runtime.create(payload)
        return mission.model_dump(mode="json")

    @app.get("/api/agent/capabilities")
    async def list_agent_capabilities(_: AdminUser) -> dict[str, Any]:
        rows = await capability_catalog.list_active()
        return {"capabilities": [row.model_dump(mode="json") for row in rows]}

    @app.get("/api/agent/capability-proposals")
    async def list_agent_capability_proposals(_: AdminUser) -> dict[str, Any]:
        rows = await capability_catalog.list_proposals()
        return {"proposals": [row.model_dump(mode="json") for row in rows]}

    @app.post("/api/agent/capability-proposals")
    async def propose_agent_capability(
        payload: CapabilityProposalV1,
        _: AdminUser,
    ) -> dict[str, Any]:
        proposal = await capability_catalog.propose(payload)
        return proposal.model_dump(mode="json")

    @app.post("/api/agent/capability-proposals/{proposal_id}/review")
    async def review_agent_capability(
        proposal_id: str,
        payload: CapabilityReviewV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            proposal = await capability_catalog.review(
                proposal_id,
                payload.model_copy(update={"actor": username}),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Capability proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return proposal.model_dump(mode="json")

    @app.get("/api/agent/capabilities/{capability_id}/circuit")
    async def get_agent_capability_circuit(
        capability_id: str,
        _: AdminUser,
    ) -> dict[str, Any]:
        return tool_executor.circuit.state(capability_id).model_dump(mode="json")

    @app.get("/api/agent/roles")
    async def list_agent_roles(_: AdminUser) -> dict[str, Any]:
        return {"roles": [role.model_dump(mode="json") for role in role_catalog.list()]}

    @app.post("/api/agent/missions/{mission_id}/team/run")
    async def run_agent_team(
        mission_id: str,
        payload: TeamRunRequestV1,
        _: AdminUser,
    ) -> dict[str, Any]:
        if not app_settings.dynamic_team_enabled:
            raise HTTPException(status_code=503, detail="Dynamic team runtime is disabled")
        try:
            mission = await mission_store.get(mission_id)
            packs = await context_artifact_store.list_packs(mission_id)
            allowed_context_refs = {
                f"context:{pack.context_pack_id}@{pack.manifest_hash}" for pack in packs
            }
            requested_context_refs = {
                ref for item in payload.assignments for ref in item.context_pack_refs
            }
            if not requested_context_refs <= allowed_context_refs:
                raise ValueError("assignment references an unknown Mission Context Pack")
            merge = await supervisor.run(mission, payload, deterministic_worker())
            await mission_store.append_event(
                mission_id,
                "team.completed",
                actor="supervisor",
                payload={
                    "handoff_count": len(merge.handoff_refs),
                    "conflict_count": len(merge.conflicts),
                    "unknown_count": len(merge.unknowns),
                },
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return merge.model_dump(mode="json")

    @app.get("/api/agent/missions/{mission_id}/supervision")
    async def get_agent_supervision(mission_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            await mission_store.get(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        assignments = await supervision_store.assignments(mission_id)
        handoffs = await supervision_store.handoffs(mission_id)
        conflicts = await supervision_store.conflicts(mission_id)
        return {
            "assignments": [row.model_dump(mode="json") for row in assignments],
            "handoffs": [row.model_dump(mode="json") for row in handoffs],
            "conflicts": [row.model_dump(mode="json") for row in conflicts],
        }

    @app.post("/api/agent/missions/{mission_id}/sandbox-runs")
    async def run_agent_strategy_sandbox(
        mission_id: str,
        payload: SandboxRequestV1,
        _: AdminUser,
    ) -> dict[str, Any]:
        if not app_settings.strategy_sandbox_enabled:
            raise HTTPException(status_code=503, detail="Strategy sandbox is disabled")
        try:
            await mission_store.get(mission_id)
            assignments = await supervision_store.assignments(mission_id)
            allowed_assignments = {
                f"assignment:{row.assignment_id}"
                for row in assignments
                if row.status == "succeeded"
            }
            if payload.assignment_ref not in allowed_assignments:
                raise ValueError("sandbox requires a succeeded Mission assignment")
            packs = await context_artifact_store.list_packs(mission_id)
            allowed_context_refs = {
                f"context:{pack.context_pack_id}@{pack.manifest_hash}" for pack in packs
            }
            if not set(payload.context_pack_refs) <= allowed_context_refs:
                raise ValueError("sandbox references an unknown Mission Context Pack")
            artifacts = await context_artifact_store.list_artifacts(mission_id)
            allowed_artifact_refs = {row.stable_ref for row in artifacts if row.status == "current"}
            if not set(payload.source_artifact_refs) <= allowed_artifact_refs:
                raise ValueError("sandbox references an unknown Mission Artifact")
            run = await strategy_sandbox.run(mission_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return run.model_dump(mode="json")

    @app.get("/api/agent/missions/{mission_id}/sandbox-runs")
    async def list_agent_strategy_sandbox_runs(mission_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            await mission_store.get(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        runs = await sandbox_store.runs(mission_id)
        reviews = await sandbox_store.reviews(mission_id)
        return {
            "runs": [row.model_dump(mode="json") for row in runs],
            "reviews": [row.model_dump(mode="json") for row in reviews],
        }

    @app.post("/api/agent/missions/{mission_id}/sandbox-runs/{run_id}/review")
    async def review_agent_strategy_sandbox_run(
        mission_id: str,
        run_id: str,
        payload: ImportReviewV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        if not app_settings.strategy_sandbox_enabled:
            raise HTTPException(status_code=503, detail="Strategy sandbox is disabled")
        try:
            run = await sandbox_store.get(mission_id, run_id)
            review = await sandbox_store.review(run, payload, username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Sandbox run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return review.model_dump(mode="json")

    @app.get("/api/agent/missions/{mission_id}/context-packs")
    async def list_agent_context_packs(mission_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            await mission_store.get(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        rows = await context_artifact_store.list_packs(mission_id)
        return {"context_packs": [row.model_dump(mode="json") for row in rows]}

    @app.get("/api/agent/missions/{mission_id}/artifacts")
    async def list_agent_mission_artifacts(mission_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            await mission_store.get(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        rows = await context_artifact_store.list_artifacts(mission_id)
        relations = await context_artifact_store.relations(mission_id)
        return {
            "artifacts": [row.model_dump(mode="json") for row in rows],
            "relations": [row.model_dump(mode="json") for row in relations],
        }

    @app.post("/api/agent/missions/{mission_id}/artifacts")
    async def register_agent_mission_artifact(
        mission_id: str,
        payload: MissionArtifactCreateV1,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            await mission_store.get(mission_id)
            artifact = await context_artifact_store.register_artifact(mission_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission or artifact not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return artifact.model_dump(mode="json")

    @app.get("/api/agent/missions/{mission_id}/artifacts/{artifact_id}")
    async def get_agent_mission_artifact(
        mission_id: str,
        artifact_id: str,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            artifact = await context_artifact_store.artifact(mission_id, artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        return artifact.model_dump(mode="json")

    @app.get("/api/agent/missions")
    async def list_agent_missions(_: AdminUser, limit: int = 50) -> dict[str, Any]:
        rows = await mission_store.list(limit=limit)
        return {"missions": [row.model_dump(mode="json") for row in rows]}

    @app.get("/api/agent/missions/{mission_id}")
    async def get_agent_mission(mission_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            mission = await mission_store.get(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        plans = await mission_store.plans(mission_id)
        attempts = await mission_store.attempts(mission_id)
        return {
            **mission.model_dump(mode="json"),
            "plans": [plan.model_dump(mode="json") for plan in plans],
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
        }

    @app.post("/api/agent/missions/{mission_id}/run")
    async def run_agent_mission(mission_id: str, _: AdminUser) -> dict[str, Any]:
        if not app_settings.mission_runtime_enabled:
            raise HTTPException(
                status_code=409,
                detail="Mission Runtime is disabled by feature flag",
            )
        try:
            mission = await mission_store.get(mission_id)
            if not app_settings.mission_runtime_worker_enabled:
                mission = await mission_runtime.run(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return mission.model_dump(mode="json")

    @app.post("/api/agent/missions/{mission_id}/control")
    async def control_agent_mission(
        mission_id: str,
        payload: MissionControlPayload,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            if payload.action == "pause":
                mission = await mission_runtime.pause(mission_id, actor=username)
            elif payload.action == "resume":
                mission = await mission_runtime.resume(mission_id, actor=username)
            else:
                mission = await mission_runtime.cancel(mission_id, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {**mission.model_dump(mode="json"), "reason": payload.reason}

    @app.post("/api/agent/missions/{mission_id}/steer")
    async def steer_agent_mission(
        mission_id: str,
        payload: SteeringEventV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        steer = payload.model_copy(update={"actor": username})
        try:
            mission = await mission_runtime.steer(mission_id, steer)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return mission.model_dump(mode="json")

    @app.get("/api/agent/missions/{mission_id}/events")
    async def list_agent_mission_events(
        mission_id: str,
        _: AdminUser,
        after: int = 0,
        limit: int = 500,
    ) -> dict[str, Any]:
        try:
            events = await mission_store.events(mission_id, after=after, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Mission not found") from exc
        return {
            "events": [event.model_dump(mode="json") for event in events],
            "next_cursor": events[-1].sequence if events else after,
        }

    @app.get("/api/agent/missions/{mission_id}/events/stream")
    async def stream_agent_mission_events(
        mission_id: str,
        request: Request,
        _: AdminUser,
        after: int = 0,
    ) -> StreamingResponse:
        raw_last_event = request.headers.get("Last-Event-ID", "").strip()
        if raw_last_event:
            try:
                after = max(after, int(raw_last_event))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Last-Event-ID") from exc

        async def replay() -> AsyncIterator[str]:
            cursor = after
            while True:
                try:
                    events = await mission_store.events(mission_id, after=cursor, limit=1_000)
                    mission = await mission_store.get(mission_id)
                except KeyError:
                    yield 'event: error\ndata: {"error":"mission_not_found"}\n\n'
                    return
                for event in events:
                    cursor = event.sequence
                    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"
                if mission.status in TERMINAL_STATUSES:
                    return
                if await request.is_disconnected():
                    return
                if not events:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(replay(), media_type="text/event-stream")

    @app.post("/api/agent/runs")
    async def create_run(payload: AgentRunPayload, request: Request) -> dict[str, Any]:
        idempotency_key = mission_request_key(request)
        fixture_case_id = evaluation_case_id(payload)
        if is_mission_canary(
            enabled=app_settings.mission_runtime_enabled,
            percent=app_settings.mission_runtime_canary_percent,
            idempotency_key=idempotency_key,
        ):
            try:
                return await run_prompt_as_mission(
                    payload.prompt,
                    actor="mission_api",
                    idempotency_key=idempotency_key,
                    evaluation_case_id=fixture_case_id,
                    prior_turns=tuple(payload.prior_turns),
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        kernel = AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
            provider_name=str(app.state.active_chat_provider),
            provider_model=str(app.state.active_chat_model or "") or None,
            evaluation_mode=payload.evaluation_mode,
        )
        task = _prepare_agent_task(
            database,
            prompt=payload.prompt,
            surface="api",
            provider_name=str(app.state.active_chat_provider),
            provider_model=str(app.state.active_chat_model or ""),
            idempotency_key=request.headers.get("Idempotency-Key") or new_id("agentreq"),
        )
        try:
            # The kernel is synchronous end to end (LLM SDK + tool IO). Offload
            # the whole run to a worker thread so one long research request
            # cannot stall the event loop serving SSE streams and health probes.
            run = await asyncio.to_thread(
                AgentTaskExecutor(database).execute_chat,
                task.id,
                kernel,
                payload.prompt,
            )
        except TaskExecutionError as exc:
            raise HTTPException(
                status_code=503 if exc.error.get("retryable") else 500,
                detail={"task_id": exc.task_id, "error": exc.error},
            ) from exc
        except TaskControlInterrupted as exc:
            raise HTTPException(
                status_code=409,
                detail={"task_id": exc.task_id, "status": exc.status},
            ) from exc
        return _run_to_dict(run)

    @app.post("/api/agent/runs/stream")
    async def stream_run(payload: AgentRunPayload, request: Request) -> StreamingResponse:
        idempotency_key = mission_request_key(request)
        fixture_case_id = evaluation_case_id(payload)
        if is_mission_canary(
            enabled=app_settings.mission_runtime_enabled,
            percent=app_settings.mission_runtime_canary_percent,
            idempotency_key=idempotency_key,
        ):

            async def mission_stream() -> AsyncIterator[str]:
                # Public stream events expose only the operator answer contract.
                # Plan/tool telemetry stays in the Mission audit stream instead.
                mission_id = ""
                yield _format_sse(
                    {
                        "event": "answer_delta",
                        "text": "已受理只读研究请求，正在验证证据。",
                    }
                )
                try:
                    mission = await create_prompt_mission(
                        payload.prompt,
                        actor="mission_stream",
                        idempotency_key=idempotency_key,
                        evaluation_case_id=fixture_case_id,
                        prior_turns=tuple(payload.prior_turns),
                    )
                    mission_id = mission.mission_id
                    yield _format_sse(
                        {
                            "event": "answer_delta",
                            "mission_id": mission.mission_id,
                            "text": "研究任务已登记，等待受治理执行。",
                        }
                    )
                    execution_failed = False
                    try:
                        completed = (
                            await await_worker_mission(mission.mission_id)
                            if app_settings.mission_runtime_worker_enabled
                            else await mission_runtime.run(mission.mission_id)
                        )
                    except Exception:  # noqa: BLE001 - streaming must end in a safe final event
                        logger.exception(
                            "streamed mission failed mission_id=%s",
                            mission.mission_id,
                        )
                        execution_failed = True
                        completed = await fail_mission_execution(mission.mission_id)
                    result = await mission_run_projection(completed, mission_store)
                    report = result.get("report_json", {})
                    operator_response = (
                        report.get("operator_response", {}) if isinstance(report, dict) else {}
                    )
                    if execution_failed:
                        yield _format_sse(
                            {
                                "event": "warning",
                                "mission_id": result["mission_id"],
                                "code": "mission_execution_failure",
                                "text": "研究执行未完成；当前仅返回安全失败结论。",
                            }
                        )
                    if isinstance(operator_response, dict):
                        evidence = operator_response.get("evidence", [])
                        if isinstance(evidence, list):
                            yield _format_sse(
                                {
                                    "event": "evidence_ready",
                                    "mission_id": result["mission_id"],
                                    "count": len(evidence),
                                }
                            )
                        decision = operator_response.get("decision")
                        if isinstance(decision, str) and decision:
                            yield _format_sse(
                                {
                                    "event": "answer_delta",
                                    "mission_id": result["mission_id"],
                                    "text": decision,
                                }
                            )
                    else:
                        yield _format_sse(
                            {
                                "event": "warning",
                                "mission_id": result["mission_id"],
                                "text": "研究已结束，但公开回答投影不可用。",
                            }
                        )
                    yield _format_sse(
                        {
                            "event": "final",
                            "mission_id": result["mission_id"],
                            "run": result,
                        }
                    )
                except Exception:  # noqa: BLE001 - preserve an operator-safe stream boundary
                    logger.exception("streamed mission terminal projection failed")
                    yield _format_sse(
                        {
                            "event": "warning",
                            "text": "研究运行未产生可验证结果。",
                            "code": "mission_runtime_error",
                        }
                    )
                    # A public stream is not complete until it has a terminal
                    # event. Do not leak the exception, but give every client a
                    # renderable failed projection instead of an ambiguous EOF.
                    yield _format_sse(
                        {
                            "event": "final",
                            "mission_id": mission_id,
                            "run": _stream_failure_projection(run_id=mission_id),
                        }
                    )

            return StreamingResponse(mission_stream(), media_type="text/event-stream")
        task = _prepare_agent_task(
            database,
            prompt=payload.prompt,
            surface="api",
            provider_name=str(app.state.active_chat_provider),
            provider_model=str(app.state.active_chat_model or ""),
            idempotency_key=request.headers.get("Idempotency-Key") or new_id("agentreq"),
        )
        return StreamingResponse(
            _agent_run_sse(
                database,
                app_settings,
                payload.prompt,
                task_id=task.id,
                provider_name=str(app.state.active_chat_provider),
                provider_model=str(app.state.active_chat_model or "") or None,
                evaluation_mode=payload.evaluation_mode,
            ),
            media_type="text/event-stream",
        )

    @app.post("/api/agent/sessions")
    def create_agent_session(payload: AgentSessionCreate, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        return session_to_dict(AgentSessionService(database).create(payload))

    @app.get("/api/agent/sessions")
    def list_agent_sessions(limit: int = 50) -> dict[str, Any]:
        return {
            "sessions": [
                session_to_dict(row) for row in AgentSessionService(database).list(limit=limit)
            ]
        }

    @app.get("/api/agent/sessions/{session_id}")
    def get_agent_session(session_id: str) -> dict[str, Any]:
        try:
            row = AgentSessionService(database).get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return session_to_dict(row)

    @app.post("/api/agent/sessions/{session_id}/tasks")
    def create_agent_task(
        session_id: str,
        payload: AgentTaskCreate,
        _: AdminUser,
    ) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        try:
            row = AgentTaskService(database).create(
                payload.model_copy(update={"session_id": session_id}),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session or parent task not found") from exc
        return task_to_dict(row)

    @app.get("/api/agent/tasks")
    def list_agent_tasks(
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        rows = AgentTaskService(database).list_tasks(
            session_id=session_id,
            status=status,
            limit=limit,
        )
        return {"tasks": [task_to_dict(row) for row in rows]}

    @app.get("/api/agent/tasks/{task_id}")
    def get_agent_task(task_id: str) -> dict[str, Any]:
        try:
            row = AgentTaskService(database).get(task_id)
            checkpoint = TaskCheckpointService(database).latest(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        payload = task_to_dict(row)
        payload["latest_checkpoint"] = checkpoint_to_dict(checkpoint) if checkpoint else None
        return payload

    @app.post("/api/agent/tasks/{task_id}/pause")
    def pause_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        return _task_control_or_http_error(database, task_id, "pause", payload)

    @app.post("/api/agent/tasks/{task_id}/resume")
    def resume_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        return _task_control_or_http_error(database, task_id, "resume", payload)

    @app.post("/api/agent/tasks/{task_id}/cancel")
    def cancel_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        return _task_control_or_http_error(database, task_id, "cancel", payload)

    @app.post("/api/agent/tasks/{task_id}/retry")
    def retry_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        return _task_control_or_http_error(database, task_id, "retry", payload)

    @app.post("/api/agent/tasks/{task_id}/branch")
    def branch_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        return _task_control_or_http_error(database, task_id, "branch", payload)

    @app.get("/api/agent/tasks/{task_id}/events")
    def get_agent_task_events(task_id: str, after: int = 0, limit: int = 500) -> dict[str, Any]:
        try:
            rows = TaskEventService(database).list(task_id, after=after, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return {
            "task_id": task_id,
            "after": max(after, 0),
            "events": [task_event_to_dict(row) for row in rows],
        }

    @app.get("/api/agent/tasks/{task_id}/stream")
    def stream_agent_task_events(
        task_id: str, request: Request, after: int = 0
    ) -> StreamingResponse:
        raw_last_event = request.headers.get("Last-Event-ID", "").strip()
        if raw_last_event:
            try:
                after = max(after, int(raw_last_event))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Last-Event-ID") from exc
        try:
            AgentTaskService(database).get(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return StreamingResponse(
            _task_event_sse(database, task_id, after=after),
            media_type="text/event-stream",
        )

    @app.get("/api/agent/runs")
    async def list_runs() -> dict[str, list[dict[str, Any]]]:
        with database.session() as session:
            runs = session.scalars(
                select(AgentRun).order_by(desc(AgentRun.created_at)).limit(25)
            ).all()
            legacy = [
                {
                    "id": run.id,
                    "prompt": run.prompt,
                    "status": run.status,
                    "created_at": run.created_at.isoformat(),
                    "runtime": "legacy",
                }
                for run in runs
            ]
        missions = await mission_store.list(limit=25)
        mission_rows = [
            {
                "id": row.mission_id,
                "prompt": row.objective,
                "status": row.status.value,
                "created_at": row.created_at.isoformat(),
                "runtime": "mission_v2",
            }
            for row in missions
        ]
        rows = sorted(
            [*mission_rows, *legacy],
            key=lambda row: row["created_at"],
            reverse=True,
        )
        return {"runs": rows[:25]}

    @app.get("/api/agent/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        if run_id.startswith("mis_"):
            try:
                mission = await mission_store.get(run_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Mission not found") from exc
            return await mission_run_projection(mission, mission_store)
        try:
            kernel = AgentKernel(
                database,
                knowledge_dir=str(app_settings.knowledge_dir),
                settings=app_settings,
                provider_name=str(app.state.active_chat_provider),
            )
            run = kernel.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return _run_to_dict(run)

    @app.get("/api/agent/runs/{run_id}/observability")
    def get_run_observability(run_id: str) -> dict[str, Any]:
        try:
            return AgentObservabilityService(database).get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.post("/api/agent/runs/{run_id}/cancel")
    def cancel_run(run_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            kernel = AgentKernel(
                database,
                knowledge_dir=str(app_settings.knowledge_dir),
                settings=app_settings,
                provider_name=str(app.state.active_chat_provider),
            )
            run = kernel.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return _run_to_dict(run)

    @app.get("/api/market/tickers/latest")
    def latest_tickers(limit: int = 50) -> dict[str, list[dict[str, str]]]:
        rows = MarketRepository(database).latest_tickers(limit=limit)
        return {
            "tickers": [
                {
                    "inst_id": row.inst_id,
                    "last": str(row.last),
                    "volume_ccy_24h": str(row.volume_ccy_24h),
                    "change_utc0_pct": str(row.change_utc0_pct),
                }
                for row in rows
            ]
        }

    @app.get("/api/market/ticker/{symbol}")
    def market_ticker(symbol: str) -> dict[str, Any]:
        return AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        )._market_ticker_payload(symbol)

    @app.get("/api/market/candles/{symbol}")
    def market_candles(
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        )._market_candles_payload(symbol=symbol, bar=bar, limit=limit)

    @app.post("/api/market/compare")
    def market_compare(payload: MarketComparePayload) -> dict[str, Any]:
        return AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        )._market_compare_payload(
            symbols=payload.symbols,
            bar=payload.bar,
            limit=payload.limit,
        )

    @app.get("/api/bitpro/health")
    def bitpro_health(_: AdminUser) -> dict[str, Any]:
        adapter = get_bitpro_adapter()
        return _bitpro_read_or_502(adapter, adapter.health)

    @app.get("/api/bitpro/market/klines/{symbol}")
    def bitpro_market_klines(
        symbol: str,
        _: AdminUser,
        timeframe: str = "1h",
        limit: int = 200,
    ) -> dict[str, Any]:
        adapter = get_bitpro_adapter()
        return _bitpro_read_or_502(
            adapter,
            lambda: adapter.market_klines(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
            ),
        )

    @app.get("/api/bitpro/paper/dashboard")
    def bitpro_paper_dashboard(_: AdminUser) -> dict[str, Any]:
        adapter = get_bitpro_adapter()
        return _bitpro_read_or_502(adapter, adapter.paper_dashboard)

    @app.get("/api/bitpro/paper/snapshot")
    def bitpro_paper_snapshot(
        _: AdminUser, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        adapter = get_bitpro_adapter()
        return _bitpro_read_or_502(
            adapter,
            lambda: adapter.paper_snapshot(strategy_id=strategy_id, instance_id=instance_id),
        )

    @app.get("/api/monitors")
    def list_monitors() -> dict[str, list[dict[str, Any]]]:
        return {
            "items": MonitorService(
                database,
                bitpro_adapter=get_bitpro_adapter(),
            ).list_monitors()
        }

    @app.post("/api/monitors/{monitor_id}/run")
    def run_monitor(monitor_id: str) -> dict[str, Any]:
        try:
            return MonitorService(
                database,
                bitpro_adapter=get_bitpro_adapter(),
            ).run_monitor(monitor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Monitor not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/alerts")
    def list_alerts(limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": MonitorService(
                database,
                bitpro_adapter=get_bitpro_adapter(),
            ).list_alerts(limit=limit)
        }

    @app.get("/api/bitpro/live/positions")
    def bitpro_live_positions(
        _: AdminUser,
        exchange: str = "okx",
        symbol: str | None = None,
    ) -> dict[str, Any]:
        adapter = get_bitpro_adapter()
        return _bitpro_read_or_502(
            adapter,
            lambda: adapter.live_positions(exchange=exchange, symbol=symbol),
        )

    @app.get("/api/paper/status")
    def paper_status() -> dict[str, Any]:
        return PaperTradingService(database, settings=app_settings).status()

    @app.post("/api/paper/control")
    def paper_control(payload: PaperControlPayload, _: AdminUser) -> dict[str, Any]:
        service = PaperTradingService(database, settings=app_settings)
        if payload.action == "pause":
            return service.pause()
        if payload.action == "resume":
            return service.resume()
        if payload.action == "close":
            return service.close(symbol=payload.symbol)
        return service.reset()

    @app.post("/api/strategy/research")
    def create_strategy_research(
        payload: StrategyResearchPayload,
    ) -> dict[str, Any]:
        return StrategyResearchService(database).create(payload.prompt)

    @app.get("/api/strategy/research")
    def list_strategy_research() -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyResearchService(database).list_recent()}

    @app.post("/api/research/mandates")
    def create_research_mandate(payload: ResearchMandateCreate, _: AdminUser) -> dict[str, Any]:
        return ResearchProgramService(database).create_mandate(payload)

    @app.post("/api/research/evidence")
    def append_research_evidence(
        payload: ResearchEvidenceInput, username: AdminUser
    ) -> dict[str, Any]:
        """Append through the trusted schema boundary; Agent tools get no direct mutation tool."""
        try:
            return EvidenceService(database).append(payload, actor=f"admin:{username}")
        except EvidenceSourceUnavailable as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "evidence_source_unavailable", "sources": exc.sources},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/evidence")
    def list_research_evidence(
        task_id: str = "",
        type: str = "",
        status: str = "",
        symbol: str = "",
        limit: int = 100,
        include_legacy: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        items = EvidenceService(database).query(
            task_id=task_id,
            evidence_type=type,
            status=status,
            symbol=symbol,
            limit=limit,
        )
        if include_legacy and not task_id and not type and not status and not symbol:
            items.extend(LegacyEvidenceAdapter(database).query(limit=limit))
            items = sorted(items, key=lambda item: item["created_at"], reverse=True)[:limit]
        return {"items": items}

    @app.get("/api/research/evidence/{evidence_id}/graph")
    def research_evidence_graph(evidence_id: str, depth: int = 2) -> dict[str, Any]:
        try:
            return EvidenceService(database).graph(evidence_id, depth=depth)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research evidence not found") from exc

    @app.get("/api/research/evidence/{evidence_id}")
    def get_research_evidence(evidence_id: str) -> dict[str, Any]:
        try:
            return EvidenceService(database).get(evidence_id)
        except KeyError:
            try:
                return LegacyEvidenceAdapter(database).get(evidence_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Research evidence not found") from exc

    @app.post("/api/research/evidence/{evidence_id}/supersede")
    def supersede_research_evidence(
        evidence_id: str, payload: EvidenceSupersedeRequest, username: AdminUser
    ) -> dict[str, Any]:
        try:
            return EvidenceService(database).supersede(
                evidence_id,
                payload.evidence,
                reason=payload.reason,
                actor=f"admin:{username}",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research evidence not found") from exc
        except (ValueError, EvidenceSourceUnavailable) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/evidence/{evidence_id}/expire")
    def expire_research_evidence(
        evidence_id: str, payload: EvidenceLifecycleRequest, username: AdminUser
    ) -> dict[str, Any]:
        try:
            return EvidenceService(database).expire(
                evidence_id, reason=payload.reason, actor=f"admin:{username}"
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research evidence not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/evidence/{evidence_id}/reject")
    def reject_research_evidence(
        evidence_id: str, payload: EvidenceLifecycleRequest, username: AdminUser
    ) -> dict[str, Any]:
        try:
            return EvidenceService(database).reject(
                evidence_id, reason=payload.reason, actor=f"admin:{username}"
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research evidence not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/graphs/topology")
    def research_graph_topology() -> dict[str, Any]:
        return graph_topology_projection()

    @app.post("/api/research/graphs")
    def create_research_graph(payload: ResearchGraphCreate, username: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        try:
            return ResearchGraphTaskService(database).create(
                payload, created_by=f"admin:{username}"
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/graphs")
    def list_research_graphs(limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        tasks = AgentTaskService(database).list_tasks(kind="research_graph", limit=limit)
        return {"items": [task_to_dict(task) for task in tasks]}

    @app.get("/api/research/graphs/{task_id}")
    def get_research_graph(task_id: str) -> dict[str, Any]:
        try:
            return research_graph_runtime().projection(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research graph not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/graphs/{task_id}/run")
    def run_research_graph(task_id: str, _: AdminUser) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        try:
            return research_graph_runtime().run(task_id)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "research_role_timeout", "retryable": True},
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research graph not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (PermissionError, RuntimeError) as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "research_graph_failed",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            ) from exc

    @app.post("/api/research/experiments")
    def register_research_experiment(
        payload: ExperimentRegister, username: AdminUser
    ) -> dict[str, Any]:
        try:
            return ExperimentLedgerService(database).register(payload, actor=f"admin:{username}")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/experiments")
    def list_research_experiments(limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        return {"items": ExperimentLedgerService(database).list(limit=limit)}

    @app.get("/api/research/experiments/{fingerprint}")
    def get_research_experiment(fingerprint: str) -> dict[str, Any]:
        try:
            return ExperimentLedgerService(database).get(fingerprint)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experiment not found") from exc

    @app.get("/api/research/experiments/{fingerprint}/executions")
    def list_research_experiment_executions(fingerprint: str) -> dict[str, Any]:
        try:
            return {"items": ExperimentLedgerService(database).executions(fingerprint)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experiment not found") from exc

    @app.get("/api/research/experiments/{fingerprint}/diff/{other_fingerprint}")
    def diff_research_experiments(fingerprint: str, other_fingerprint: str) -> dict[str, Any]:
        try:
            return ExperimentLedgerService(database).diff(fingerprint, other_fingerprint)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experiment not found") from exc

    @app.get("/api/research/validations")
    def list_robustness_validations(limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        return {"items": RobustnessValidationService(database).list(limit=limit)}

    @app.get("/api/research/validations/{validation_id}")
    def get_robustness_validation(validation_id: str) -> dict[str, Any]:
        try:
            return RobustnessValidationService(database).get(validation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Validation run not found") from exc

    @app.post("/api/research/triggers")
    def create_research_trigger(
        payload: ResearchTriggerCreate,
        username: AdminUser,
    ) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        try:
            return ResearchTriggerService(database, settings=app_settings).create(
                payload,
                actor=username,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/triggers")
    def list_research_triggers(_: AdminUser) -> dict[str, Any]:
        service = ResearchTriggerService(database, settings=app_settings)
        return {
            "items": service.list_triggers(),
            "control": service.control(),
            "feature_enabled": app_settings.research_triggers_enabled,
        }

    @app.get("/api/research/triggers/fires")
    def list_research_trigger_fires(
        _: AdminUser,
        trigger_id: str = "",
    ) -> dict[str, Any]:
        return {
            "items": ResearchTriggerService(
                database,
                settings=app_settings,
            ).list_fires(trigger_id=trigger_id)
        }

    @app.put("/api/research/triggers/control")
    def update_research_trigger_control(
        payload: TriggerControlUpdate,
        username: AdminUser,
    ) -> dict[str, Any]:
        return ResearchTriggerService(database, settings=app_settings).set_control(
            payload,
            actor=username,
        )

    @app.get("/api/research/triggers/{trigger_id}")
    def get_research_trigger(trigger_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ResearchTriggerService(database, settings=app_settings).get(trigger_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trigger not found") from exc

    @app.put("/api/research/triggers/{trigger_id}/enabled")
    def set_research_trigger_enabled(
        trigger_id: str,
        payload: TriggerEnabledPayload,
        username: AdminUser,
    ) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        try:
            return ResearchTriggerService(database, settings=app_settings).set_enabled(
                trigger_id,
                enabled=payload.enabled,
                reason=payload.reason,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trigger not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/research/triggers/{trigger_id}/fire")
    def fire_research_trigger(
        trigger_id: str,
        payload: TriggerEvent,
        username: AdminUser,
    ) -> dict[str, Any]:
        require_legacy_agent_write_enabled()
        try:
            return ResearchTriggerService(database, settings=app_settings).fire(
                trigger_id,
                payload,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trigger not found") from exc

    @app.get("/api/research/mandates")
    def list_research_mandates(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": ResearchProgramService(database).list_mandates()}

    @app.get("/api/research/mandates/{mandate_id}")
    def get_research_mandate(mandate_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).get_mandate(mandate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/mandates/{mandate_id}/pause")
    def pause_research_mandate(mandate_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).pause_mandate(mandate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/mandates/{mandate_id}/resume")
    def resume_research_mandate(mandate_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).resume_mandate(mandate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/mandates/{mandate_id}/strategy-specs/draft")
    def draft_research_strategy_spec(
        mandate_id: str, payload: StrategyResearchPayload, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).draft_strategy_spec(mandate_id, payload.prompt)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/mandates/{mandate_id}/jobs")
    def queue_research_job(
        mandate_id: str, payload: ResearchJobCreate, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).queue_job(mandate_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/jobs")
    def list_research_jobs(
        _: AdminUser, mandate_id: str = "", status: str = ""
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": ResearchProgramService(database).list_jobs(
                mandate_id=mandate_id, status=status
            )
        }

    @app.get("/api/research/jobs/{job_id}")
    def get_research_job(job_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/research/jobs/{job_id}/report")
    def research_job_report(job_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).report(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/jobs/{job_id}/run")
    def run_research_job(job_id: str, _: AdminUser) -> dict[str, Any]:
        """Run the bounded BitPro research worker; it cannot configure paper or live."""
        try:
            return ResearchOrchestrator(
                database,
                bitpro_adapter=cast(BitProResearchAdapter, get_bitpro_adapter()),
            ).run(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/paper-promotions")
    def request_paper_promotion(
        payload: PaperPromotionRequestPayload, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return PaperPromotionService(database).request(
                evidence_id=payload.evidence_id, reason=payload.reason
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/paper-incubation/mandates")
    def create_paper_research_mandate(
        payload: PaperMandateCreateV1, actor: AdminUser
    ) -> dict[str, Any]:
        try:
            return paper_incubation_service().create_mandate(payload, actor=actor)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/paper-incubation/mandates")
    def list_paper_research_mandates(
        _: AdminUser, limit: int = 100
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": paper_incubation_service().list(limit=limit)}

    @app.get("/api/research/paper-incubation/mandates/{mandate_id}")
    def get_paper_research_mandate(mandate_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return paper_incubation_service().get(mandate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/paper-incubation/mandates/{mandate_id}/state")
    def set_paper_research_mandate_state(
        mandate_id: str, payload: PaperMandateStatePayload, actor: AdminUser
    ) -> dict[str, Any]:
        try:
            return paper_incubation_service().set_mandate_state(
                mandate_id,
                status=payload.status,
                actor=actor,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/paper-incubation/members/{member_id}")
    def get_paper_incubation_member(member_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return paper_incubation_service().get_member(member_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/paper-incubation/windows/capture")
    def capture_paper_incubation_windows(
        payload: PaperIncubationCaptureV1, actor: AdminUser
    ) -> dict[str, Any]:
        try:
            return paper_incubation_service(external_access=True).capture_windows(
                payload, actor=actor
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/paper-incubation/actions")
    async def run_paper_incubation_action(
        payload: PaperIncubationActionV1, actor: AdminUser
    ) -> dict[str, Any]:
        try:
            return await paper_incubation_service(external_access=True).act(payload, actor=actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/paper-incubation/actions/{action_id}/reconcile")
    async def reconcile_paper_incubation_action(action_id: str, actor: AdminUser) -> dict[str, Any]:
        try:
            return await paper_incubation_service(external_access=True).reconcile(
                action_id, actor=actor
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/research/paper-promotions")
    def list_paper_promotions(_: AdminUser, status: str = "") -> dict[str, list[dict[str, Any]]]:
        return {"items": PaperPromotionService(database).list(status=status)}

    @app.get("/api/research/paper-promotions/{promotion_id}")
    def get_paper_promotion(promotion_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return PaperPromotionService(database).get(promotion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/research/paper-promotions/{promotion_id}/approve")
    def approve_paper_promotion(
        promotion_id: str, payload: PaperPromotionApprovalPayload, approved_by: AdminUser
    ) -> dict[str, Any]:
        try:
            return PaperPromotionService(
                database, bitpro_adapter=cast(PaperPromotionAdapter, get_bitpro_adapter())
            ).approve(
                promotion_id=promotion_id,
                reason=payload.reason,
                idempotency_key=payload.idempotency_key,
                approved_by=approved_by,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/paper-promotions/{promotion_id}/observe")
    def observe_paper_promotion(promotion_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return PaperPromotionService(
                database, bitpro_adapter=cast(PaperPromotionAdapter, get_bitpro_adapter())
            ).observe(promotion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/research/paper-observations/sample")
    def sample_paper_observations(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        service = PaperObservationService(
            database, bitpro_adapter=cast(PaperPromotionAdapter, get_bitpro_adapter())
        )
        return {"items": service.sample_all()}

    @app.get("/api/research/paper-review-requests")
    def list_paper_review_requests(
        _: AdminUser, status: str = "open"
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": PaperObservationService(
                database, bitpro_adapter=cast(PaperPromotionAdapter, get_bitpro_adapter())
            ).list_requests(status=status)
        }

    @app.post("/api/research/jobs/{job_id}/cancel")
    def cancel_research_job(
        job_id: str, payload: ResearchJobCancelPayload, _: AdminUser
    ) -> dict[str, Any]:
        try:
            return ResearchProgramService(database).cancel_job(job_id, reason=payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/strategy/experiments")
    def create_strategy_experiment(
        payload: StrategyResearchPayload,
    ) -> dict[str, Any]:
        return StrategyExperimentService(database).create(payload.prompt)

    @app.post("/api/strategy/experiments/iterate")
    def create_strategy_iteration(
        payload: StrategyResearchPayload,
    ) -> dict[str, Any]:
        return StrategyExperimentService(database).create_iteration(payload.prompt)

    @app.get("/api/strategy/experiments")
    def list_strategy_experiments() -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyExperimentService(database).list_recent()}

    @app.get("/api/strategy/library")
    def strategy_library(
        query: str = "",
        strategy_key: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        return StrategyLibraryService(database).search(
            query=query,
            strategy_key=strategy_key,
            limit=limit,
        )

    @app.post("/api/backtests")
    def create_backtest(payload: BacktestPayload) -> dict[str, Any]:
        try:
            return BacktestService(database).run(
                research_id=payload.research_id,
                strategy_key=payload.strategy_key,
                candles=payload.candles,
                initial_cash=Decimal(payload.initial_cash),
                use_live_candles=payload.use_live_candles,
                symbol=payload.symbol,
                bar=payload.bar,
                candle_limit=payload.candle_limit,
                candle_source=payload.candle_source,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Research not found") from exc

    @app.get("/api/backtests")
    def list_backtests() -> dict[str, list[dict[str, Any]]]:
        return {"items": BacktestService(database).list_recent()}

    @app.post("/api/live/order-intents")
    def create_live_order_intent(
        payload: LiveOrderIntentPayload,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            return LiveOrderIntentService(database, settings=app_settings).create(
                symbol=payload.symbol,
                side=payload.side,
                size=payload.size,
                order_type=payload.order_type,
                price=payload.price,
                reason=payload.reason,
                source="api",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/live/order-intents")
    def list_live_order_intents() -> dict[str, list[dict[str, Any]]]:
        return {"items": LiveOrderIntentService(database, settings=app_settings).list_recent()}

    @app.post("/api/live/order-intents/{intent_id}/approve")
    def approve_live_order_intent(
        intent_id: str,
        payload: LiveOrderDecisionPayload,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            return LiveOrderIntentService(database, settings=app_settings).approve(
                intent_id,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order intent not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/live/order-intents/{intent_id}/reject")
    def reject_live_order_intent(
        intent_id: str,
        payload: LiveOrderDecisionPayload,
        _: AdminUser,
    ) -> dict[str, Any]:
        try:
            return LiveOrderIntentService(database, settings=app_settings).reject(
                intent_id,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order intent not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/live/order-intents/{intent_id}/execute")
    def execute_live_order_intent(intent_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return LiveOrderIntentService(database, settings=app_settings).execute(intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order intent not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/rag/search")
    def search_rag(
        query: str,
        limit: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        service = RagService(database, knowledge_dir=str(app_settings.knowledge_dir))
        service.scan_once()
        hits = service.search(query, limit=limit)
        return {"hits": [_rag_hit_to_dict(hit) for hit in hits]}

    @app.get("/api/memory")
    def list_memory(
        query: str = "",
        kind: str = "",
        tag: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        service = MemoryService(database)
        if query or kind or tag:
            items = service.search(query=query, kind=kind, tag=tag)
        else:
            items = service.list_active()
        return {"items": [_memory_to_dict(item) for item in items]}

    @app.post("/api/memory/assertions")
    def propose_memory_assertion(
        payload: MemoryAssertionV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return MemoryAssertionService(database).propose(payload, actor=username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/memory/assertions")
    def list_memory_assertions(
        _: AdminUser,
        query: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        return {
            "items": MemoryAssertionService(database).list_assertions(
                query=query,
                status=status,
            )
        }

    @app.post("/api/memory/assertion-relations")
    def create_memory_assertion_relation(
        payload: MemoryAssertionRelationV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return MemoryAssertionService(database).add_relation(payload, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assertion not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/memory/assertions/{assertion_id}")
    def get_memory_assertion(assertion_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return MemoryAssertionService(database).get(assertion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assertion not found") from exc

    @app.post("/api/memory/assertions/{assertion_id}/review")
    def review_memory_assertion(
        assertion_id: str,
        payload: MemoryAssertionReviewV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return MemoryAssertionService(database).review(
                assertion_id,
                payload,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Assertion not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/skills/proposals")
    def propose_skill(payload: SkillProposalV1, username: AdminUser) -> dict[str, Any]:
        try:
            return SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).propose(payload, actor=username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/skills/proposals")
    def list_skill_proposals(_: AdminUser) -> dict[str, Any]:
        return {
            "items": SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).list_proposals()
        }

    @app.get("/api/skills/proposals/{proposal_id}")
    def get_skill_proposal(proposal_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            return SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).get_proposal(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill proposal not found") from exc

    @app.get("/api/skills/proposals/{proposal_id}/diff")
    def get_skill_proposal_diff(proposal_id: str, _: AdminUser) -> dict[str, Any]:
        try:
            proposal = SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).get_proposal(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill proposal not found") from exc
        return {
            "proposal_id": proposal_id,
            "definition_hash": proposal["definition_hash"],
            "diff": proposal["diff"],
        }

    @app.post("/api/skills/proposals/{proposal_id}/evaluate")
    def record_skill_evaluation(
        proposal_id: str,
        payload: SkillEvaluationV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).record_evaluation(
                proposal_id,
                payload,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill proposal not found") from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/skills/proposals/{proposal_id}/approve")
    def decide_skill_proposal(
        proposal_id: str,
        payload: SkillApprovalV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).decide(
                proposal_id,
                payload,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/skills/releases")
    def list_skill_releases(_: AdminUser, active_only: bool = False) -> dict[str, Any]:
        return {
            "items": SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).list_releases(active_only=active_only)
        }

    @app.post("/api/skills/releases/{release_id}/rollback")
    def rollback_skill_release(
        release_id: str,
        payload: SkillRollbackV1,
        username: AdminUser,
    ) -> dict[str, Any]:
        try:
            return SkillLifecycleService(
                database,
                attestation_secret=app_settings.skill_eval_attestation_secret,
            ).rollback(
                release_id,
                payload,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Skill release not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/memory/{memory_id}")
    def disable_memory(memory_id: str, _: AdminUser) -> dict[str, str]:
        MemoryService(database).disable(memory_id)
        return {"status": "ok"}

    @app.post("/api/reports/{run_id}/send-feishu")
    async def send_feishu(run_id: str, _: AdminUser) -> dict[str, object]:
        if not app_settings.feishu_webhook_url:
            return {"status": "skipped", "configured": False}
        run = AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        ).get_run(run_id)
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                app_settings.feishu_webhook_url,
                json={"msg_type": "text", "content": {"text": run.report_markdown[:3900]}},
            )
        return {"status": "sent", "configured": True}

    @app.websocket("/api/ws/runs/{run_id}")
    async def run_events(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        with database.session() as session:
            events = session.scalars(
                select(TraceEvent)
                .where(TraceEvent.run_id == run_id)
                .order_by(TraceEvent.created_at)
            ).all()
            for event in events:
                await websocket.send_json(_trace_to_dict(event))
        await websocket.close()

    return app


def _agent_run_sse(
    database: Database,
    settings: Settings,
    prompt: str,
    task_id: str,
    provider_name: str | None = None,
    provider_model: str | None = None,
    evaluation_mode: bool = False,
) -> Any:
    events: Queue[dict[str, Any] | None] = Queue()

    def worker() -> None:
        try:
            kernel = AgentKernel(
                database,
                knowledge_dir=str(settings.knowledge_dir),
                settings=settings,
                provider_name=provider_name,
                provider_model=provider_model,
                evaluation_mode=evaluation_mode,
            )
            run = AgentTaskExecutor(database).execute_chat(
                task_id,
                kernel,
                prompt,
                external_event_sink=events.put,
            )
            events.put({"event": "final", "task_id": task_id, "run": _run_to_dict(run)})
        except TaskExecutionError as exc:
            events.put(
                {
                    "event": "error",
                    "task_id": exc.task_id,
                    "error": exc.error,
                }
            )
            events.put(
                {
                    "event": "final",
                    "task_id": exc.task_id,
                    "run": _stream_failure_projection(run_id=exc.task_id),
                }
            )
        except TaskControlInterrupted as exc:
            events.put(
                {
                    "event": "task_controlled",
                    "task_id": exc.task_id,
                    "status": exc.status,
                }
            )
            events.put(
                {
                    "event": "final",
                    "task_id": exc.task_id,
                    "run": _stream_failure_projection(
                        run_id=exc.task_id,
                        status=exc.status,
                        decision="任务已停止，当前没有可交付的研究结论。",
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve a typed stream boundary
            events.put(
                {
                    "event": "error",
                    "task_id": task_id,
                    "error": {
                        "code": "stream_runtime_error",
                        "category": "stream",
                        "retryable": False,
                        "source": exc.__class__.__name__,
                    },
                }
            )
            events.put(
                {
                    "event": "final",
                    "task_id": task_id,
                    "run": _stream_failure_projection(run_id=task_id),
                }
            )
        finally:
            events.put(None)

    Thread(target=worker, daemon=True).start()
    while True:
        event = events.get()
        if event is None:
            break
        yield _format_sse(event)


def _stream_failure_projection(
    *,
    run_id: str = "",
    status: str = "failed",
    decision: str = "研究运行未产生可验证结果。",
) -> dict[str, Any]:
    """Return a bounded public terminal payload when a stream cannot project a run."""

    identifier = run_id or "stream_unavailable"
    next_action = "请稍后重试；若问题持续，请通过 /runs 提供运行编号。"
    report_markdown = f"## 结论\n{decision}\n\n## 下一步\n- {next_action}"
    return {
        "id": identifier,
        "mission_id": run_id,
        "runtime": "stream_boundary",
        "status": status,
        "report_markdown": report_markdown,
        "report_json": {
            "runtime": "stream_boundary",
            "operator_response": {
                "schema_version": "operator_response.v1",
                "mission_id": identifier,
                "outcome": "failed",
                "decision": decision,
                "confidence": "not_assessed",
                "evidence": [],
                "unknowns": ["最终结果投影失败，未将未验证信息作为结论。"],
                "next_actions": [next_action],
                "context_refs": [],
            },
        },
        "run_state_json": {"status": status, "stream_terminal": True},
        "trace_events": [],
        "legacy_run": False,
    }


def _prepare_agent_task(
    database: Database,
    *,
    prompt: str,
    surface: Literal["cli", "tui", "web", "api", "background"],
    provider_name: str,
    provider_model: str,
    idempotency_key: str,
) -> Any:
    task_service = AgentTaskService(database)
    existing = task_service.get_by_idempotency(idempotency_key)
    if existing is not None:
        return existing
    agent_session = AgentSessionService(database).create(
        AgentSessionCreate(
            title=prompt.strip()[:200] or "Agent Session",
            surface=surface,
            provider_config={"provider": provider_name, "model": provider_model},
            context_policy={"legacy_adapter": True, "max_history_turns": 1},
            created_by="legacy_agent_api",
        )
    )
    return task_service.create(
        AgentTaskCreate(
            session_id=agent_session.id,
            kind="chat_run",
            objective=prompt,
            idempotency_key=idempotency_key,
        ),
        actor="legacy_agent_api",
        start_immediately=True,
    )


def _task_control_or_http_error(
    database: Database,
    task_id: str,
    action: Literal["pause", "resume", "cancel", "retry", "branch"],
    payload: TaskControl,
) -> dict[str, Any]:
    service = AgentTaskService(database)
    try:
        row = getattr(service, action)(task_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invalid_task_transition",
                "task_id": exc.task_id,
                "current": exc.current,
                "target": exc.target,
            },
        ) from exc
    return task_to_dict(row)


def _task_event_sse(database: Database, task_id: str, *, after: int = 0) -> Any:
    cursor = max(after, 0)
    while True:
        rows = TaskEventService(database).list(task_id, after=cursor, limit=500)
        for row in rows:
            event = task_event_to_dict(row)
            cursor = row.sequence
            yield (
                f"id: {row.sequence}\n"
                f"event: {row.event}\n"
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            )
        task = AgentTaskService(database).get(task_id)
        if task.status in {"completed", "failed", "canceled", "paused", "retry_wait"}:
            break
        if not rows:
            yield (
                f"event: heartbeat\ndata: {json.dumps({'task_id': task_id, 'after': cursor})}\n\n"
            )
            time.sleep(1.0)


def _format_sse(event: dict[str, Any]) -> str:
    event_name = str(event.get("event", "message"))
    return f"event: {event_name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _tool_to_dict(tool: ToolDefinition) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "requires_approval": tool.requires_approval,
        "policy": tool.policy.to_dict(),
    }
    if tool.connector_origin is not None:
        payload["connector_origin"] = dict(tool.connector_origin)
    return payload


def _run_to_dict(run: CompletedAgentRun) -> dict[str, Any]:
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


def _trace_to_dict(event: TraceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "tool_name": event.tool_name,
        "status": event.status,
        "input_json": event.input_json,
        "output_json": event.output_json,
        "created_at": event.created_at.isoformat(),
    }


def _memory_to_dict(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "content": item.content,
        "source_run_id": item.source_run_id,
        "source_tool": item.source_tool,
        "importance": str(item.importance),
        "tags": item.tags,
        "confidence": str(item.confidence),
        "last_used_at": _iso_or_none(item.last_used_at),
        "usage_count": item.usage_count,
        "created_at": item.created_at.isoformat(),
    }


def _rag_hit_to_dict(hit: RagHit) -> dict[str, Any]:
    return {
        "source_path": hit.source_path,
        "title": hit.title,
        "chunk_index": hit.chunk_index,
        "score": hit.score,
        "content_preview": hit.content_preview,
    }


def _run_summary_to_dict(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "prompt": run.prompt,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "error": run.error,
    }


def _count_rows(session: Any, model: type[Any], where_clause: Any | None = None) -> int:
    statement = select(func.count()).select_from(model)
    if where_clause is not None:
        statement = statement.where(where_clause)
    return int(session.scalar(statement) or 0)


def _iso_or_none(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _age_seconds(value: object) -> int | None:
    if not isinstance(value, datetime):
        return None
    measured_at = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return max(0, int((utc_now() - measured_at).total_seconds()))


app = create_app()
