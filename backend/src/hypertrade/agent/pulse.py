"""Autonomous Market Pulse & Live Perception Daemon.

Continuously surveys target symbols across price action, funding rates, open
interest, and live news perception. Evaluates market catalysts with heuristic
screening and LLM reasoning, executing autonomous trading actions within
strict risk guardrails and logging auditable pulse cycles.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import desc, select

from hypertrade.config import Settings, get_settings
from hypertrade.db import AutonomousPulseCycle, Database, MarketTicker
from hypertrade.live.service import AutonomousExecutionManager
from hypertrade.market.intelligence import MarketIntelligenceService, normalize_swap_inst_id
from hypertrade.market.news import NewsIngestionService, build_default_news_service
from hypertrade.market.repository import MarketRepository
from hypertrade.providers.chat import ChatProvider

logger = logging.getLogger(__name__)


def _cycle_to_dict(cycle: AutonomousPulseCycle) -> dict[str, Any]:
    return {
        "id": cycle.id,
        "trigger": cycle.trigger,
        "status": cycle.status,
        "symbols": cycle.symbols,
        "sentiment_summary": cycle.sentiment_summary,
        "decisions": cycle.decisions_json,
        "orders_executed": cycle.orders_executed,
        "error_message": cycle.error_message,
        "duration_ms": cycle.duration_ms,
        "created_at": cycle.created_at.isoformat() if cycle.created_at else None,
        "updated_at": cycle.updated_at.isoformat() if cycle.updated_at else None,
    }


class AutonomousMarketPulseService:
    """Surveys target symbols and executes governed autonomous trading pulses."""

    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        chat_provider: ChatProvider | None = None,
        news_service: NewsIngestionService | None = None,
        execution_manager: AutonomousExecutionManager | None = None,
        market_repo: MarketRepository | None = None,
        intelligence_service: MarketIntelligenceService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.chat_provider = chat_provider
        self.news_service = news_service or build_default_news_service(
            cryptopanic_key=self.settings.cryptopanic_api_key,
            enable_external=self.settings.enable_external_news_feed,
        )
        self.execution_manager = execution_manager or AutonomousExecutionManager(
            db, settings=self.settings
        )
        self.market_repo = market_repo or MarketRepository(db)
        self.intelligence_service = intelligence_service or MarketIntelligenceService(
            settings=self.settings,
            news_service=self.news_service,
        )

    def run_pulse_once(
        self,
        *,
        trigger: str = "scheduled",
        dry_run: bool = False,
        symbols: list[str] | None = None,
        autonomous_override: bool = False,
    ) -> dict[str, Any]:
        """Execute one complete market pulse cycle across target symbols."""
        started_at = time.monotonic()
        target_symbols = self._resolve_target_symbols(symbols)

        # 1. Ingest/sync latest live news feeds
        try:
            self.news_service.sync_sources()
        except Exception as exc:
            logger.warning("Pulse: news sync encountered error: %s", exc)

        decisions: list[dict[str, Any]] = []
        orders_executed: list[dict[str, Any]] = []
        sentiment_summary: dict[str, Any] = {}

        # 2. Evaluate each symbol
        for symbol in target_symbols:
            inst_id = normalize_swap_inst_id(symbol)
            try:
                perception = self.intelligence_service.collect_perception(
                    symbol=inst_id, include_news=True, limit_news=5
                )
                if not sentiment_summary:
                    sentiment_summary = perception.get("news_and_sentiment", {}).get(
                        "aggregated", {}
                    )

                ticker_data = self._get_symbol_ticker(inst_id)
                decision = self._evaluate_symbol_decision(
                    inst_id=inst_id,
                    ticker=ticker_data,
                    perception=perception,
                )
                decisions.append(decision)

                # 3. Execution if conviction is high and action is tradeable
                action = decision.get("action", "hold")
                confidence = float(decision.get("confidence", 0.0))
                min_conviction = float(self.settings.autonomous_pulse_min_conviction)

                if action in {"buy", "sell"} and confidence >= min_conviction:
                    if not dry_run and (
                        self.settings.autonomous_trading_enabled or autonomous_override
                    ):
                        order_size = str(decision.get("suggested_size", "1"))
                        exec_res = self.execution_manager.execute_order(
                            symbol=inst_id,
                            side=action,
                            size=order_size,
                            order_type="market",
                            reason=f"pulse_{trigger}:{decision.get('reason', '')[:100]}",
                            autonomous_override=autonomous_override,
                        )
                        orders_executed.append(exec_res)
                    else:
                        orders_executed.append(
                            {
                                "inst_id": inst_id,
                                "side": action,
                                "status": "simulated_dry_run" if dry_run else "autonomous_disabled",
                                "executed": False,
                                "decision": decision,
                            }
                        )

            except Exception as exc:
                logger.exception("Error evaluating pulse for symbol %s: %s", inst_id, exc)
                decisions.append(
                    {
                        "symbol": inst_id,
                        "action": "hold",
                        "confidence": 0.0,
                        "reason": f"evaluation_error: {str(exc)[:150]}",
                    }
                )

        duration_ms = int((time.monotonic() - started_at) * 1000)

        # 4. Persist cycle audit record
        cycle = AutonomousPulseCycle(
            trigger=trigger,
            status="completed",
            symbols=target_symbols,
            sentiment_summary=sentiment_summary,
            decisions_json=decisions,
            orders_executed=orders_executed,
            duration_ms=duration_ms,
        )
        with self.db.session() as session:
            session.add(cycle)
            session.flush()
            return _cycle_to_dict(cycle)

    def list_history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent autonomous pulse cycles from database."""
        with self.db.session() as session:
            stmt = (
                select(AutonomousPulseCycle)
                .order_by(desc(AutonomousPulseCycle.created_at))
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [_cycle_to_dict(row) for row in rows]

    def _resolve_target_symbols(self, symbols: list[str] | None) -> list[str]:
        if symbols:
            return [s.strip().upper() for s in symbols if s.strip()]
        configured = self.settings.autonomous_pulse_symbols
        parsed = [s.strip().upper() for s in configured.split(",") if s.strip()]
        return parsed or ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]

    def _get_symbol_ticker(self, inst_id: str) -> dict[str, Any]:
        """Fetch latest cached or DB ticker."""
        with self.db.session() as session:
            row = session.scalar(
                select(MarketTicker)
                .where(MarketTicker.inst_id == inst_id)
                .order_by(desc(MarketTicker.created_at))
            )
            if row is not None:
                return {
                    "last": str(row.last),
                    "change_utc0_pct": str(row.change_utc0_pct),
                    "volume_24h": str(row.volume_ccy_24h),
                }
        return {"last": "0", "change_utc0_pct": "0", "volume_24h": "0"}

    def _evaluate_symbol_decision(
        self,
        *,
        inst_id: str,
        ticker: dict[str, Any],
        perception: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine perception features and invoke LLM reasoning or fast heuristic."""
        funding_data = perception.get("funding_and_oi", {}).get("metrics", {})
        news_data = perception.get("news_and_sentiment", {}).get("aggregated", {})

        sentiment_score = float(news_data.get("sentiment_score", 0.0))
        urgency = str(news_data.get("urgency", "normal"))
        breaking_events = list(news_data.get("breaking_events", []))
        funding_rate = float(funding_data.get("funding_rate", 0.0) or 0.0)

        # 1. Fast Heuristic Filter: If everything is quiet, HOLD immediately without token spend
        if (
            abs(sentiment_score) < 0.25
            and urgency not in {"breaking", "high"}
            and abs(funding_rate) < 0.0003
            and not breaking_events
        ):
            return {
                "symbol": inst_id,
                "action": "hold",
                "confidence": 0.90,
                "suggested_size": "0",
                "reason": "calm_market_rangebound_no_catalyst",
                "risk_assessment": "minimal_volatility",
            }

        # 2. If ChatProvider is available, invoke LLM reasoning for high-conviction decision
        if self.chat_provider is not None:
            return self._llm_reasoning_decision(
                inst_id=inst_id,
                ticker=ticker,
                funding_rate=funding_rate,
                sentiment_score=sentiment_score,
                urgency=urgency,
                breaking_events=breaking_events,
            )

        # Compute safe default size respecting max notional limits
        last_price = float(ticker.get("last", "0") or 0.0)
        try:
            max_notional = float(self.settings.risk_max_order_notional_usdt or "100")
        except Exception:
            max_notional = 100.0
        target_notional = max_notional * 0.8
        safe_size = (
            f"{(target_notional / last_price):.4f}".rstrip("0").rstrip(".")
            if last_price > 0
            else "1"
        )
        if not safe_size or safe_size == "0":
            safe_size = "0.01"

        # 3. Rule-based deterministic fallback if LLM is offline
        if sentiment_score >= 0.40 or (urgency == "breaking" and sentiment_score > 0.1):
            return {
                "symbol": inst_id,
                "action": "buy",
                "confidence": min(0.85, 0.60 + sentiment_score * 0.3),
                "suggested_size": safe_size,
                "reason": f"bullish_catalyst: sentiment={sentiment_score:.2f} urgency={urgency}",
                "risk_assessment": "controlled_long_breakout",
            }
        elif sentiment_score <= -0.40 or (urgency == "breaking" and sentiment_score < -0.1):
            return {
                "symbol": inst_id,
                "action": "sell",
                "confidence": min(0.85, 0.60 + abs(sentiment_score) * 0.3),
                "suggested_size": safe_size,
                "reason": f"bearish_catalyst: sentiment={sentiment_score:.2f} urgency={urgency}",
                "risk_assessment": "controlled_short_hedge",
            }

        return {
            "symbol": inst_id,
            "action": "hold",
            "confidence": 0.75,
            "suggested_size": "0",
            "reason": f"indecisive_sentiment: score={sentiment_score:.2f}",
            "risk_assessment": "awaiting_clearer_signal",
        }

    def _llm_reasoning_decision(
        self,
        *,
        inst_id: str,
        ticker: dict[str, Any],
        funding_rate: float,
        sentiment_score: float,
        urgency: str,
        breaking_events: list[str],
    ) -> dict[str, Any]:
        """Invoke Gemini 3.8 Flash High / Active LLM for structured pulse decision."""
        assert self.chat_provider is not None
        payload = {
            "symbol": inst_id,
            "last_price": ticker.get("last", "0"),
            "funding_rate": funding_rate,
            "sentiment_score": sentiment_score,
            "urgency": urgency,
            "breaking_events": breaking_events,
        }
        prompt = (
            "You are the HyperTrade Autonomous Market Pulse Engine.\n"
            "Analyze the real-time market data & sentiment below and output valid JSON ONLY.\n"
            f"Input:\n{json.dumps(payload, indent=2)}\n\n"
            "Output schema:\n"
            "{\n"
            '  "symbol": "<symbol>",\n'
            '  "action": "buy" | "sell" | "hold" | "close",\n'
            '  "confidence": <float 0.0 to 1.0>,\n'
            '  "suggested_size": "1",\n'
            '  "reason": "<short 1-line reason>",\n'
            '  "risk_assessment": "<short risk comment>"\n'
            "}"
        )
        try:
            resp = self.chat_provider.chat([{"role": "user", "content": prompt}])
            text = resp.content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "action" in parsed:
                return {
                    "symbol": inst_id,
                    "action": str(parsed.get("action", "hold")).lower(),
                    "confidence": float(parsed.get("confidence", 0.7)),
                    "suggested_size": str(parsed.get("suggested_size", "1")),
                    "reason": str(parsed.get("reason", "llm_autonomous_decision")),
                    "risk_assessment": str(parsed.get("risk_assessment", "normal")),
                }
        except Exception as exc:
            logger.warning("LLM pulse reasoning failed for %s: %s", inst_id, exc)

        return {
            "symbol": inst_id,
            "action": "hold",
            "confidence": 0.60,
            "suggested_size": "0",
            "reason": "llm_fallback_hold",
            "risk_assessment": "fallback_conservative",
        }
