from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.live.service import AutonomousExecutionManager
from hypertrade.market.repository import MarketRepository
from hypertrade.risk.service import AutonomousCircuitBreaker, RiskEngine


class MockExchangeClient:
    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []

    def place_order(
        self,
        *,
        inst_id: str,
        side: str,
        order_type: str,
        size: str,
        price: str | None = None,
    ) -> dict[str, Any]:
        order: dict[str, Any] = {
            "ordId": f"mock_ord_{len(self.orders) + 1}",
            "instId": inst_id,
            "side": side,
            "orderType": order_type,
            "sz": size,
            "px": price or "0",
        }
        self.orders.append(order)
        return {"code": "0", "data": [order]}


def test_autonomous_circuit_breaker_tripping() -> None:
    cb = AutonomousCircuitBreaker(max_daily_loss_pct=Decimal("3.0"))
    assert not cb.is_tripped

    # 2.5% loss is fine
    assert cb.check_daily_pnl(Decimal("2.5"))
    assert not cb.is_tripped

    # 3.2% loss trips breaker
    assert not cb.check_daily_pnl(Decimal("3.2"))
    assert cb.is_tripped
    assert "exceeded max" in cb.trip_reason

    # Reset
    cb.reset()
    assert not cb.is_tripped


def test_autonomous_execution_manager_direct_execution() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    mock_client = MockExchangeClient()

    settings = Settings(
        OKX_TESTNET=True,
        AUTONOMOUS_TRADING_ENABLED=True,
        RISK_MAX_ORDER_NOTIONAL_USDT="5000",
    )
    manager = AutonomousExecutionManager(db, settings=settings, client=mock_client)

    result = manager.execute_order(
        symbol="BTC-USDT-SWAP",
        side="buy",
        size="0.05",
        order_type="market",
        reason="momentum breakout signal",
        autonomous_override=True,
    )

    assert result["executed"] is True
    assert result["status"] == "executed_autonomous"
    assert result["exchange_order_id"].startswith("mock_ord_")
    assert result["decision_reason"] == "autonomous_risk_guard_approved"
    assert len(mock_client.orders) == 1
    assert mock_client.orders[0]["instId"] == "BTC-USDT-SWAP"


def test_autonomous_execution_manager_blocked_by_circuit_breaker() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    mock_client = MockExchangeClient()

    settings = Settings(
        OKX_TESTNET=True,
        AUTONOMOUS_TRADING_ENABLED=True,
        AUTONOMOUS_MAX_DAILY_LOSS_PCT="2.0",
    )
    cb = AutonomousCircuitBreaker(max_daily_loss_pct=Decimal("2.0"))
    risk_engine = RiskEngine(db, settings=settings, circuit_breaker=cb)
    manager = AutonomousExecutionManager(
        db, settings=settings, risk_engine=risk_engine, client=mock_client
    )

    # Place order with daily loss 2.5% (exceeds 2.0% limit)
    result = manager.execute_order(
        symbol="BTC-USDT-SWAP",
        side="buy",
        size="0.05",
        order_type="market",
        daily_loss_pct=Decimal("2.5"),
        autonomous_override=True,
    )

    assert result["executed"] is False
    assert result["status"] == "risk_blocked"
    assert any("daily loss limit breached" in r for r in result["block_reasons"])
    assert len(mock_client.orders) == 0


def test_autonomous_execution_manager_blocked_by_notional() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal(60000),
        volume_ccy_24h=Decimal(1000),
        change_utc0_pct=Decimal(0),
    )
    mock_client = MockExchangeClient()

    settings = Settings(
        OKX_TESTNET=True,
        AUTONOMOUS_TRADING_ENABLED=True,
        RISK_MAX_ORDER_NOTIONAL_USDT="500",  # $500 max
    )
    manager = AutonomousExecutionManager(db, settings=settings, client=mock_client)

    # 0.1 BTC at 60,000 is $6,000 -> exceeds $500 limit
    result = manager.execute_order(
        symbol="BTC-USDT-SWAP",
        side="buy",
        size="0.1",
        order_type="market",
        autonomous_override=True,
    )

    assert result["executed"] is False
    assert result["status"] == "risk_blocked"
    assert any("order notional exceeds limit" in r for r in result["block_reasons"])
    assert len(mock_client.orders) == 0


def test_agent_kernel_autonomous_tools() -> None:
    from hypertrade.agent.kernel import AgentKernel

    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal(60000),
        volume_ccy_24h=Decimal(1000),
        change_utc0_pct=Decimal(0),
    )
    settings = Settings(
        OKX_TESTNET=True,
        AUTONOMOUS_TRADING_ENABLED=True,
        RISK_MAX_ORDER_NOTIONAL_USDT="10000",
    )
    kernel = AgentKernel(db, settings=settings)

    # 1. Test market_news_stream
    news_res = kernel._dispatch_tool(
        "market_news_stream",
        {"symbol": "BTC", "limit": 5},
        run_id="run_test",
        policy=kernel.tools.get("market.news_stream").policy,
    )
    assert "articles" in news_res
    assert isinstance(news_res["articles"], list)

    # 2. Test market_perception_snapshot
    perc_res = kernel._dispatch_tool(
        "market_perception_snapshot",
        {"symbol": "BTC-USDT-SWAP", "limit_news": 5},
        run_id="run_test",
        policy=kernel.tools.get("market.perception_snapshot").policy,
    )
    assert perc_res["symbol"] == "BTC-USDT-SWAP"
    assert "news_and_sentiment" in perc_res
    assert "aggregated" in perc_res["news_and_sentiment"]

    # 3. Test live_autonomous_order
    order_res = kernel._dispatch_tool(
        "live_autonomous_order",
        {
            "symbol": "BTC-USDT-SWAP",
            "side": "buy",
            "size": "0.01",
            "order_type": "market",
            "reason": "kernel integration test",
        },
        run_id="run_test",
        policy=kernel.tools.get("live.autonomous_order").policy,
    )
    assert "id" in order_res
    assert order_res["source"] == "autonomous_agent"

