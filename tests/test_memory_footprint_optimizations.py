"""Regression suite pinning HyperTrade's startup and runtime memory footprint optimizations."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypertrade.arc import evolution, store
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionService
from hypertrade.db import (
    ArcEpisodicMemory,
    ArcMission,
    ArcSemanticAssertion,
    Database,
    RagChunk,
)
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    LayeredMemoryService,
    SemanticMemoryAssertionV1,
)
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagService
from hypertrade.runtime import heartbeat
from sqlalchemy import event as sa_event

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY_STARTUP_PACKAGES = ("pandas", "numpy", "pyarrow", "backtrader", "yfinance")


@pytest.mark.parametrize("entrypoint", ["hypertrade.main", "hypertrade.worker"])
def test_entrypoints_do_not_eagerly_import_heavy_data_libraries(entrypoint: str) -> None:
    """Headless API and worker cold-start must keep heavy local data packages unloaded."""
    probe = (
        "import json, sys; "
        f"__import__({entrypoint!r}); "
        f"loaded = sorted(p for p in {HEAVY_STARTUP_PACKAGES!r} if p in sys.modules); "
        "print(json.dumps(loaded))"
    )
    output = subprocess.check_output([sys.executable, "-c", probe], text=True)
    assert json.loads(output.strip()) == []


def test_dockerfile_and_compose_cap_glibc_malloc_arenas() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "MALLOC_ARENA_MAX=2" in dockerfile

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for svc_name in ("api", "worker"):
        env = compose["services"][svc_name]["environment"]
        assert env.get("MALLOC_ARENA_MAX") == "${MALLOC_ARENA_MAX:-2}"

    eval_compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.eval.yml").read_text(encoding="utf-8")
    )
    for svc_name in ("api", "worker"):
        env = eval_compose["services"][svc_name]["environment"]
        assert env.get("MALLOC_ARENA_MAX") == "${MALLOC_ARENA_MAX:-2}"


def test_trim_process_heap_is_safe_across_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    orig_cached = heartbeat._glibc_malloc_trim
    orig_cached.cache_clear()
    try:
        calls: list[int] = []
        monkeypatch.setattr(heartbeat, "_glibc_malloc_trim", lambda: None)
        assert heartbeat.trim_process_heap() is False

        def fake_trim(pad: int) -> int:
            calls.append(pad)
            return 1

        monkeypatch.setattr(heartbeat, "_glibc_malloc_trim", lambda: fake_trim)
        assert heartbeat.trim_process_heap(pad=0) is True
        assert heartbeat.trim_process_heap(pad=-16) is True
        assert calls == [0, 0]

        def broken_trim(_pad: int) -> int:
            raise OSError("libc unavailable")

        monkeypatch.setattr(heartbeat, "_glibc_malloc_trim", lambda: broken_trim)
        assert heartbeat.trim_process_heap() is False
    finally:
        orig_cached.cache_clear()


def test_rag_search_hybrid_skips_embedding_json_and_orm_hydration(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'rag.db'}")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    for idx in range(12):
        (knowledge_dir / f"doc_{idx:02d}.md").write_text(
            f"# Strategy Note {idx}\n\n"
            f"Paragraph {idx} discusses momentum breakout risk gates and turnover limits.\n\n"
            + ("filler context " * 40),
            encoding="utf-8",
        )

    rag = RagService(db, knowledge_dir=knowledge_dir)
    scan = rag.scan_once()
    assert scan.ingested_files == 12

    statements: list[str] = []
    hydrated_chunks: list[Any] = []

    @sa_event.listens_for(db.engine, "before_cursor_execute")
    def _capture_sql(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    @sa_event.listens_for(RagChunk, "load")
    def _on_load(target: RagChunk, _context: Any) -> None:
        hydrated_chunks.append(target)

    hits = rag.search_hybrid("momentum breakout", limit=3)
    assert len(hits) == 3
    assert hydrated_chunks == []
    assert all("embedding_json" not in sql for sql in statements)
    assert all(hit.content_preview == hit.content[:240] for hit in hits)
    assert hits[0].score >= hits[1].score >= hits[2].score


def test_layered_memory_retrieval_hydrates_only_top_k_winners(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'layered.db'}")
    db.create_all()
    svc = LayeredMemoryService(db)

    for idx in range(25):
        svc.record_semantic_assertion(
            SemanticMemoryAssertionV1(
                claim=f"Trend following rule #{idx} on BTC-USDT-SWAP volatility expansion",
                applicable_regimes=["bull_trend"],
                confidence=Decimal(f"0.{50 + idx:02d}"),
                metadata={"symbols": ["BTC-USDT-SWAP"], "timeframe": "1H"},
            )
        )
        svc.record_episode(
            EpisodicMemoryItemV1(
                mission_id=f"arc_ep_{idx}",
                experiment_id=f"exp_{idx}",
                symbols=["BTC-USDT-SWAP"],
                timeframe="1H",
                market_regime="bull_trend",
                event_type="backtest_success",
                metrics_delta={"sharpe_delta": idx * 0.05, "blob": "x" * 200},
                raw_evidence_ref=f"bt_{idx}",
                reflection_summary=f"Episode #{idx} momentum breakout reflection",
            )
        )

    hydrated_semantics: list[str] = []
    hydrated_episodes: list[str] = []

    @sa_event.listens_for(ArcSemanticAssertion, "load")
    def _on_sem_load(target: ArcSemanticAssertion, _ctx: Any) -> None:
        hydrated_semantics.append(target.id)

    @sa_event.listens_for(ArcEpisodicMemory, "load")
    def _on_ep_load(target: ArcEpisodicMemory, _ctx: Any) -> None:
        hydrated_episodes.append(target.id)

    semantics, episodes = svc.retrieve_context_for_task(
        goal="BTC-USDT-SWAP momentum breakout",
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        current_regime="bull_trend",
        top_k_semantic=3,
        top_k_episodic=2,
    )
    assert len(semantics) == 3
    assert len(episodes) == 2
    assert len(hydrated_semantics) == 3
    assert len(hydrated_episodes) == 2

    hydrated_episodes.clear()
    listed = svc.list_episodes(symbols=["BTC-USDT-SWAP"], timeframe="1H", limit=4)
    assert len(listed) == 4
    assert len(hydrated_episodes) == 4


def _assert_development_memory_parity(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    store.configure_store(db)
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    windows = ResearchWindowsV1(as_of=now.date() - timedelta(days=1))
    dev_start, dev_end = windows.window("development")
    strategy_code = "class S1:\n    pass\n"
    code_hash = hashlib.sha256(strategy_code.encode()).hexdigest()

    heavy_context = {
        "orders": {
            "sample_limit": 200,
            "fills": [{"fill_id": i, "payload": "z" * 256} for i in range(50)],
        },
        "paper_feedback": {"daily": ["row" * 64 for _ in range(14)]},
    }
    m_with_dev = ARCController(
        goal=ARCGoalV1(
            objective="with dev receipt",
            paper_review_required=True,
            research_mode="avo",
            research_windows=windows,
            symbols=["BTC-USDT-SWAP"],
            timeframes=["1H"],
            paper_initial_equity=Decimal("1000"),
            evolution_context=heavy_context,
            budget=ARCBudgetV1(max_candidates=3),
        )
    )
    m_with_dev.apply_event("goal_compiled", {"goal": m_with_dev.projection.goal.model_dump()})
    att = ARCCandidateAttemptV1(
        attempt_id="att_1",
        candidate_id="cand_1",
        hypothesis="tighter trailing stop reduces giveback",
        strategy_code=strategy_code,
        strategy_spec={"symbol": "BTC-USDT-SWAP", "timeframe": "1H", "family": "ma_crossover"},
    )
    m_with_dev.apply_event("candidate_proposed", {"attempt": att.model_dump(mode="json")})
    m_with_dev.projection.avo["development"] = {
        "att_1": {
            "purpose": "development",
            "code_sha256": code_hash,
            "backtest_id": "bt_dev_1",
            "passed": True,
            "reasons": [],
            "metrics": {
                "config_sha256": "d" * 64,
                "cost_policy_hash": "c" * 64,
                "net_return": 0.125,
                "max_drawdown": 0.042,
                "evaluation_window": {
                    "purpose": "development",
                    "start_date": str(dev_start),
                    "end_date": str(dev_end),
                },
            },
        }
    }
    m_with_dev.projection.avo["messages"] = [{"role": "assistant", "content": "m" * 2048}]
    store.save_mission(m_with_dev)

    for idx in range(5):
        noise = ARCController(
            goal=ARCGoalV1(
                objective=f"noise {idx}",
                paper_review_required=True,
                research_mode="avo",
                research_windows=windows,
                symbols=["BTC-USDT-SWAP"],
                timeframes=["1H"],
            )
        )
        noise.apply_event("goal_compiled", {"goal": noise.projection.goal.model_dump()})
        noise.apply_event("mission_failed", {})

    store.reset_runtime()
    hydrated_missions: list[str] = []

    @sa_event.listens_for(ArcMission, "load")
    def _on_mission_load(target: ArcMission, _ctx: Any) -> None:
        hydrated_missions.append(target.mission_id)

    mem_svc = MemoryService(db)
    entries, manifest = mem_svc.research_context(
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        windows=windows,
    )
    assert hydrated_missions == []
    assert manifest["source_scan_truncated"] is False
    assert len(entries) == 1
    assert entries[0]["candidate_id"] == "cand_1"

    evo_svc = EvolutionService(db)
    base_ctx = {
        "baseline": {"strategy_spec": {"symbol": "BTC-USDT-SWAP", "timeframe": "1H"}},
        "target_id": "bitpro",
        "source_strategy_id": 7,
    }
    fast_ctx = copy.deepcopy(base_ctx)
    fast_mem = evo_svc._memory(fast_ctx, now)
    assert hydrated_missions == []
    assert len(fast_mem) == 1

    real_load = store.load_projection
    monkeypatch.setattr(
        evolution,
        "load_projection",
        lambda s, row, **kw: real_load(s, row, **kw),
    )
    ref_ctx = copy.deepcopy(base_ctx)
    ref_mem = evo_svc._memory(ref_ctx, now)
    assert len(hydrated_missions) == 6
    assert fast_mem == ref_mem
    assert fast_ctx == ref_ctx


def test_development_memory_projection_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.reset_store()
    db = Database(f"sqlite:///{tmp_path / 'arc_mem.db'}")
    db.create_all()
    try:
        _assert_development_memory_parity(db, monkeypatch)
    finally:
        store.reset_store()
        db.engine.dispose()


def test_development_memory_projection_postgres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl or os.getuid() == 0:
        pytest.skip("isolated PostgreSQL binaries require an unprivileged local user")

    cluster = tmp_path / "pg"
    subprocess.run(
        [
            initdb,
            "-D",
            str(cluster),
            "-A",
            "trust",
            "-U",
            "mem_test",
            "--no-locale",
            "-E",
            "UTF8",
        ],
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(cluster),
            "-l",
            str(tmp_path / "pg.log"),
            "-w",
            "start",
            "-o",
            f"-F -p {port} -h 127.0.0.1 -k /tmp",
        ],
        check=True,
        capture_output=True,
    )
    store.reset_store()
    db = Database(f"postgresql+psycopg://mem_test@127.0.0.1:{port}/postgres")
    try:
        db.create_all()
        _assert_development_memory_parity(db, monkeypatch)
    finally:
        store.reset_store()
        db.engine.dispose()
        subprocess.run(
            [pg_ctl, "-D", str(cluster), "-m", "immediate", "stop"],
            check=False,
            capture_output=True,
        )
