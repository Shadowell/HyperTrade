import asyncio
import logging
import os
import socket
from contextlib import suppress
from threading import Event, Thread
from typing import Any, cast

from hypertrade.agent.kernel import AgentKernel
from hypertrade.agent.task_executor import (
    AgentTaskExecutor,
    TaskControlInterrupted,
    TaskExecutionError,
)
from hypertrade.agent.tasks import AgentTaskService
from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
from hypertrade.config import Settings, get_settings
from hypertrade.db import Database
from hypertrade.market.client import MarketIngestor
from hypertrade.market.repository import MarketRepository
from hypertrade.monitoring import MonitorService
from hypertrade.paper.service import PaperTradingService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.rag.service import RagService
from hypertrade.research.graph import ResearchGraphRuntime
from hypertrade.research.graph_tools import (
    BuiltinResearchToolRunner,
    ResearchBitProReadAdapter,
)
from hypertrade.research.role_provider import (
    ChatResearchRoleProvider,
    DeterministicGapRoleProvider,
)
from hypertrade.research.triggers import ResearchTriggerService
from hypertrade.runtime.adapters.capability_catalog import (
    CatalogCapabilityPolicy,
    SqlCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.context_engine import (
    ContextArtifactEngine,
    SqlContextArtifactStore,
)
from hypertrade.runtime.adapters.research_planner import ProviderBackedResearchPlanner
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.adapters.tool_runtime import (
    GovernedToolExecutor,
    SqlObservationStore,
    builtin_handlers,
)
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.models import TERMINAL_STATUSES, MissionStatus
from hypertrade.skills.lifecycle import ApprovedSkillLoader

logger = logging.getLogger("hypertrade.worker")


async def _mission_runtime_resources(
    db: Database,
    settings: Settings,
) -> tuple[MissionRuntime, SqlAlchemyMissionStore, tuple[object, ...]]:
    """Build the same governed runtime as the API, owned by the worker process.

    The worker receives only read-only catalog capabilities. A lease controls
    execution ownership; a provider cannot expand tool permissions or budgets.
    """

    store = SqlAlchemyMissionStore(db.url)
    catalog = SqlCapabilityCatalog(db.url)
    observations = SqlObservationStore(db.url)
    context_store = SqlContextArtifactStore(db.url)
    await catalog.bootstrap(builtin_capabilities())
    runtime = MissionRuntime(
        store,
        ProviderBackedResearchPlanner(
            provider=ProviderRuntime(settings).get_chat_provider(
                selected=settings.active_chat_provider,
            )
        ),
        GovernedToolExecutor(
            catalog,
            builtin_handlers(db, knowledge_dir=str(settings.knowledge_dir)),
            observations=observations,
        ),
        CatalogCapabilityPolicy(catalog),
        ContextArtifactEngine(context_store),
    )
    return runtime, store, (store, catalog, observations, context_store)


async def mission_worker_once(
    db: Database,
    *,
    settings: Settings | None = None,
    worker_id: str | None = None,
    runtime: MissionRuntime | None = None,
    store: SqlAlchemyMissionStore | None = None,
) -> dict[str, Any]:
    """Claim and execute one durable Mission, with a bounded heartbeat lease."""

    active_settings = settings or get_settings()
    if not (
        active_settings.mission_runtime_enabled
        and active_settings.mission_runtime_worker_enabled
    ):
        return {"status": "disabled", "mission_id": None}
    owner = worker_id or f"{socket.gethostname()}:{os.getpid()}:missions"
    resources: tuple[object, ...] = ()
    if runtime is None or store is None:
        runtime, store, resources = await _mission_runtime_resources(db, active_settings)
    mission = await store.claim_next(
        owner,
        lease_seconds=active_settings.mission_runtime_lease_seconds,
    )
    if mission is None:
        await _dispose_resources(resources)
        return {"status": "idle", "mission_id": None}

    stop_heartbeat = asyncio.Event()

    async def heartbeat() -> None:
        interval = max(1.0, active_settings.mission_runtime_lease_seconds / 3)
        while not stop_heartbeat.is_set():
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=interval)
                return
            except TimeoutError:
                try:
                    await store.heartbeat(
                        mission.mission_id,
                        owner,
                        lease_seconds=active_settings.mission_runtime_lease_seconds,
                    )
                except (KeyError, PermissionError):
                    return

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        completed = await runtime.run(mission.mission_id)
        return {
            "status": completed.status.value,
            "mission_id": completed.mission_id,
            "plan_version": completed.active_plan_version,
        }
    except Exception:
        logger.exception("mission_worker execution failed mission_id=%s", mission.mission_id)
        current = await store.get(mission.mission_id)
        if current.status not in TERMINAL_STATUSES:
            await store.append_event(
                mission.mission_id,
                "mission_worker_failed",
                actor=f"worker:{owner}",
                payload={"code": "worker_execution_failure"},
            )
            try:
                current = await store.get(mission.mission_id)
                failed = await store.transition(
                    mission.mission_id,
                    expected_version=current.version,
                    target=MissionStatus.FAILED,
                    actor=f"worker:{owner}",
                    reason="worker_execution_failure",
                    terminal_summary=(
                        "Mission execution failed before a validated result was produced."
                    ),
                )
                return {"status": failed.status.value, "mission_id": failed.mission_id}
            except (KeyError, RuntimeError, ValueError):
                logger.exception("mission_worker failed to record terminal state")
        return {"status": "failed", "mission_id": mission.mission_id}
    finally:
        stop_heartbeat.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        with suppress(KeyError, PermissionError):
            await store.release(mission.mission_id, owner)
        await _dispose_resources(resources)


