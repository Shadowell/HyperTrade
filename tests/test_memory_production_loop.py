from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.arc import store
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.config import Settings
from hypertrade.db import (
    ArcEpisodicMemory,
    ArcHypothesisNode,
    Database,
    MemoryItem,
)
from hypertrade.main import create_app
from hypertrade.memory.arc_integration import (
    ingest_projection,
    replay_arc_cognitive_memory_once,
    sync_cognitive_to_memory_items,
)
from hypertrade.memory.distillation import (
    deterministic_causal_summarizer,
    distill_pending_regimes,
)
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    LayeredMemoryService,
    SemanticMemoryAssertionV1,
)
from hypertrade.memory.service import MemoryService
from sqlalchemy import select


def _make_projection(
    *,
    attempt_id: str,
    candidate_id: str,
    hypothesis: str,
    source_strategy_id: int | None = 583,
    target_id: str = "bitpro",
    events: list[SimpleNamespace] | None = None,
    paper_outcome: dict[str, Any] | None = None,
    include_attempt: bool = True,
) -> SimpleNamespace:
    evo_ctx: dict[str, Any] = {"market_regime": "high_volatility", "target_id": target_id}
    if source_strategy_id is not None:
        evo_ctx["source_strategy_id"] = source_strategy_id
    goal = SimpleNamespace(
        objective="Research bounded ETH evolution hypothesis",
        symbols=["ETH-USDT-SWAP"],
        timeframes=["1H"],
        evolution_context=evo_ctx,
        feedback_parent=None,
    )
    attempts = (
        [
            SimpleNamespace(
                attempt_id=attempt_id,
                candidate_id=candidate_id,
                hypothesis=hypothesis,
                strategy_code=f"class Strategy_{attempt_id}: pass",
                strategy_spec={"family": "atr_breakout"},
            )
        ]
        if include_attempt
        else []
    )
    return SimpleNamespace(
        goal=goal,
        attempts=attempts,
        events=events or [],
        paper_outcome=paper_outcome or {},
    )


def test_cross_mission_strategy_lineage_recall(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'lineage.db'}")
    db.create_all()

    first_proj = _make_projection(
        attempt_id="att-583-1",
        candidate_id="cand-583-1",
        hypothesis="Widen ATR trailing stop to 2.5x for parent #583",
        source_strategy_id=583,
        events=[
            SimpleNamespace(
                event_id="evt-dev-1",
                event_type="avo_development_result",
                payload={
                    "attempt_id": "att-583-1",
                    "result": {
                        "attempt_id": "att-583-1",
                        "passed": False,
                        "backtest_id": "bt-583-1",
                        "metrics": {"sharpe": 0.65, "relative_pnl": -0.02},
                    },
                },
            )
        ],
    )
    first = ingest_projection(db, "mission-583-1", first_proj, max_prompt_tokens=600)
    assert first.status == "ok"

    # Unrelated parent #999 must not leak into #583 lineage recall
    other_proj = _make_projection(
        attempt_id="att-999-1",
        candidate_id="cand-999-1",
        hypothesis="HYPOTHESIS_FOR_PARENT_999_ONLY",
        source_strategy_id=999,
    )
    ingest_projection(db, "mission-999-1", other_proj, max_prompt_tokens=600)

    with db.session() as session:
        nodes = session.scalars(select(ArcHypothesisNode)).all()
        by_tree = {node.tree_id: node for node in nodes}
        assert by_tree["arc:mission-583-1"].metadata_json["lineage_key"] == "bitpro:583"
        assert by_tree["arc:mission-999-1"].metadata_json["lineage_key"] == "bitpro:999"

    # Mission 2 on #583 starts with zero local attempts yet recalls mission 1's hypothesis
    second_proj = _make_projection(
        attempt_id="att-583-2",
        candidate_id="cand-583-2",
        hypothesis="unused",
        source_strategy_id=583,
        include_attempt=False,
    )
    recalled = ingest_projection(db, "mission-583-2", second_proj, max_prompt_tokens=800)
    assert "Widen ATR trailing stop to 2.5x for parent #583" in recalled.prompt_context
    assert "HYPOTHESIS_FOR_PARENT_999_ONLY" not in recalled.prompt_context


