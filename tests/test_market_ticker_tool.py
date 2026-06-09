from decimal import Decimal

from hypertrade.agent.kernel import AgentKernel, _normalize_swap_inst_id
from hypertrade.agent.planner import ToolCallRecord
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository


def test_normalize_swap_inst_id_accepts_common_symbol_forms() -> None:
    assert _normalize_swap_inst_id("btc") == "BTC-USDT-SWAP"
    assert _normalize_swap_inst_id("BTC-USDT") == "BTC-USDT-SWAP"
    assert _normalize_swap_inst_id("btc/usdt") == "BTC-USDT-SWAP"
    assert _normalize_swap_inst_id("BTC-USDT-SWAP") == "BTC-USDT-SWAP"


def test_normalize_swap_inst_id_supports_any_okx_swap_symbol() -> None:
    assert _normalize_swap_inst_id("eth") == "ETH-USDT-SWAP"
    assert _normalize_swap_inst_id("SOL-USDT") == "SOL-USDT-SWAP"
    assert _normalize_swap_inst_id("doge_usdt") == "DOGE-USDT-SWAP"
    assert _normalize_swap_inst_id("BTC-USD") == "BTC-USD-SWAP"
    assert _normalize_swap_inst_id("ETH-USDC") == "ETH-USDC-SWAP"
    assert _normalize_swap_inst_id("PEPE-USDT-SWAP") == "PEPE-USDT-SWAP"


def test_market_ticker_payload_returns_exact_requested_symbol_from_db(
    monkeypatch,
    tmp_path,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="DOGE-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("0.2"),
        volume_ccy_24h=Decimal("120000"),
        change_utc0_pct=Decimal("-1.5"),
    )
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="", DATABASE_URL="sqlite:///:memory:"),
        knowledge_dir=str(tmp_path),
    )
    monkeypatch.setattr(kernel, "_refresh_market_snapshot", lambda: ("unavailable", "offline"))

    payload = kernel._market_ticker_payload("doge")

    assert payload["found"] is True
    assert payload["inst_id"] == "DOGE-USDT-SWAP"
    assert payload["last"] == "0.200000000000"
    assert payload["data_source"] == "db_fallback"


def test_planner_report_includes_specific_ticker_values() -> None:
    report = AgentKernel._render_planner_report(
        "已完成查询。",
        [
            ToolCallRecord(
                tool_name="market_ticker",
                input_json={"symbol": "ETH"},
                output_json={
                    "inst_id": "ETH-USDT-SWAP",
                    "found": True,
                    "last": "3500.000000000000",
                    "change_utc0_pct": "1.230000000000",
                    "volume_ccy_24h": "987654.000000000000",
                    "data_source": "okx_rest",
                    "as_of_utc": "2026-05-29T08:00:00+00:00",
                },
            )
        ],
    )

    assert "## 单标的行情" in report
    assert "ETH-USDT-SWAP" in report
    assert "最新价 3500.000000000000" in report
    assert "Research output only. Not investment advice." not in report