async def _dispose_resources(resources: tuple[object, ...]) -> None:
    for resource in resources:
        dispose = getattr(resource, "dispose", None)
        if dispose is not None:
            await dispose()


async def mission_worker_loop(db: Database) -> None:
    settings = get_settings()
    runtime, store, resources = await _mission_runtime_resources(db, settings)
    try:
        while True:
            try:
                result = await mission_worker_once(
                    db,
                    settings=settings,
                    runtime=runtime,
                    store=store,
                )
                if result.get("status") not in {"idle", "disabled"}:
                    logger.info(
                        "mission_worker status=%s mission_id=%s",
                        result.get("status"),
                        result.get("mission_id"),
                    )
            except Exception:
                logger.exception("mission_worker loop failed")
            await asyncio.sleep(settings.mission_runtime_poll_interval_seconds)
    finally:
        await _dispose_resources(resources)


async def rag_scanner_loop(db: Database) -> None:
    settings = get_settings()
    service = RagService(db, knowledge_dir=settings.knowledge_dir)
    while True:
        result = service.scan_once()
        logger.info("rag_scan scanned=%s ingested=%s", result.scanned_files, result.ingested_files)
        await asyncio.sleep(settings.rag_scan_interval_seconds)


async def market_ingestion_loop(db: Database) -> None:
    settings = get_settings()
    ingestor = MarketIngestor(settings, MarketRepository(db))
    await ingestor.ingest_ws_forever()


async def market_rest_supplement_loop(db: Database) -> None:
    settings = get_settings()
    ingestor = MarketIngestor(settings, MarketRepository(db))
    while True:
        try:
            count = await ingestor.ingest_rest_once()
            logger.info("okx_rest_supplement tickers=%s", count)
        except Exception:
            logger.exception("okx_rest_supplement failed")
        await asyncio.sleep(settings.okx_rest_supplement_interval_seconds)


async def paper_trading_loop(db: Database) -> None:
    settings = get_settings()
    service = PaperTradingService(db, settings=settings)
    while True:
        try:
            result = service.run_once()
            logger.info("paper_trading tick status=%s fills=%s", result.status, result.fill_count)
        except Exception:
            logger.exception("paper_trading failed")
        await asyncio.sleep(settings.paper_loop_interval_seconds)


