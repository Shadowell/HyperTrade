from hypertrade.agent.kernel import AgentKernel
from hypertrade.agent.planner import ToolCallRecord
from hypertrade.config import Settings
from hypertrade.db import Database


def test_market_compare_payload_ranks_symbols_by_strength(monkeypatch, tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="", DATABASE_URL="sqlite:///:memory:"),
        knowledge_dir=str(tmp_path),
    )

    summaries = {
        "ETH": {
            "inst_id": "ETH-USDT-SWAP",
            "bar": "4H",
            "found": True,
            "return_pct": "2.500000",
            "close_position_pct": "70.000000",
            "trend_bias": "up",
            "ma20": "2010.000000000000",
            "ma60": "1990.000000000000",
            "data_source": "okx_rest",
        },
        "SOL": {
            "inst_id": "SOL-USDT-SWAP",
            "bar": "4H",
            "found": True,
            "return_pct": "-3.000000",
            "close_position_pct": "25.000000",
            "trend_bias": "down",
            "ma20": "82.000000000000",
            "ma60": "84.000000000000",
            "data_source": "okx_rest",
        },
    }

    def fake_candles_payload(*, symbol: str, bar: str, limit: int):
        assert bar == "4H"
        assert limit == 100
        return summaries[symbol.upper()]

    monkeypatch.setattr(kernel, "_market_candles_payload", fake_candles_payload)

    payload = kernel._market_compare_payload(symbols=["eth", "SOL"], bar="4h", limit=100)

    assert payload["found"] is True
    assert payload["bar"] == "4H"
    assert [row["inst_id"] for row in payload["rankings"]] == [
        "ETH-USDT-SWAP",
        "SOL-USDT-SWAP",
    ]
    assert payload["rankings"][0]["strength_score"] > payload["rankings"][1]["strength_score"]
    assert payload["leader"] == "ETH-USDT-SWAP"


def test_planner_report_includes_market_compare_rankings() -> None:
    report = AgentKernel._render_planner_report(
        "ETH 相对更强。\n\nResearch output only. Not investment advice.",
        [
            ToolCallRecord(
                tool_name="market_compare",
                input_json={"symbols": ["ETH", "SOL"], "bar": "4H", "limit": 100},
                output_json={
                    "found": True,
                    "bar": "4H",
                    "leader": "ETH-USDT-SWAP",
                    "rankings": [
                        {
                            "rank": 1,
                            "inst_id": "ETH-USDT-SWAP",
                            "strength_score": "75.000000",
                            "return_pct": "2.500000",
                            "close_position_pct": "70.000000",
                            "trend_bias": "up",
                        },
                        {
                            "rank": 2,
                            "inst_id": "SOL-USDT-SWAP",
                            "strength_score": "20.000000",
                            "return_pct": "-3.000000",
                            "close_position_pct": "25.000000",
                            "trend_bias": "down",
                        },
                    ],
                },
            )
        ],
    )

    assert "## 多标的强弱比较" in report
    assert "周期: 4H" in report
    assert "领先标的: ETH-USDT-SWAP" in report
    assert "1. ETH-USDT-SWAP: 强弱分 75.000000" in report
    assert "2. SOL-USDT-SWAP: 强弱分 20.000000" in report