@pytest.mark.parametrize(
    ("verdict", "expected_event_type", "expected_status", "expected_prune_reason"),
    [
        ("won", "paper_race_won", "promoted", None),
        ("lost_futility", "paper_race_lost", "pruned", "lost_futility"),
        ("lost_exam", "paper_race_lost", "pruned", "lost_exam"),
    ],
)
def test_forward_race_outcome_ingestion_updates_episode_and_hypothesis(
    tmp_path: Path,
    verdict: str,
    expected_event_type: str,
    expected_status: str,
    expected_prune_reason: str | None,
) -> None:
    db = Database(f"sqlite:///{tmp_path / f'race-{verdict}.db'}")
    db.create_all()
    proj = _make_projection(
        attempt_id="att-race-1",
        candidate_id="cand-race-1",
        hypothesis="Race candidate hypothesis",
        events=[
            SimpleNamespace(
                event_id=f"evt-race-{verdict}",
                event_type="paper_observation_ended",
                payload={
                    "reason": "race_finished",
                    "attempt_id": "att-race-1",
                    "paper_instance_id": "paper_42",
                    "outcome_id": f"fo_{verdict}",
                    "verdict": verdict,
                    "metrics": {
                        "excess_return_pct": 1.85 if verdict == "won" else -2.1,
                        "observed_hours": 72.0,
                    },
                },
            )
        ],
    )
    ingest_projection(db, f"mission-race-{verdict}", proj)
    # Re-ingest to confirm idempotency
    ingest_projection(db, f"mission-race-{verdict}", proj)

    with db.session() as session:
        episodes = session.scalars(select(ArcEpisodicMemory)).all()
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.event_type == expected_event_type
        assert ep.raw_evidence_ref == f"outcome:fo_{verdict}"
        assert ep.metadata_json["recall_eligible"] is True
        assert verdict in ep.reflection_summary
        assert "excess_return_pct=" in ep.reflection_summary

        nodes = session.scalars(select(ArcHypothesisNode)).all()
        assert len(nodes) == 1
        assert nodes[0].status == expected_status
        assert nodes[0].prune_reason == expected_prune_reason


def test_neutral_paper_session_end_does_not_emit_race_outcome(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'neutral.db'}")
    db.create_all()
    proj = _make_projection(
        attempt_id="att-neutral",
        candidate_id="cand-neutral",
        hypothesis="Neutral session end",
        events=[
            SimpleNamespace(
                event_id="evt-session-ended",
                event_type="paper_observation_ended",
                payload={
                    "reason": "paper_session_ended",
                    "attempt_id": "att-neutral",
                    "paper_instance_id": "paper_99",
                },
            ),
            SimpleNamespace(
                event_id="evt-timeout",
                event_type="paper_observation_ended",
                payload={
                    "reason": "race_finished",
                    "attempt_id": "att-neutral",
                    "paper_instance_id": "paper_99",
                    "outcome_id": "fo_timeout",
                    "verdict": "expired_timeout",
                },
            ),
        ],
    )
    res = ingest_projection(db, "mission-neutral", proj)
    assert res.episodes_recorded == 0
    with db.session() as session:
        assert session.scalars(select(ArcEpisodicMemory)).all() == []


