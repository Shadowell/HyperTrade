from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypertrade import worker
from hypertrade.config import DEFAULT_WORKER_STARTUP_DELAYS, Settings
from hypertrade.db import Database


def test_settings_defaults_preserve_legacy_worker_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPERTRADE_HEADLESS_MODE", raising=False)
    monkeypatch.delenv("MARKET_INGESTION_ENABLED", raising=False)
    monkeypatch.delenv("WORKER_STARTUP_STAGGER_ENABLED", raising=False)
    monkeypatch.delenv("WORKER_STARTUP_STAGGER_DELAYS", raising=False)

    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="")

    assert settings.headless_mode is False
    assert settings.market_ingestion_enabled is True
    assert settings.worker_startup_stagger_enabled is True
    assert settings.worker_startup_stagger_delays == DEFAULT_WORKER_STARTUP_DELAYS

    headless_settings = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        HYPERTRADE_HEADLESS_MODE=True,
        MARKET_INGESTION_ENABLED=False,
        WORKER_STARTUP_STAGGER_ENABLED=False,
    )
    assert headless_settings.headless_mode is True
    assert headless_settings.market_ingestion_enabled is False
    assert headless_settings.worker_startup_stagger_enabled is False


def test_headless_mode_disables_redundant_loops_and_keeps_research_loops() -> None:
    db = Database("sqlite:///:memory:")
    settings = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        HYPERTRADE_HEADLESS_MODE=True,
        MARKET_INGESTION_ENABLED=True,
        PAPER_ENABLED=True,
        AUTONOMOUS_PULSE_ENABLED=True,
        MONITOR_SCHEDULER_ENABLED=True,
        AGENT_TASK_WORKER_ENABLED=True,
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_WORKER_ENABLED=True,
        RESEARCH_TRIGGERS_ENABLED=True,
        ARC_PAPER_EFFECT_RECONCILE_ENABLED=True,
        RACE_JUDGE_ENABLED=True,
        ARC_MEMORY_DISTILLATION_ENABLED=True,
    )

    names = [name for name, _ in worker.build_loops(db, settings)]

    for omitted in (
        "market_ingestion",
        "market_rest_supplement",
        "paper_trading",
        "autonomous_market_pulse",
    ):
        assert omitted not in names

    for expected in (
        "rag_scanner",
        "monitor_scheduler",
        "agent_task_worker",
        "mission_worker_1",
        "research_trigger",
        "arc_observation",
        "arc_evolution",
        "arc_auto_review",
        "arc_paper_effect_reconcile",
        "arc_meta_tuning",
        "cognitive_memory_replay",
        "heartbeat",
        "avo_research",
        "race_judge",
        "memory_distillation",
    ):
        assert expected in names


def test_market_ingestion_enabled_false_disables_market_ingestion_loops() -> None:
    db = Database("sqlite:///:memory:")
    settings = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        HYPERTRADE_HEADLESS_MODE=False,
        MARKET_INGESTION_ENABLED=False,
        PAPER_ENABLED=True,
        AUTONOMOUS_PULSE_ENABLED=True,
    )

    names = [name for name, _ in worker.build_loops(db, settings)]

    assert "market_ingestion" not in names
    assert "market_rest_supplement" not in names
    assert "paper_trading" in names
    assert "autonomous_market_pulse" in names


def test_worker_startup_stagger_resolve_can_be_disabled_or_overridden() -> None:
    disabled = Settings(_env_file=None, DEEPSEEK_API_KEY="", WORKER_STARTUP_STAGGER_ENABLED=False)
    assert worker.resolve_startup_delays(disabled) == {}

    custom = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        WORKER_STARTUP_STAGGER_DELAYS={"arc_evolution": 1.5},
    )
    assert worker.resolve_startup_delays(custom, {"rag_scanner": 4.0}) == {
        "arc_evolution": 1.5,
        "rag_scanner": 4.0,
    }


