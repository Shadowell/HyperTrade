"""FastAPI application wiring for the HyperTrade harness.

The API is the bridge between the operator surfaces (frontend `/harness`, CLI
remote mode, tests) and the backend services. Endpoints stay thin: they validate
HTTP input, call the Agent/tool service, and return redacted runtime state.
"""

import json
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
from pydantic import BaseModel
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
from hypertrade.memory.service import MemoryService
from hypertrade.monitoring import MonitorService
from hypertrade.paper.service import PaperTradingService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.rag.service import RagHit, RagService
from hypertrade.research.evidence import EvidenceService, EvidenceSourceUnavailable
from hypertrade.research.evidence_schemas import (
    EvidenceLifecycleRequest,
    EvidenceSupersedeRequest,
    ResearchEvidenceInput,
)
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
from hypertrade.research.paper_observation import PaperObservationService
from hypertrade.research.paper_promotion import PaperPromotionAdapter, PaperPromotionService
from hypertrade.research.role_provider import (
    ChatResearchRoleProvider,
    DeterministicGapRoleProvider,
)
from hypertrade.research.schemas import ResearchJobCreate, ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.strategy_cards import StrategyCardService
from hypertrade.strategy.experiment import StrategyExperimentService
from hypertrade.strategy.library import StrategyLibraryService
from hypertrade.strategy.sdk import Candle
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolDefinition, ToolRegistry
from hypertrade.world_model.defensive_actions import DefensiveActionEngine
from hypertrade.world_model.service import WorldModelService

SESSION_COOKIE = "hypertrade_session"


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


class PaperPromotionRequestPayload(BaseModel):
    evidence_id: str
    reason: str


class PaperPromotionApprovalPayload(BaseModel):
    reason: str
    idempotency_key: str


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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if app_settings.database_url.startswith("sqlite"):
            database.create_all()
        yield

    app = FastAPI(title="HyperTrade API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.db = database
    app.state.active_chat_provider = app_settings.active_chat_provider
    app.state.active_chat_model = ""
    app.state.bitpro_adapter = bitpro_adapter
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
        return str(username)

    AdminUser = Annotated[str, Depends(require_admin)]

    def get_bitpro_adapter() -> BitProApiAdapter:
        if app.state.bitpro_adapter is None:
            app.state.bitpro_adapter = BitProToolAdapter(BitProMcpClient(settings=app_settings))
        adapter: BitProApiAdapter = app.state.bitpro_adapter
        return adapter

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
            ChatResearchRoleProvider(chat_provider)
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

    @app.post("/api/agent/runs")
    def create_run(payload: AgentRunPayload, request: Request) -> dict[str, Any]:
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
            run = AgentTaskExecutor(database).execute_chat(task.id, kernel, payload.prompt)
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
    def stream_run(payload: AgentRunPayload, request: Request) -> StreamingResponse:
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
        return _task_control_or_http_error(database, task_id, "pause", payload)

    @app.post("/api/agent/tasks/{task_id}/resume")
    def resume_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        return _task_control_or_http_error(database, task_id, "resume", payload)

    @app.post("/api/agent/tasks/{task_id}/cancel")
    def cancel_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        return _task_control_or_http_error(database, task_id, "cancel", payload)

    @app.post("/api/agent/tasks/{task_id}/retry")
    def retry_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
        return _task_control_or_http_error(database, task_id, "retry", payload)

    @app.post("/api/agent/tasks/{task_id}/branch")
    def branch_agent_task(task_id: str, payload: TaskControl, _: AdminUser) -> dict[str, Any]:
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
    def list_runs() -> dict[str, list[dict[str, Any]]]:
        with database.session() as session:
            runs = session.scalars(
                select(AgentRun).order_by(desc(AgentRun.created_at)).limit(25)
            ).all()
            return {
                "runs": [
                    {
                        "id": run.id,
                        "prompt": run.prompt,
                        "status": run.status,
                        "created_at": run.created_at.isoformat(),
                    }
                    for run in runs
                ]
            }

    @app.get("/api/agent/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
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
    def create_research_graph(
        payload: ResearchGraphCreate, username: AdminUser
    ) -> dict[str, Any]:
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
            return ExperimentLedgerService(database).register(
                payload, actor=f"admin:{username}"
            )
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
            return {
                "items": ExperimentLedgerService(database).executions(fingerprint)
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experiment not found") from exc

    @app.get("/api/research/experiments/{fingerprint}/diff/{other_fingerprint}")
    def diff_research_experiments(
        fingerprint: str, other_fingerprint: str
    ) -> dict[str, Any]:
        try:
            return ExperimentLedgerService(database).diff(
                fingerprint, other_fingerprint
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Experiment not found") from exc

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
        except TaskControlInterrupted as exc:
            events.put(
                {
                    "event": "task_controlled",
                    "task_id": exc.task_id,
                    "status": exc.status,
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
        finally:
            events.put(None)

    Thread(target=worker, daemon=True).start()
    while True:
        event = events.get()
        if event is None:
            break
        yield _format_sse(event)


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
