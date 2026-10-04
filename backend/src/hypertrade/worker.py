import asyncio
import hashlib
import json
import logging
import os
import socket
from collections.abc import Callable
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from threading import Event, Thread
from typing import Any, cast

from hypertrade.agent.kernel import AgentKernel
from hypertrade.agent.task_executor import (
    AgentTaskExecutor,
    TaskControlInterrupted,
    TaskExecutionError,
)
from hypertrade.agent.tasks import AgentTaskService
from hypertrade.arc.observation import observe_arc_missions_once
from hypertrade.arc.runtime_journal import record_model_exchange, record_runtime_error
from hypertrade.arc.store import configure_store
from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
from hypertrade.config import Settings, get_settings
from hypertrade.db import Database
from hypertrade.market.client import MarketIngestor
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.arc_integration import replay_arc_cognitive_memory_once
from hypertrade.memory.distillation import (
    CausalSummarizer,
    DistillationBudgetExhausted,
    distill_pending_regimes,
)
from hypertrade.memory.layered_service import EpisodicMemoryItemV1
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
from hypertrade.runtime.adapters.research_planner import build_mission_planner
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
        build_mission_planner(
            settings,
            ProviderRuntime(settings).get_chat_provider(
                selected=settings.active_chat_provider,
            ),
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
        active_settings.mission_runtime_enabled and active_settings.mission_runtime_worker_enabled
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
        completed = await runtime.run(
            mission.mission_id,
            fencing_token=mission.fencing_token,
        )
        return {
            "status": completed.status.value,
            "mission_id": completed.mission_id,
            "plan_version": completed.active_plan_version,
        }
    except Exception as exc:
        logger.exception("mission_worker execution failed mission_id=%s", mission.mission_id)
        await _journal(db, "worker.mission_execution", exc, mission_id=mission.mission_id)
        current = await store.get(mission.mission_id)
        if current.status not in TERMINAL_STATUSES:
            await store.append_event(
                mission.mission_id,
                "mission_worker_failed",
                actor=f"worker:{owner}",
                payload={"code": "worker_execution_failure"},
                fencing_token=mission.fencing_token,
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
                    fencing_token=mission.fencing_token,
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
            except Exception as exc:
                logger.exception("mission_worker loop failed")
                await _journal(db, "worker.mission", exc)
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
        except Exception as exc:
            logger.exception("okx_rest_supplement failed")
            await _journal(db, "worker.okx_rest_supplement", exc)
        await asyncio.sleep(settings.okx_rest_supplement_interval_seconds)


async def paper_trading_loop(db: Database) -> None:
    settings = get_settings()
    service = PaperTradingService(db, settings=settings)
    while True:
        try:
            result = service.run_once()
            logger.info("paper_trading tick status=%s fills=%s", result.status, result.fill_count)
        except Exception as exc:
            logger.exception("paper_trading failed")
            await _journal(db, "worker.paper_trading", exc)
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
        except Exception as exc:
            logger.exception("monitor_scheduler failed")
            await _journal(db, "worker.monitor_scheduler", exc)
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
        except Exception as exc:
            logger.exception("agent_task_worker failed")
            await _journal(db, "worker.agent_task", exc)
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
        except Exception as exc:
            logger.exception("research_trigger failed")
            await _journal(db, "worker.research_trigger", exc)
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
    full_mission_cutover = (
        settings.mission_runtime_enabled and settings.mission_runtime_canary_percent >= 100
    )
    if settings.agent_task_worker_enabled and not full_mission_cutover:
        tasks.append(agent_task_worker_loop(db))
    if settings.mission_runtime_enabled and settings.mission_runtime_worker_enabled:
        # Each loop owns its runtime resources and claims through the durable lease,
        # so fencing — not this count — is what prevents double execution. Default
        # stays 1: chat requests queue behind each other until an operator opts in.
        for _ in range(max(1, settings.mission_runtime_worker_concurrency)):
            tasks.append(mission_worker_loop(db))
    if settings.research_triggers_enabled and not full_mission_cutover:
        tasks.append(research_trigger_loop(db))
    if settings.autonomous_pulse_enabled:
        tasks.append(autonomous_market_pulse_loop(db))
    tasks.append(arc_observation_loop(db))
    tasks.append(arc_evolution_loop(db))
    tasks.append(arc_auto_review_loop(db))
    tasks.append(arc_meta_tuning_loop(db))
    tasks.append(cognitive_memory_replay_loop(db))
    if settings.mission_runtime_worker_enabled:
        tasks.append(avo_research_loop(db))
    if settings.self_healing_evolution_enabled:
        tasks.append(self_healing_evolution_loop(db, settings=settings))
    if settings.race_judge_enabled:
        tasks.append(race_judge_loop(db, settings=settings))
    if settings.arc_memory_distillation_enabled:
        tasks.append(memory_distillation_loop(db, settings=settings))
    await asyncio.gather(*tasks)


def memory_distillation_worker_once(
    db: Database,
    *,
    settings: Settings | None = None,
    causal_summarizer: CausalSummarizer | None = None,
) -> dict[str, object]:
    """Run one idempotent evidence-set distillation pass."""
    active_settings = settings or get_settings()
    summarizer = causal_summarizer
    version = "injected-v1"
    if summarizer is None:
        if not active_settings.arc_memory_distillation_enabled:
            return {"status": "disabled", "ids": []}
        provider = ProviderRuntime(active_settings).get_chat_provider(
            selected=active_settings.active_chat_provider
        )
        if provider is None:
            return {"status": "skipped", "reason": "provider_unavailable", "ids": []}
        summarizer = _provider_causal_summarizer(
            provider,
            db=db,
            max_calls=active_settings.arc_memory_distillation_max_model_calls_per_pass,
        )
        identity = f"cognitive-distillation-json-v1:{provider.name}:{provider.model}"
        version = f"model-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
    return distill_pending_regimes(
        db,
        causal_summarizer=summarizer,
        summarizer_version=version,
    )


async def memory_distillation_loop(
    db: Database,
    *,
    settings: Settings | None = None,
) -> None:
    """Periodically distill episodes only when the paid-model ARC channel is enabled."""
    active_settings = settings or get_settings()
    while True:
        await _guarded(
            db,
            "worker.memory_distillation",
            lambda: memory_distillation_worker_once(db, settings=active_settings),
        )
        await asyncio.sleep(active_settings.arc_memory_distillation_poll_interval_seconds)


async def cognitive_memory_replay_loop(db: Database) -> None:
    """Recover missed inline cognitive projections from the canonical ARC journal."""
    configure_store(db)
    while True:
        await _guarded(
            db,
            "worker.cognitive_memory_replay",
            replay_arc_cognitive_memory_once,
        )
        await asyncio.sleep(60)


def _provider_causal_summarizer(
    provider: Any,
    *,
    db: Database,
    max_calls: int,
) -> CausalSummarizer:
    calls = 0

    def summarize(
        episodes: list[EpisodicMemoryItemV1],
    ) -> tuple[str, str, Decimal] | None:
        nonlocal calls
        if calls >= max_calls:
            raise DistillationBudgetExhausted
        evidence = [
            {
                "id": item.id,
                "event_type": item.event_type,
                "market_regime": item.market_regime,
                "symbols": item.symbols,
                "timeframe": item.timeframe,
                "metrics": item.metrics_delta,
                "summary": item.reflection_summary[:500],
            }
            for item in episodes[:20]
        ]
        request_content = json.dumps(evidence, default=str, sort_keys=True)
        request_hash = hashlib.sha256(request_content.encode()).hexdigest()
        calls += 1
        response = provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Return one JSON object only. Derive a conservative reusable quant rule "
                        "from the supplied audited episodes. If causality is unsupported, return "
                        '{"status":"unknown"}. Otherwise return status=ok, claim, '
                        "assertion_type (causal_heuristic|structural_constraint|factor_affinity), "
                        "and confidence in [0,1]. Do not invent metrics or evidence."
                    ),
                },
                {"role": "user", "content": request_content},
            ]
        )
        record_model_exchange(
            f"memory-distillation:{request_hash[:20]}",
            provider=str(provider.name),
            model=str(provider.model),
            request_hash=request_hash,
            context_record_id=f"episode-set:{request_hash}",
            content=response.content,
            reasoning_content=response.reasoning_content,
            tool_calls=[],
            usage=response.usage.to_dict(),
            db=db,
        )
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return None
        assertion_type = str(payload.get("assertion_type") or "")
        if assertion_type not in {
            "causal_heuristic",
            "structural_constraint",
            "factor_affinity",
        }:
            return None
        claim = str(payload.get("claim") or "").strip()
        try:
            confidence = Decimal(str(payload.get("confidence")))
        except (InvalidOperation, ValueError):
            return None
        if not claim or not Decimal("0") <= confidence <= Decimal("1"):
            return None
        return claim, assertion_type, confidence

    return summarize