def test_deterministic_causal_summarizer_and_sync_to_memory_items(tmp_path: Path) -> None:
    assert deterministic_causal_summarizer([]) is None
    single = [
        EpisodicMemoryItemV1(
            mission_id="m1",
            symbols=["ETH-USDT-SWAP"],
            timeframe="1H",
            market_regime="high_volatility",
            event_type="backtest_success",
            metrics_delta={"sharpe": 1.4},
            reflection_summary="Single episode",
        )
    ]
    assert deterministic_causal_summarizer(single) is None

    ineligible_pair = [
        *single,
        EpisodicMemoryItemV1(
            mission_id="m2",
            symbols=["ETH-USDT-SWAP"],
            timeframe="1H",
            market_regime="high_volatility",
            event_type="backtest_success",
            metrics_delta={"sharpe": 1.8},
            reflection_summary="Final holdout episode",
            metadata={"recall_eligible": False},
        ),
    ]
    assert deterministic_causal_summarizer(ineligible_pair) is None

    pair = [
        *single,
        EpisodicMemoryItemV1(
            mission_id="m2",
            symbols=["ETH-USDT-SWAP"],
            timeframe="1H",
            market_regime="high_volatility",
            event_type="paper_race_won",
            metrics_delta={"sharpe": 1.8, "excess_return_pct": 2.4},
            reflection_summary="Won race",
        ),
    ]
    summary = deterministic_causal_summarizer(pair)
    assert summary is not None
    claim, assertion_type, confidence = summary
    assert assertion_type == "causal_heuristic"
    assert Decimal("0.55") <= confidence <= Decimal("0.80")
    assert "ETH-USDT-SWAP" in claim
    assert "1H" in claim
    assert "high_volatility" in claim
    assert "backtest_success=1" in claim
    assert "paper_race_won=1" in claim
    assert "sharpe median=1.6 mean=1.6" in claim
    assert "excess_return_pct median=2.4 mean=2.4" in claim

    db = Database(f"sqlite:///{tmp_path / 'sync.db'}")
    db.create_all()
    memory = LayeredMemoryService(db)
    for idx, event_type in enumerate(("backtest_success", "paper_race_won", "paper_race_lost")):
        memory.record_episode(
            EpisodicMemoryItemV1(
                mission_id=f"m-{idx}",
                symbols=["BTC-USDT-SWAP"],
                timeframe="4H",
                market_regime="bull_trend",
                event_type=event_type,
                metrics_delta={"sharpe": 1.2 + idx * 0.2},
                raw_evidence_ref=f"outcome:fo_{idx}",
                reflection_summary=f"Audited {event_type} summary {idx}",
                metadata={"verdict": "won" if event_type == "paper_race_won" else "lost_exam"},
            )
        )

    distill_result = distill_pending_regimes(
        db,
        causal_summarizer=deterministic_causal_summarizer,
        summarizer_version="deterministic-v1",
    )
    assert distill_result["status"] == "completed"
    assert len(distill_result["ids"]) == 1  # type: ignore[arg-type]

    created_first = sync_cognitive_to_memory_items(db)
    assert created_first == 3  # 1 distilled semantic rule + 2 race outcomes
    created_second = sync_cognitive_to_memory_items(db)
    assert created_second == 0

    with db.session() as session:
        items = session.scalars(select(MemoryItem)).all()
        assert len(items) == 3
        kinds = {item.kind for item in items}
        assert kinds == {"arc_semantic_rule", "arc_race_outcome"}
        assert all(item.source_run_id == "cognitive-replay" for item in items)
        assert all(item.source_tool == "cognitive_memory.sync" for item in items)
        rule_item = next(item for item in items if item.kind == "arc_semantic_rule")
        assert {"btc-usdt-swap", "4h", "bull_trend", "cognitive_memory"} <= set(rule_item.tags)

    # Disabling a synced item keeps it disabled on subsequent syncs
    MemoryService(db).disable(rule_item.id)
    assert sync_cognitive_to_memory_items(db) == 0
    with db.session() as session:
        refreshed = session.get(MemoryItem, rule_item.id)
        assert refreshed is not None and refreshed.disabled is True