def monitor_scheduler_once(
    db: Database,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.monitor_scheduler_enabled:
        return {
            "status": "disabled",
            "ran": [],
            "skipped": [],
            "failed": [],
        }
    adapter = BitProToolAdapter(BitProMcpClient(settings=active_settings))
    return MonitorService(db, bitpro_adapter=adapter).run_due_monitors()


async def monitor_scheduler_loop(db: Database) -> None:
    settings = get_settings()
    while True:
        try:
            result = monitor_scheduler_once(db, settings=settings)
            logger.info(
                "monitor_scheduler status=%s ran=%s skipped=%s failed=%s",
                result.get("status"),
                len(result.get("ran", [])),
                len(result.get("skipped", [])),
                len(result.get("failed", [])),
            )
        except Exception:
            logger.exception("monitor_scheduler failed")
        await asyncio.sleep(settings.monitor_loop_interval_seconds)


def agent_task_worker_once(
    db: Database,
    *,
    settings: Settings | None = None,
    worker_id: str | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.agent_task_worker_enabled:
        return {"status": "disabled", "task_id": None}
    owner = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    task_service = AgentTaskService(db)
    task = task_service.claim_next(
        owner,
        lease_seconds=active_settings.agent_task_lease_seconds,
    )
    if task is None:
        return {"status": "idle", "task_id": None}
    if task.kind not in {"chat_run", "research_graph", "triggered_research"}:
        error = {
            "code": "unsupported_task_kind",
            "category": "task_dispatch",
            "retryable": False,
            "kind": task.kind,
        }
        task_service.transition(
            task.id,
            "failed",
            actor=f"worker:{owner}",
            reason="unsupported_task_kind",
            error=error,
        )
        return {"status": "failed", "task_id": task.id, "error": error}

    stop_heartbeat = Event()

    def heartbeat() -> None:
        interval = max(5.0, active_settings.agent_task_lease_seconds / 3)
        while not stop_heartbeat.wait(interval):
            try:
                task_service.heartbeat(
                    task.id,
                    owner,
                    lease_seconds=active_settings.agent_task_lease_seconds,
                )
            except (KeyError, PermissionError):
                return

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        if task.kind == "research_graph":
            chat_provider = ProviderRuntime(active_settings).get_chat_provider(
                selected=active_settings.active_chat_provider
            )
            role_provider = (
                ChatResearchRoleProvider(
                    chat_provider,
                    skill_loader=ApprovedSkillLoader(db),
                )
                if chat_provider is not None
                else DeterministicGapRoleProvider()
            )
            bitpro_adapter = BitProToolAdapter(BitProMcpClient(settings=active_settings))
            result = ResearchGraphRuntime(
                db,
                provider=role_provider,
                tool_runner=BuiltinResearchToolRunner(
                    db,
                    bitpro_adapter=cast(ResearchBitProReadAdapter, bitpro_adapter),
                    knowledge_dir=active_settings.knowledge_dir,
                ),
            ).run(task.id)
            return {
                "status": str(result["task"]["status"]),
                "task_id": task.id,
                "evidence_count": len(result["evidence"]),
            }
        kernel = AgentKernel(
            db,
            knowledge_dir=str(active_settings.knowledge_dir),
            settings=active_settings,
            provider_name=active_settings.active_chat_provider,
            evaluation_mode=task.kind == "triggered_research",
        )
        run = AgentTaskExecutor(db).execute_chat(task.id, kernel, task.objective)
        return {"status": "completed", "task_id": task.id, "run_id": run.id}
    except TaskControlInterrupted:
        current = task_service.get(task.id)
        return {"status": current.status, "task_id": task.id}
    except TaskExecutionError as exc:
        current = task_service.get(task.id)
        return {
            "status": current.status,
            "task_id": task.id,
            "error": exc.error,
        }
    except Exception:
        if task.kind != "research_graph":
            raise
        current = task_service.get(task.id)
        return {
            "status": current.status,
            "task_id": task.id,
            "error": dict(current.error_json),
        }
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)


async def agent_task_worker_loop(db: Database) -> None:
    settings = get_settings()
    while True:
        try:
            result = await asyncio.to_thread(agent_task_worker_once, db, settings=settings)
            if result.get("status") != "idle":
                logger.info(
                    "agent_task_worker status=%s task_id=%s",
                    result.get("status"),
                    result.get("task_id"),
                )
        except Exception:
            logger.exception("agent_task_worker failed")
        await asyncio.sleep(max(0.25, settings.agent_task_poll_interval_seconds))


def research_trigger_worker_once(
    db: Database,
    *,
    settings: Settings | None = None,
    worker_id: str | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.research_triggers_enabled:
        return {"status": "disabled", "trigger_id": None}
    owner = worker_id or f"{socket.gethostname()}:{os.getpid()}:triggers"
    service = ResearchTriggerService(db, settings=active_settings)
    trigger = service.claim_due(owner)
    if trigger is None:
        return {"status": "idle", "trigger_id": None}
    result = service.run_claimed(str(trigger["id"]), owner)
    return {
        "status": str(result["status"]),
        "trigger_id": trigger["id"],
        "fire_id": result["id"],
        "task_id": result["task_id"],
        "reason": result["reason"],
    }


async def research_trigger_loop(db: Database) -> None:
    settings = get_settings()
    while True:
        try:
            result = await asyncio.to_thread(
                research_trigger_worker_once,
                db,
                settings=settings,
            )
            if result.get("status") not in {"idle", "disabled"}:
                logger.info(
                    "research_trigger status=%s trigger_id=%s task_id=%s",
                    result.get("status"),
                    result.get("trigger_id"),
                    result.get("task_id"),
                )
        except Exception:
            logger.exception("research_trigger failed")
        await asyncio.sleep(max(1.0, settings.research_trigger_poll_interval_seconds))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = Database(settings.database_url)
    tasks = [
        rag_scanner_loop(db),
        market_ingestion_loop(db),
        market_rest_supplement_loop(db),
    ]
    if settings.paper_enabled:
        tasks.append(paper_trading_loop(db))
    if settings.monitor_scheduler_enabled:
        tasks.append(monitor_scheduler_loop(db))
    if settings.agent_task_worker_enabled:
        tasks.append(agent_task_worker_loop(db))
    if settings.mission_runtime_enabled and settings.mission_runtime_worker_enabled:
        tasks.append(mission_worker_loop(db))
    if settings.research_triggers_enabled:
        tasks.append(research_trigger_loop(db))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