async def _guarded(db: Database, component: str, step: Callable[[], Any]) -> Any:
    """Run one loop step; a failure is journalled in the database, not only stdout."""
    try:
        return await asyncio.to_thread(step)
    except Exception as exc:
        logger.exception("%s failed", component)
        await _journal(db, component, exc)
        return None


async def _journal(
    db: Database, component: str, exc: Exception, *, mission_id: str | None = None
) -> None:
    await asyncio.to_thread(record_runtime_error, component, exc, mission_id=mission_id, db=db)


async def autonomous_market_pulse_loop(
    db: Database,
    settings: Settings | None = None,
    *,
    service: Any | None = None,
) -> None:
    """7x24 Autonomous Market Pulse & Live Perception loop."""
    from hypertrade.agent.pulse import AutonomousMarketPulseService
    from hypertrade.providers.runtime import ProviderRuntime

    active_settings = settings or get_settings()
    if service is None:
        try:
            chat_provider = ProviderRuntime(active_settings).get_chat_provider(
                selected=active_settings.active_chat_provider
            )
        except Exception:
            chat_provider = None

        service = AutonomousMarketPulseService(
            db,
            settings=active_settings,
            chat_provider=chat_provider,
        )
    logger.info(
        "autonomous_market_pulse_loop started interval=%ss symbols=%s",
        active_settings.autonomous_pulse_interval_seconds,
        active_settings.autonomous_pulse_symbols,
    )
    while True:
        try:
            result = await asyncio.to_thread(service.run_pulse_once, trigger="scheduled")
            decisions = result.get("decisions", [])
            orders = result.get("orders_executed", [])
            logger.info(
                "autonomous_pulse completed decisions=%s orders=%s duration=%sms",
                len(decisions),
                len(orders),
                result.get("duration_ms", 0),
            )
        except Exception:
            logger.exception("autonomous_market_pulse_loop cycle error")
        await asyncio.sleep(max(1, active_settings.autonomous_pulse_interval_seconds))


