from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.config import Settings, get_settings
from hypertrade.db import (
    AgentRun,
    Database,
    MarketTicker,
    MemoryItem,
    RagChunk,
    RagDocument,
    TraceEvent,
    utc_now,
)
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.tools.registry import ToolDefinition, ToolRegistry

SESSION_COOKIE = "hypertrade_session"


class LoginPayload(BaseModel):
    username: str
    password: str


class AgentRunPayload(BaseModel):
    prompt: str


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
            secure=app_settings.app_env == "production",
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
        return {"providers": ProviderRuntime(app_settings).list_providers()}

    @app.get("/api/harness/tools")
    def tools(_: AdminUser) -> dict[str, list[dict[str, object]]]:
        return {"tools": [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]}

    @app.get("/api/harness/overview")
    def harness_overview(_: AdminUser) -> dict[str, Any]:
        providers_payload = ProviderRuntime(app_settings).list_providers()
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
            }

    @app.post("/api/agent/runs")
    def create_run(payload: AgentRunPayload, _: AdminUser) -> dict[str, Any]:
        kernel = AgentKernel(database, knowledge_dir=str(app_settings.knowledge_dir))
        run = kernel.run_chat(payload.prompt)
        return _run_to_dict(run)

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
            kernel = AgentKernel(database, knowledge_dir=str(app_settings.knowledge_dir))
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

    @app.get("/api/memory")
    def list_memory(_: AdminUser) -> dict[str, list[dict[str, Any]]]:
        return {"items": [_memory_to_dict(item) for item in MemoryService(database).list_active()]}

    @app.delete("/api/memory/{memory_id}")
    def disable_memory(memory_id: str, _: AdminUser) -> dict[str, str]:
        MemoryService(database).disable(memory_id)
        return {"status": "ok"}

    @app.post("/api/reports/{run_id}/send-feishu")
    async def send_feishu(run_id: str, _: AdminUser) -> dict[str, object]:
        if not app_settings.feishu_webhook_url:
            return {"status": "skipped", "configured": False}
        run = AgentKernel(database, knowledge_dir=str(app_settings.knowledge_dir)).get_run(run_id)
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
        "created_at": item.created_at.isoformat(),
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
