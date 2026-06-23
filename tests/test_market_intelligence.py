from __future__ import annotations

from hypertrade.agent.kernel import AgentKernel
from hypertrade.agent.planner import ToolCallRecord
from hypertrade.market.intelligence import MarketIntelligenceService


class ReplayIntelligenceClient:
    async def fetch_funding_rate(self, *, inst_id: str) -> dict[str, object]:
        assert inst_id == "ETH-USDT-SWAP"
        return {
            "fundingRate": "0.000125",
            "nextFundingRate": "0.000140",
            "fundingTime": "1782158400000",
        }

    async def fetch_open_interest(self, *, inst_id: str) -> dict[str, object]:
        assert inst_id == "ETH-USDT-SWAP"
        return {
            "instId": "ETH-USDT-SWAP",
            "oi": "12345.67",
            "oiCcy": "54321.0",
            "ts": "1782157500000",
        }


def test_market_intelligence_service_returns_provenance_for_okx_and_curated_sources() -> None:
    service = MarketIntelligenceService(okx_client=ReplayIntelligenceClient())

    payload = service.collect(symbol="ETH")

    assert payload["symbol"] == "ETH"
    assert payload["inst_id"] == "ETH-USDT-SWAP"
    assert payload["source_count"] == 2
    assert [item["source"] for item in payload["results"]] == [
        "okx_public.funding_open_interest",
        "curated.market_context",
    ]
    okx = payload["results"][0]
    assert okx["source_path"] == "/api/v5/public/funding-rate + /api/v5/public/open-interest"
    assert okx["metrics"] == {
        "funding_rate": "0.000125",
        "next_funding_rate": "0.000140",
        "open_interest_contracts": "12345.67",
        "open_interest_ccy": "54321.0",
    }
    assert okx["missing_fields"] == []
    assert okx["freshness_seconds"] >= 0
    assert okx["as_of"].startswith("2026-06-22")
    curated = payload["results"][1]
    assert curated["source_path"] == "docs/knowledge/market-intelligence-curated.md"
    assert "funding/open-interest context" in curated["sample"][0]


def test_market_intelligence_service_reports_missing_fields_without_inventing_data() -> None:
    class MissingOpenInterestClient(ReplayIntelligenceClient):
        async def fetch_open_interest(self, *, inst_id: str) -> dict[str, object]:
            return {"instId": inst_id}

    service = MarketIntelligenceService(okx_client=MissingOpenInterestClient())

    payload = service.collect(symbol="ETH")

    okx = payload["results"][0]
    assert "open_interest_contracts" in okx["missing_fields"]
    assert "open_interest_ccy" in okx["missing_fields"]
    assert okx["metrics"]["funding_rate"] == "0.000125"
    assert "open_interest_contracts" not in okx["metrics"]


def test_planner_report_renders_market_intelligence_evidence() -> None:
    report = AgentKernel._render_planner_report(
        "资金费率和持仓情报已读取。",
        [
            ToolCallRecord(
                tool_name="market_intelligence",
                input_json={"symbol": "ETH"},
                output_json={
                    "symbol": "ETH",
                    "inst_id": "ETH-USDT-SWAP",
                    "source_count": 2,
                    "results": [
                        {
                            "source": "okx_public.funding_open_interest",
                            "source_path": (
                                "/api/v5/public/funding-rate + "
                                "/api/v5/public/open-interest"
                            ),
                            "symbol": "ETH-USDT-SWAP",
                            "as_of": "2026-06-22T14:25:00+00:00",
                            "freshness_seconds": 3600,
                            "metrics": {
                                "funding_rate": "0.000125",
                                "next_funding_rate": "0.000140",
                                "open_interest_contracts": "12345.67",
                            },
                            "missing_fields": ["open_interest_ccy"],
                            "sample": ["funding_rate=0.000125"],
                        }
                    ],
                },
            )
        ],
    )

    assert "## 市场情报" in report
    assert "标的: ETH-USDT-SWAP" in report
    assert "来源: okx_public.funding_open_interest" in report
    assert "source_path: /api/v5/public/funding-rate + /api/v5/public/open-interest" in report
    assert "funding_rate=0.000125" in report
    assert "open_interest_contracts=12345.67" in report
    assert "缺失字段: open_interest_ccy" in report
    assert "资金费率和持仓情报已读取。" in report