async def arc_meta_tuning_loop(db: Database) -> None:
    """Daily offline meta-tuning of evolution parameters (advisory by default)."""
    from hypertrade.arc.evolution import EvolutionService
    from hypertrade.arc.meta_tuning import tune_once

    configure_store(db)
    service = EvolutionService(db)
    while True:
        result = await _guarded(db, "worker.arc_meta_tuning", lambda: tune_once(service))
        if result and result.get("status") == "applied":
            revision = result.get("report", {}).get("applied_revision")
            logger.info("arc_meta_tuning applied=%s", revision)
        await asyncio.sleep(3600)


async def arc_observation_loop(db: Database) -> None:
    """Poll paper_observing ARC missions and record BitPro snapshots."""
    configure_store(db)
    while True:
        result = await _guarded(db, "worker.arc_observation", observe_arc_missions_once)
        if result and result.get("observed"):
            logger.info("arc_observation observed=%s", result.get("observed"))
        await asyncio.sleep(60)


async def arc_evolution_loop(db: Database) -> None:
    from hypertrade.arc.evolution import EvolutionService
    from hypertrade.arc.evolution_alerts import evolution_alerts_once

    configure_store(db)
    service = EvolutionService(db)
    while True:
        await _guarded(db, "worker.arc_evolution", service.tick)
        await _guarded(db, "worker.arc_evolution_alerts", lambda: evolution_alerts_once(db))
        await asyncio.sleep(60)


async def arc_auto_review_loop(db: Database) -> None:
    from hypertrade.arc.auto_review import auto_review_once

    configure_store(db)
    while True:
        await _guarded(db, "worker.arc_auto_review", lambda: auto_review_once(db))
        await asyncio.sleep(15)


async def avo_research_loop(db: Database) -> None:
    """Claim persisted AVO research. Historical ARC/Paper instances are never restarted here."""
    from hypertrade.arc.avo import run_pending_avo_once

    configure_store(db)
    while True:
        await _guarded(db, "worker.avo_research", run_pending_avo_once)
        await asyncio.sleep(5)


async def self_healing_evolution_loop(
    db: Database,
    settings: Settings | None = None,
    *,
    engine: Any | None = None,
) -> None:
    """Monitors DEGRADED execution strategies and performs autonomous parameter self-healing."""
    from hypertrade.paper.self_healing import SelfHealingEvolutionEngine

    active_settings = settings or get_settings()
    evolution_engine = engine or SelfHealingEvolutionEngine()
    poll_interval = max(5.0, active_settings.self_healing_evolution_interval_seconds)
    logger.info("self_healing_evolution_loop started poll_interval=%ss", poll_interval)
    while True:
        try:
            healed = await asyncio.to_thread(evolution_engine.scan_and_heal_all_degraded)
            if healed:
                logger.info(
                    "self_healing_evolution_loop healed %d strategies: %s",
                    len(healed),
                    [h.offspring_strategy_id for h in healed],
                )
        except Exception as exc:
            logger.exception("self_healing_evolution_loop cycle error")
            await _journal(db, "worker.self_healing_evolution", exc)
        await asyncio.sleep(poll_interval)


async def race_judge_loop(
    db: Database,
    settings: Settings | None = None,
    *,
    daemon: Any | None = None,
) -> None:
    """Periodically evaluates paper twin strategies, forward gates, and triggers relay."""
    from hypertrade.paper.race_judge import RaceJudgeDaemon

    active_settings = settings or get_settings()
    judge_daemon = daemon or RaceJudgeDaemon(db=db, settings=active_settings)
    poll_interval = max(5.0, float(active_settings.race_judge_interval_seconds))
    logger.info("race_judge_loop started poll_interval=%ss", poll_interval)
    while True:
        try:
            records = await asyncio.to_thread(judge_daemon.scan_and_judge_all)
            if records:
                logger.info(
                    "race_judge_loop evaluated %d twin pairs: %s",
                    len(records),
                    [(r.parent_strategy_id, r.challenger_strategy_id, r.state) for r in records],
                )
        except Exception as exc:
            logger.exception("race_judge_loop cycle error")
            await _journal(db, "worker.race_judge", exc)
        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(main())
