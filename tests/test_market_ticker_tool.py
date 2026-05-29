from decimal import Decimal

from hypertrade.agent.kernel import AgentKernel, _normalize_swap_inst_id
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
