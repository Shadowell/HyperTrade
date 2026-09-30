"""Comprehensive end-to-end integration test for the autonomous trading agent.

Validates the full perception-cognition-execution-evolution loop:
1. Real-time news ingestion and sentiment scoring.
2. Market perception snapshot synthesis (funding, OI, news sentiment).
3. Bounded autonomous execution under hardware circuit breakers.
4. Freeform strategy synthesis and AST sandbox dry-run execution.
5. Dual-track evolution compatibility with existing BitPro strategies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from hypertrade.agent.kernel import AgentKernel
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.live.service import AutonomousExecutionManager
from hypertrade.market.news import InMemoryNewsFeed, NewsArticle, NewsIngestionService
from hypertrade.market.repository import MarketRepository
from hypertrade.market.sentiment import NewsSentimentAnalyzer
from hypertrade.research.synthesis import FreeformStrategySynthesizer
from hypertrade.risk.service import AutonomousCircuitBreaker, RiskEngine


class MockDirectExchangeClient:
    def __init__(self) -> None:
        self.placed_orders: list[dict[str, str]] = []

    def place_order(
        self,
        *,
        inst_id: str,
        side: str,
        order_type: str,
        size: str,
        price: str | None = None,
    ) -> dict[str, Any]:
        order = {
            "ordId": f"auto_{len(self.placed_orders) + 1}",
            "instId": inst_id,
            "side": side,
            "orderType": order_type,
            "sz": size,
            "px": price or "0",
        }
        self.placed_orders.append(order)
        return {"code": "0", "data": [order]}


def test_autonomous_trading_agent_full_loop() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    # Step 1: Market data setup
    market_repo = MarketRepository(db)
    market_repo.upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal(65000),
        volume_ccy_24h=Decimal(50000000),
        change_utc0_pct=Decimal("3.5"),
    )

    # Step 2: News Ingestion & Sentiment Analysis
    now_utc = datetime.now(UTC)
    news_feed = InMemoryNewsFeed(
        initial_articles=[
            NewsArticle.create(
                title="Institutional inflows surge as BTC breaks resistance",
                content="Spot ETF inflows hit record highs with massive spot accumulation.",
                source="CoinDesk",
                published_at=now_utc,
                symbols=["BTC"],
            ),
            NewsArticle.create(
                title="Major protocol upgrade activates smoothly",
                content="Network efficiency improved with zero downtime reported.",
                source="CoinTelegraph",
                published_at=now_utc,
                symbols=["ETH", "BTC"],
            ),
        ]
    )
    news_service = NewsIngestionService(sources=[news_feed])
    news_service.sync_sources()
    articles = news_service.get_latest(symbol="BTC", limit=5)
    assert len(articles) == 2

    analyzer = NewsSentimentAnalyzer()
    parsed_sentiments = analyzer.analyze_batch(articles)
    sentiment = analyzer.aggregate_symbol_sentiment("BTC", parsed_sentiments)
    assert sentiment["sentiment_score"] > 0.0
    assert sentiment["label"] == "bullish"

    # Step 3: Perception Snapshot via Agent Kernel
    settings = Settings(
        OKX_TESTNET=True,
        AUTONOMOUS_TRADING_ENABLED=True,
        AUTONOMOUS_MAX_DAILY_LOSS_PCT="3.0",
        RISK_MAX_ORDER_NOTIONAL_USDT="20000",
    )
    kernel = AgentKernel(db, settings=settings)

    # Dispatch perception snapshot tool
    perception = kernel._dispatch_tool(
        "market_perception_snapshot",
        {"symbol": "BTC-USDT-SWAP", "limit_news": 5},
        run_id="run_e2e_001",
        policy=kernel.tools.get("market.perception_snapshot").policy,
    )
    assert perception["symbol"] == "BTC-USDT-SWAP"
    assert "news_and_sentiment" in perception

    # Step 4: Autonomous Order Execution under Circuit Breaker
    mock_client = MockDirectExchangeClient()
    circuit_breaker = AutonomousCircuitBreaker(max_daily_loss_pct=Decimal("3.0"))
    risk_engine = RiskEngine(
        db,
        settings=settings,
        circuit_breaker=circuit_breaker,
    )
    exec_manager = AutonomousExecutionManager(
        db,
        settings=settings,
        risk_engine=risk_engine,
        client=mock_client,
    )

    # Order 1: Within limits -> Successfully executes without human intervention
    order_result = exec_manager.execute_order(
        symbol="BTC-USDT-SWAP",
        side="buy",
        size="0.05",
        order_type="market",
        reason="Autonomous momentum signal supported by positive news sentiment",
        autonomous_override=True,
    )
    assert order_result["executed"] is True
    assert order_result["status"] == "executed_autonomous"
    assert len(mock_client.placed_orders) == 1

    # Order 2: Drawdown breach -> Hardware Circuit Breaker trips & blocks execution
    blocked_result = exec_manager.execute_order(
        symbol="BTC-USDT-SWAP",
        side="buy",
        size="0.05",
        order_type="market",
        reason="Chasing breakout",
        daily_loss_pct=Decimal("3.5"),  # Exceeds 3.0% limit
        autonomous_override=True,
    )
    assert blocked_result["executed"] is False
    assert blocked_result["status"] == "risk_blocked"
    assert circuit_breaker.is_tripped is True
    assert len(mock_client.placed_orders) == 1  # No additional order sent to exchange

    # Step 5: Freeform Strategy Synthesis & Sandbox Verification
    custom_strategy_code = (
        "from app.core.execution.base_strategy import BaseStrategy\n"
        "\n"
        "\n"
        "class SentimentMomentumAlpha(BaseStrategy):\n"
        '    """Autonomous sentiment-guided momentum breakout."""\n'
        "\n"
        "    async def on_init(self):\n"
        "        self.p_lookback = 20\n"
        "        self.p_sentiment_threshold = 0.2\n"
        "\n"
        "    async def on_bar(self, bar: BarData):\n"
        "        if bar.close_price > 60200.0:\n"
        '            await self.open_contract("BTC-USDT-SWAP", "long", 0.05)\n'
        "        return None\n"
    )
    synthesizer = FreeformStrategySynthesizer()
    synthesis_result = synthesizer.synthesize(custom_code=custom_strategy_code)

    assert synthesis_result.is_freeform is True
    assert synthesis_result.validation.is_valid is True
    assert synthesis_result.smoke_test.passed is True
    assert synthesis_result.smoke_test.bars_processed == 10
    assert synthesis_result.smoke_test.orders_simulated > 0
    assert "lookback" in synthesis_result.tunable_parameters

    # Step 6: Dual-Track Compatibility Check (Template family spec)
    template_spec = {
        "schema_version": "research_strategy_spec.v1",
        "mandate_id": "rman_e2e",
        "strategy_key": "e2e_crossover_candidate",
        "title": "E2E Template Crossover",
        "hypothesis": "crossover of fast moving average over slow moving average",
        "symbols": ["BTC"],
        "timeframes": ["1H"],
        "strategy_category": "TREND",
        "entry_logic": "golden cross forms",
        "exit_logic": "death cross forms",
        "risk_conditions": ["bounded notional"],
        "data_requirements": ["ohlcv"],
        "parameter_bounds": {},
        "invalidation_conditions": ["insufficient data"],
    }
    template_result = synthesizer.synthesize(spec=template_spec)
    assert template_result.is_freeform is False
    assert template_result.validation.is_valid is True
    assert template_result.smoke_test.passed is True