def test_worker_main_staggers_non_critical_scan_loops_on_initial_start_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _FakeWatchdog:
        def __init__(self, _registry: Any) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    settings = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        DATABASE_URL=f"sqlite:///{tmp_path}/stagger.db",
        HYPERTRADE_HEADLESS_MODE=True,
        MONITOR_SCHEDULER_ENABLED=False,
        AGENT_TASK_WORKER_ENABLED=False,
        MISSION_RUNTIME_ENABLED=False,
        MISSION_RUNTIME_WORKER_ENABLED=False,
        RESEARCH_TRIGGERS_ENABLED=False,
        ARC_PAPER_EFFECT_RECONCILE_ENABLED=False,
        ARC_AVO_RESEARCH_ENABLED=False,
        RACE_JUDGE_ENABLED=False,
        ARC_MEMORY_DISTILLATION_ENABLED=False,
    )

    sleeps: list[tuple[str, float]] = []
    runs: dict[str, int] = {}
    current_task_loop: dict[asyncio.Task[Any], str] = {}

    async def fake_supervise(
        name: str,
        factory: Any,
        *,
        journal: Any = None,
        on_crash: Any = None,
        **kwargs: Any,
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        current_task_loop[task] = name
        # First invocation fails on arc_evolution to prove restarts do not re-sleep startup delay.
        try:
            await factory()
        except RuntimeError:
            await factory()

    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        task = asyncio.current_task()
        name = current_task_loop.get(task, "unknown") if task is not None else "unknown"
        sleeps.append((name, seconds))
        await real_sleep(0)

    def make_loop(loop_name: str, *, crash_first: bool = False) -> Any:
        async def _loop(_db: Database) -> None:
            runs[loop_name] = runs.get(loop_name, 0) + 1
            if crash_first and runs[loop_name] == 1:
                raise RuntimeError("transient crash")

        return _loop

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "LoopWatchdog", _FakeWatchdog)
    monkeypatch.setattr(worker, "supervise", fake_supervise)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "arc_evolution_loop", make_loop("arc_evolution", crash_first=True))
    monkeypatch.setattr(worker, "arc_observation_loop", make_loop("arc_observation"))
    monkeypatch.setattr(
        worker,
        "cognitive_memory_replay_loop",
        make_loop("cognitive_memory_replay"),
    )
    monkeypatch.setattr(worker, "arc_meta_tuning_loop", make_loop("arc_meta_tuning"))
    monkeypatch.setattr(worker, "rag_scanner_loop", make_loop("rag_scanner"))
    monkeypatch.setattr(worker, "arc_auto_review_loop", make_loop("arc_auto_review"))
    monkeypatch.setattr(worker, "heartbeat_loop", make_loop("heartbeat"))

    asyncio.run(worker.main())

    assert dict(sleeps) == {
        "arc_evolution": 2.0,
        "arc_observation": 5.0,
        "cognitive_memory_replay": 8.0,
        "arc_meta_tuning": 12.0,
        "rag_scanner": 15.0,
    }
    assert sleeps.count(("arc_evolution", 2.0)) == 1
    assert runs["arc_evolution"] == 2
    assert runs["arc_auto_review"] == 1
    assert runs["heartbeat"] == 1


def test_production_compose_and_env_example_configure_headless_mode_and_memory_limits() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    env_example = Path(".env.example").read_text(encoding="utf-8")

    api_service = compose["services"]["api"]
    worker_service = compose["services"]["worker"]

    assert api_service["mem_limit"] == "2g"
    assert worker_service["mem_limit"] == "3g"
    assert (
        api_service["environment"]["HYPERTRADE_HEADLESS_MODE"]
        == "${HYPERTRADE_HEADLESS_MODE:-true}"
    )
    assert (
        worker_service["environment"]["HYPERTRADE_HEADLESS_MODE"]
        == "${HYPERTRADE_HEADLESS_MODE:-true}"
    )
    assert "HYPERTRADE_HEADLESS_MODE=true" in env_example