def test_replay_loop_backfills_paper_outcome_and_syncs_memory_items(tmp_path: Path) -> None:
    store.reset_store()
    db = Database(f"sqlite:///{tmp_path / 'replay.db'}")
    db.create_all()
    store.configure_store(db)
    try:
        for idx, verdict in enumerate(("won", "lost_exam")):
            goal = ARCGoalV1(
                objective="Forward race replay test",
                symbols=["SOL-USDT-SWAP"],
                timeframes=["1H"],
                paper_review_required=True,
                research_mode="avo",
                research_windows=ResearchWindowsV1(),
                paper_initial_equity=Decimal("100"),
                budget=ARCBudgetV1(max_candidates=3),
                evolution_context={
                    "target_id": "bitpro",
                    "source_strategy_id": 583,
                    "market_regime": "sideways_range",
                },
            )
            ctrl = ARCController(mission_id=f"arc_replay_{idx}", goal=goal)
            ctrl.apply_event("goal_compiled", {"goal": goal.model_dump()})
            attempt = ARCCandidateAttemptV1(
                attempt_id=f"att_{idx}",
                candidate_id=f"cand_{idx}",
                hypothesis=f"Hypothesis {idx} for #583",
                strategy_code=f"class S{idx}: pass",
                strategy_spec={"family": "trend"},
            )
            ctrl.apply_event("candidate_proposed", {"attempt": attempt.model_dump(mode="json")})
            ctrl.apply_event(
                "paper_started",
                {"attempt_id": f"att_{idx}", "paper_instance_id": f"paper_{idx}"},
            )
            ctrl.apply_event(
                "paper_observation_ended",
                {
                    "attempt_id": f"att_{idx}",
                    "paper_instance_id": f"paper_{idx}",
                    "reason": "race_finished",
                    "verdict": verdict,
                    "outcome_id": f"fo_replay_{idx}",
                    "metrics": {"excess_return_pct": 1.2 if verdict == "won" else -1.5},
                },
            )
        store.reset_runtime()

        replay_res = replay_arc_cognitive_memory_once()
        assert replay_res == {"status": "ok", "missions": 2, "unchanged": 0}
        assert MemoryService(db).cognitive_counts() == {
            "episodic_count": 2,
            "semantic_count": 1,
            "active_semantic_count": 1,
            "hypothesis_count": 2,
        }
        items = MemoryService(db).search(query="SOL-USDT-SWAP")
        assert {item.kind for item in items} == {"arc_semantic_rule", "arc_race_outcome"}
    finally:
        store.reset_store()


def test_memory_service_cognitive_counts(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'counts.db'}")
    db.create_all()
    memory = LayeredMemoryService(db)
    ingest_projection(
        db,
        "mission-counts",
        _make_projection(
            attempt_id="att-c1",
            candidate_id="cand-c1",
            hypothesis="Count test hypothesis",
            events=[
                SimpleNamespace(
                    event_id="evt-c1",
                    event_type="avo_development_result",
                    payload={
                        "attempt_id": "att-c1",
                        "result": {
                            "attempt_id": "att-c1",
                            "passed": True,
                            "backtest_id": "bt-c1",
                            "metrics": {"sharpe": 1.1},
                        },
                    },
                )
            ],
        ),
    )
    active_id = memory.record_semantic_assertion(
        SemanticMemoryAssertionV1(claim="Active semantic rule", applicable_regimes=["bull_trend"])
    )
    deprecated_id = memory.record_semantic_assertion(
        SemanticMemoryAssertionV1(claim="Deprecated rule", applicable_regimes=["bear_trend"])
    )
    memory.deprecate_semantic_assertion(deprecated_id, reason="obsolete")
    assert active_id != deprecated_id

    assert MemoryService(db).cognitive_counts() == {
        "episodic_count": 1,
        "semantic_count": 2,
        "active_semantic_count": 1,
        "hypothesis_count": 1,
    }


