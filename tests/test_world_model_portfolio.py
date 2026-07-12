from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.agent.planner import _SYSTEM_PROMPT, TOOL_SCHEMAS, ToolCallRecord
from hypertrade.config import Settings
from hypertrade.db import (
    Database,
    MemoryItem,
    PaperPromotion,
    ResearchExperimentEvidence,
    ResearchMandate,
)
from hypertrade.main import create_app
from hypertrade.market.repository import MarketRepository
from hypertrade.reporting.blocks import build_report_blocks_from_tool_calls, render_report_blocks
from hypertrade.world_model.service import WorldModelService


def _settings() -> Settings:
    return Settings(
        DEEPSEEK_API_KEY="test-key",
        OKX_REST_URL="http://127.0.0.1:9",
    )


def _seed_market(db: Database) -> None:
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("2000000"),
        change_utc0_pct=Decimal("-1.2"),
    )


def _seed_strategy_memory(db: Database) -> None:
    with db.session() as session:
        session.add(
            MemoryItem(
                kind="strategy_knowledge",
                content=(
                    "experiment=strategy=momentum_breakout_v1;passed=true\n"
                    "metrics=total_return_pct=12.5;max_drawdown_pct=3.2;score=8.1"
                ),
                source_tool="strategy.experiment",
                tags=[
                    "strategy",
                    "strategy:momentum_breakout_v1",
                    "winner:fast",
                ],
            )
        )


def test_world_model_snapshot_includes_portfolio_scheduler_view() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)
    _seed_strategy_memory(db)

    snapshot = WorldModelService(db, settings=_settings()).snapshot()

    portfolio = snapshot["portfolio"]
    assert portfolio["schema_version"] == "portfolio_state.v1"
    assert set(portfolio) >= {
        "portfolio_state",
        "recommendations",
        "decision",
        "missing_evidence",
        "source_refs",
    }
    strategies = portfolio["portfolio_state"]["strategies"]
    assert strategies[0]["strategy_group"] == "momentum_breakout_v1"
    assert strategies[0]["evidence_freshness"] in {"fresh", "stale", "unknown"}
    assert strategies[0]["regime_fit"] in {"favorable", "neutral", "defensive", "unknown"}
    assert portfolio["portfolio_state"]["correlation_proxy"]["status"] in {
        "single_strategy",
        "insufficient_data",
        "shared_exposure_warning",
    }
    assert portfolio["decision"]["recommendation_type"] in {
        "keep_allocation",
        "increase_observation_frequency",
        "run_targeted_backtest_or_experiment",
        "request_human_review_before_allocation_change",
    }
    assert not any(
        recommendation["recommendation_type"] == "increase_allocation"
        for recommendation in portfolio["recommendations"]
    )


def test_portfolio_scheduler_refuses_allocation_advice_when_evidence_is_missing() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)

    portfolio = WorldModelService(db, settings=_settings()).snapshot()["portfolio"]

    assert "portfolio.strategy_evidence_unavailable" in portfolio["missing_evidence"]
    assert portfolio["decision"]["allocation_change_allowed"] is False
    assert portfolio["decision"]["recommendation_type"] in {
        "increase_observation_frequency",
        "request_human_review_before_allocation_change",
        "run_targeted_backtest_or_experiment",
    }


def test_portfolio_endpoint_and_report_blocks_explain_source_bound_recommendations() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)
    _seed_strategy_memory(db)
    client = TestClient(create_app(settings=_settings(), db=db))

    response = client.get("/api/world-model/portfolio")

    assert response.status_code == 200
    portfolio = response.json()
    assert portfolio["schema_version"] == "portfolio_state.v1"
    assert portfolio["source_refs"]

    snapshot = WorldModelService(db, settings=_settings()).snapshot()
    blocks = build_report_blocks_from_tool_calls(
        "组合调度已生成。",
        [ToolCallRecord(tool_name="world_model_snapshot", input_json={}, output_json=snapshot)],
    )
    titles = {block.title for block in blocks}
    assert "Global Portfolio Risk" in titles
    assert "Global Portfolio Recommended Actions" in titles
    rendered = render_report_blocks(blocks, audit=False)
    assert "recommendation_type" in rendered
    assert "regime_fit" in rendered


def test_planner_guides_portfolio_prompts_to_world_model() -> None:
    schema = next(
        item for item in TOOL_SCHEMAS if item["function"]["name"] == "world_model_snapshot"
    )
    assert "portfolio" in schema["function"]["description"]
    assert "策略权重" in _SYSTEM_PROMPT
    assert "portfolio" in _SYSTEM_PROMPT


def test_portfolio_uses_strategy_card_and_requests_review_without_writes() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)
    with db.session() as session:
        mandate = ResearchMandate(
            name="portfolio",
            status="active",
            market_type="SWAP",
            symbols_json=["BTC"],
            timeframes_json=["1H"],
            strategy_categories_json=["TREND"],
            budget_json={},
            validation_json={},
            paper_promotion_mode="manual_approval",
            live_mode="disabled",
            audit_json=[],
        )
        session.add(mandate)
        session.flush()
        evidence = ResearchExperimentEvidence(
            job_id="rjob_portfolio",
            mandate_id=mandate.id,
            variant_id="base",
            status="evidence_recorded",
            strategy_key="btc",
            bitpro_strategy_id="42",
            result_refs_json={},
            windows_json={},
            parameters_json={},
            metrics_json={},
            gate_results_json={"oos": True},
            rejection_reasons_json=[],
            tool_calls_json=[],
        )
        session.add(evidence)
        session.flush()
        session.add(
            PaperPromotion(
                mandate_id=mandate.id,
                job_id=evidence.job_id,
                evidence_id=evidence.id,
                strategy_key="btc",
                bitpro_strategy_id="42",
                status="paper_review_required",
                request_reason="review",
                approval_reason="approved",
                approval_idempotency_key="portfolio-key",
                approved_by="admin",
                paper_refs_json={},
                observation_json={"drift": {"data_gaps": [], "alerts": [{"code": "equity_drop"}]}},
                transition_json=[],
            )
        )

    portfolio = WorldModelService(db, settings=_settings()).snapshot()["portfolio"]

    assert portfolio["portfolio_state"]["strategies"][0]["card_id"].startswith("scard_")
    assert any(
        row["recommendation_type"] == "request_pause_review" for row in portfolio["recommendations"]
    )
    assert all(row["allocation_change_allowed"] is False for row in portfolio["recommendations"])
