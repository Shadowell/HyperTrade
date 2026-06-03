"""FastAPI application wiring for the HyperTrade harness.

The API is the bridge between the learning surfaces (frontend `/harness`, CLI
remote mode, tests) and the backend services. Endpoints stay thin: they validate
HTTP input, call the Agent/tool service, and return redacted runtime state.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from queue import Queue
from threading import Thread
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.backtest.service import BacktestService
from hypertrade.config import Settings, get_settings
from hypertrade.db import (
    AgentRun,
    Database,
    LiveOrderIntent,
    MarketTicker,
    MemoryItem,
    RagChunk,
    RagDocument,
    TraceEvent,
    utc_now,
)
from hypertrade.evals.service import AgentEvalSuite
from hypertrade.live.service import LiveOrderIntentService
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.paper.service import PaperTradingService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.rag.service import RagHit, RagService
from hypertrade.strategy.experiment import StrategyExperimentService
from hypertrade.strategy.sdk import Candle
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolDefinition, ToolRegistry

SESSION_COOKIE = "hypertrade_session"


class LoginPayload(BaseModel):
    username: str
    password: str


class AgentRunPayload(BaseModel):
    prompt: str


class ProviderSelectionPayload(BaseModel):
    provider: str


class PaperControlPayload(BaseModel):
    action: Literal["pause", "resume", "close", "reset"]
    symbol: str | None = None


class StrategyResearchPayload(BaseModel):
    prompt: str


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


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
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
    def providers(_: AdminUser) -> dict[str, list[dict[str, object]]]:
        return {
            "providers": ProviderRuntime(app_settings).list_providers(
                selected=str(app.state.active_chat_provider)
            )
        }

    @app.post("/api/harness/provider-selection")
    def select_provider(payload: ProviderSelectionPayload, _: AdminUser) -> dict[str, Any]:
        requested = payload.provider.strip().lower()
        runtime = ProviderRuntime(app_settings)
        known = {str(provider["name"]) for provider in runtime.list_providers()}
        if requested not in known:
            raise HTTPException(status_code=400, detail="Unknown provider")
        app.state.active_chat_provider = requested
        providers_payload = runtime.list_providers(selected=requested)
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
    def tools(_: AdminUser) -> dict[str, list[dict[str, object]]]:
        return {"tools": [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]}

    @app.get("/api/evals/status")
    def eval_status(_: AdminUser) -> dict[str, Any]:
        return AgentEvalSuite().status()

    @app.get("/api/harness/overview")
    def harness_overview(_: AdminUser) -> dict[str, Any]:
        providers_payload = ProviderRuntime(app_settings).list_providers(
            selected=str(app.state.active_chat_provider)
        )
        tools_payload = [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]
        top_movers = [
            {
                "inst_id": row.inst_id,
                "last": str(row.last),
                "volume_ccy_24h": str(row.volume_ccy_24h),
                "change_utc0_pct": str(row.change_utc0_pct),
            }
            for row in MarketRepository(database).top_movers(limit=8)
        ]

        with database.session() as session:
            latest_market_at = session.scalar(select(func.max(MarketTicker.updated_at)))
            latest_memory_at = session.scalar(select(func.max(MemoryItem.created_at)))
            runs = session.scalars(
                select(AgentRun).order_by(desc(AgentRun.created_at)).limit(6)
            ).all()
            trace_events = session.scalars(
                select(TraceEvent).order_by(desc(TraceEvent.created_at)).limit(12)
            ).all()
            return {
                "generated_at": utc_now().isoformat(),
                "providers": providers_payload,
                "tools": tools_payload,
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
                "evals": AgentEvalSuite().status(),
            }

    @app.post("/api/agent/runs")
    def create_run(payload: AgentRunPayload, _: AdminUser) -> dict[str, Any]:
        kernel = AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
            provider_name=str(app.state.active_chat_provider),
        )
        run = kernel.run_chat(payload.prompt)
        return _run_to_dict(run)

    @app.post("/api/agent/runs/stream")
    def stream_run(payload: AgentRunPayload, _: AdminUser) -> StreamingResponse:
        return StreamingResponse(
            _agent_run_sse(
                database,
                app_settings,
                payload.prompt,
                provider_name=str(app.state.active_chat_provider),
            ),
            media_type="text/event-stream",
        )

    @app.get("/api/agent/runs")
    def list_runs(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
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
    def get_run(run_id: str, _: AdminUser) -> dict[str, Any]:
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

    @app.get("/api/market/tickers/latest")
    def latest_tickers(_: AdminUser, limit: int = 50) -> dict[str, list[dict[str, str]]]:
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
    def market_ticker(symbol: str, _: AdminUser) -> dict[str, Any]:
        return AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        )._market_ticker_payload(symbol)

    @app.get("/api/market/candles/{symbol}")
    def market_candles(
        symbol: str,
        _: AdminUser,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        )._market_candles_payload(symbol=symbol, bar=bar, limit=limit)

    @app.post("/api/market/compare")
    def market_compare(payload: MarketComparePayload, _: AdminUser) -> dict[str, Any]:
        return AgentKernel(
            database,
            knowledge_dir=str(app_settings.knowledge_dir),
            settings=app_settings,
        )._market_compare_payload(
            symbols=payload.symbols,
            bar=payload.bar,
            limit=payload.limit,
        )

    @app.get("/api/paper/status")
    def paper_status(_: AdminUser) -> dict[str, Any]:
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
        _: AdminUser,
    ) -> dict[str, Any]:
        return StrategyResearchService(database).create(payload.prompt)

    @app.get("/api/strategy/research")
    def list_strategy_research(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyResearchService(database).list_recent()}

    @app.post("/api/strategy/experiments")
    def create_strategy_experiment(
        payload: StrategyResearchPayload,
        _: AdminUser,
    ) -> dict[str, Any]:
        return StrategyExperimentService(database).create(payload.prompt)

    @app.get("/api/strategy/experiments")
    def list_strategy_experiments(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": StrategyExperimentService(database).list_recent()}

    @app.post("/api/backtests")
    def create_backtest(payload: BacktestPayload, _: AdminUser) -> dict[str, Any]:
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
    def list_backtests(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
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
    def list_live_order_intents(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
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
        _: AdminUser,
        query: str,
        limit: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        service = RagService(database, knowledge_dir=str(app_settings.knowledge_dir))
        service.scan_once()
        hits = service.search(query, limit=limit)
        return {"hits": [_rag_hit_to_dict(hit) for hit in hits]}

    @app.get("/api/memory")
    def list_memory(
        _: AdminUser,
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
    provider_name: str | None = None,
) -> Any:
    events: Queue[dict[str, Any] | None] = Queue()

    def worker() -> None:
        try:
            kernel = AgentKernel(
                database,
                knowledge_dir=str(settings.knowledge_dir),
                settings=settings,
                provider_name=provider_name,
            )
            run = kernel.run_chat_with_events(prompt, event_sink=events.put)
            events.put({"event": "final", "run": _run_to_dict(run)})
        except Exception as exc:  # noqa: BLE001 - stream API errors to client
            events.put({"event": "error", "error": str(exc)})
        finally:
            events.put(None)

    Thread(target=worker, daemon=True).start()
    while True:
        event = events.get()
        if event is None:
            break
        yield _format_sse(event)


def _format_sse(event: dict[str, Any]) -> str:
    event_name = str(event.get("event", "message"))
    return f"event: {event_name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _tool_to_dict(tool: ToolDefinition) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "requires_approval": tool.requires_approval,
    }


def _run_to_dict(run: CompletedAgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "report_markdown": run.report_markdown,
        "report_json": run.report_json,
        "run_state_json": run.run_state_json,
        "trace_events": [_trace_to_dict(event) for event in run.trace_events],
    }


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