def test_overview_and_memory_endpoints_expose_cognitive_and_live_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'api.db'}")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()

    MemoryService(db).write(
        content="Operator prefers bounded risk sizing.",
        kind="user_preference",
        source_run_id="run-1",
        source_tool="memory.write",
        tags=["risk"],
    )
    memory = LayeredMemoryService(db)
    for idx, verdict in enumerate(("won", "lost_futility")):
        memory.record_episode(
            EpisodicMemoryItemV1(
                mission_id=f"m-api-{idx}",
                symbols=["ETH-USDT-SWAP"],
                timeframe="1H",
                market_regime="high_volatility",
                event_type="paper_race_won" if verdict == "won" else "paper_race_lost",
                metrics_delta={"excess_return_pct": 2.0 if verdict == "won" else -1.0},
                raw_evidence_ref=f"outcome:fo_api_{idx}",
                reflection_summary=f"Forward race verdict={verdict}",
                metadata={"verdict": verdict},
            )
        )
    # Hidden holdout episode must not leak into /api/memory cognitive_items
    memory.record_episode(
        EpisodicMemoryItemV1(
            mission_id="m-holdout",
            symbols=["ETH-USDT-SWAP"],
            timeframe="1H",
            market_regime="high_volatility",
            event_type="backtest_success",
            raw_evidence_ref="bt-holdout-secret",
            reflection_summary="SECRET_FINAL_HOLDOUT_SUMMARY",
            metadata={"recall_eligible": False},
        )
    )
    sync_cognitive_to_memory_items(db)

    # 1. Token empty -> live_probe is None without probing
    app_no_token = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            BITPRO_MCP_API_TOKEN="",
        ),
        db=db,
    )
    client_no_token = TestClient(app_no_token)
    overview_no_token = client_no_token.get("/api/harness/overview").json()
    assert overview_no_token["bitpro"]["live_probe"] is None
    assert overview_no_token["memory"]["active_count"] == 4
    assert overview_no_token["memory"]["total_count"] == 4
    assert overview_no_token["memory"]["latest_created_at"] is not None
    assert overview_no_token["memory"]["cognitive"] == {
        "episodic_count": 3,
        "semantic_count": 1,
        "active_semantic_count": 1,
        "hypothesis_count": 0,
    }

    mem_resp = client_no_token.get("/api/memory").json()
    assert len(mem_resp["items"]) == 4
    assert mem_resp["cognitive"] == overview_no_token["memory"]["cognitive"]
    assert any(item["tier"] == "semantic" for item in mem_resp["cognitive_items"])
    assert any(item["tier"] == "episodic" for item in mem_resp["cognitive_items"])
    assert all(
        "SECRET_FINAL_HOLDOUT_SUMMARY" not in str(item)
        for item in mem_resp["cognitive_items"]
    )

    filtered_mem = client_no_token.get("/api/memory?query=excess_return_pct").json()
    assert len(filtered_mem["items"]) >= 1
    assert any(item["tier"] == "semantic" for item in filtered_mem["cognitive_items"])

    # 2. Token configured + probe_connectivity present -> live_probe populated safely
    class ProbeAdapter:
        def probe_connectivity(self) -> dict[str, Any]:
            return {"reachable": True, "authenticated": True, "status": "ok", "latency_ms": 4.2}

    app_with_probe = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            BITPRO_MCP_API_TOKEN="secret-token",
        ),
        db=db,
        bitpro_adapter=ProbeAdapter(),  # type: ignore[arg-type]
    )
    overview_with_probe = TestClient(app_with_probe).get("/api/harness/overview").json()
    assert overview_with_probe["bitpro"]["live_probe"] == {
        "reachable": True,
        "authenticated": True,
        "status": "ok",
        "latency_ms": 4.2,
    }

    # 3. Failing probe never breaks /api/harness/overview
    class BrokenProbeAdapter:
        def probe_connectivity(self) -> dict[str, Any]:
            raise RuntimeError("bitpro unreachable")

    app_broken_probe = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            BITPRO_MCP_API_TOKEN="secret-token",
        ),
        db=db,
        bitpro_adapter=BrokenProbeAdapter(),  # type: ignore[arg-type]
    )
    broken_resp = TestClient(app_broken_probe).get("/api/harness/overview")
    assert broken_resp.status_code == 200
    assert broken_resp.json()["bitpro"]["live_probe"] is None
