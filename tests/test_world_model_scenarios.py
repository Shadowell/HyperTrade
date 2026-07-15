from __future__ import annotations

from decimal import Decimal

from hypertrade.agent.planner import ToolCallRecord
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository
from hypertrade.reporting.blocks import build_report_blocks_from_tool_calls, render_report_blocks
from hypertrade.world_model.service import WorldModelService


def _settings() -> Settings:
    return Settings(
        DEEPSEEK_API_KEY="test-key",
        OKX_REST_URL="http://127.0.0.1:9",
    )


def _seed_market(db: Database) -> None:
    repository = MarketRepository(db)
    repository.upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("2000000"),
        change_utc0_pct=Decimal("-3.5"),
    )
    repository.upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("3500"),
        volume_ccy_24h=Decimal("1200000"),
        change_utc0_pct=Decimal("-2.8"),
    )


def _snapshot() -> dict[str, object]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)
    return WorldModelService(
        db,
        settings=_settings(),
        global_market_collector=lambda: {
            "risk_regime": "risk_off",
            "volatility_regime": "elevated",
            "dollar_pressure": "neutral",
            "rates_pressure": "neutral",
            "cross_asset_signal": "defensive",
            "tickers": [],
            "missing_data": ["^GSPC"],
            "as_of": "2026-07-15T00:00:00+00:00",
        },
    ).snapshot()


def test_world_model_snapshot_includes_deterministic_scenarios_and_decision() -> None:
    snapshot = _snapshot()

    scenarios = snapshot["action_scenarios"]
    assert isinstance(scenarios, list)
    scenario_ids = {scenario["action_id"] for scenario in scenarios}
    assert {
        "observe_more",
        "hold",
        "run_monitor",
        "inspect_trace",
        "request_human_confirmation",
        "pause_strategy_request",
        "reduce_risk_request",
    } <= scenario_ids
    for scenario in scenarios:
        assert {
            "action_id",
            "action_level",
            "expected_benefit",
            "downside",
            "affected_state_domains",
            "confidence",
            "data_gap_penalty",
            "reversibility",
            "execution_complexity",
            "policy_result",
            "policy_status",
            "requires_human_confirmation",
            "review_after",
            "expected_follow_up_evidence",
            "score",
            "rank",
            "source_refs",
        } <= set(scenario)
        assert scenario["policy_status"] in {
            "allowed_read_only",
            "requires_human_confirmation",
            "blocked_risk_increasing_until_confirmed",
        }
        assert scenario["source_refs"]

    decision = snapshot["decision"]
    assert isinstance(decision, dict)
    assert decision["decision_id"].startswith("wmdec_")
    assert decision["selected_action_id"] == scenarios[0]["action_id"]
    assert decision["policy_status"] == scenarios[0]["policy_status"]
    assert decision["review_after"]
    assert decision["expected_follow_up_evidence"]
    assert decision["world_state_hash"]


def test_scenario_scoring_is_deterministic_and_avoids_risk_increase_on_data_gaps() -> None:
    first = _snapshot()
    second = _snapshot()

    first_scores = [
        (
            scenario["action_id"],
            scenario["score"],
            scenario["policy_status"],
            scenario["data_gap_penalty"],
        )
        for scenario in first["action_scenarios"]
    ]
    second_scores = [
        (
            scenario["action_id"],
            scenario["score"],
            scenario["policy_status"],
            scenario["data_gap_penalty"],
        )
        for scenario in second["action_scenarios"]
    ]
    assert first_scores == second_scores
    assert first["decision"]["selected_action_id"] in {
        "observe_more",
        "request_human_confirmation",
    }
    assert first["decision"]["policy_status"] != "blocked_risk_increasing_until_confirmed"


def test_world_model_report_blocks_show_scenario_comparison_and_policy_status() -> None:
    snapshot = _snapshot()
    blocks = build_report_blocks_from_tool_calls(
        "全局世界模型已生成。",
        [ToolCallRecord(tool_name="world_model_snapshot", input_json={}, output_json=snapshot)],
    )
    titles = {block.title for block in blocks}
    assert "Global WorldState Scenario Comparison" in titles
    assert "Global WorldState Decision" in titles

    rendered = render_report_blocks(blocks, audit=False)
    assert "policy_status" in rendered
    assert "selected_action_id" in rendered
    assert "review_after" in rendered
