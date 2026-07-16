#!/usr/bin/env python3
"""Seed only the synthetic facts required by isolated operator eval suites.

This script is intentionally not a production data bootstrap: it requires both
the explicit isolated target marker and the evaluation application environment.
It creates no strategy, paper trade, approval or exchange action.
"""

from __future__ import annotations

import os
from decimal import Decimal

from hypertrade.config import get_settings
from hypertrade.db import (
    BacktestRun,
    Database,
    LiveOrderIntent,
    MarketTicker,
    MemoryItem,
    PaperOrder,
    PaperPosition,
    PaperSession,
    RagChunk,
    RagDocument,
)
from sqlalchemy import select


def main() -> int:
    settings = get_settings()
    if os.getenv("HYPERTRADE_EVAL_TARGET") != "isolated" or settings.app_env != "evaluation":
        raise SystemExit("operator-answer fixtures require the isolated evaluation target")
    database = Database(settings.database_url)
    with database.session() as session:
        for inst_id, last, volume, change in (
            ("BTC-USDT-SWAP", "65000", "25000000", "1.8"),
            ("ETH-USDT-SWAP", "3025", "18000000", "2.4"),
            ("SOL-USDT-SWAP", "145", "9000000", "-0.8"),
        ):
            if session.scalar(select(MarketTicker).where(MarketTicker.inst_id == inst_id)) is None:
                session.add(
                    MarketTicker(
                        inst_id=inst_id,
                        inst_type="SWAP",
                        last=Decimal(last),
                        volume_ccy_24h=Decimal(volume),
                        change_utc0_pct=Decimal(change),
                        raw={"fixture": "operator_task_completion.v1"},
                    )
                )
        if session.get(BacktestRun, "196") is None:
            session.add(
                BacktestRun(
                    id="196",
                    research_id="eval_research",
                    strategy_key="momentum_breakout_v1",
                    status="completed",
                    start_cash=Decimal("100000"),
                    end_value=Decimal("102100"),
                    total_return_pct=Decimal("2.1"),
                    max_drawdown_pct=Decimal("1.4"),
                    trade_count=12,
                    report_markdown="isolated evaluation fixture",
                    report_json={"fixture": "operator_answer.v1"},
                )
            )
        if session.get(BacktestRun, "197") is None:
            session.add(
                BacktestRun(
                    id="197",
                    research_id="eval_research",
                    strategy_key="mean_reversion_v1",
                    status="completed",
                    start_cash=Decimal("100000"),
                    end_value=Decimal("100800"),
                    total_return_pct=Decimal("0.8"),
                    max_drawdown_pct=Decimal("0.9"),
                    trade_count=8,
                    report_markdown="isolated evaluation fixture",
                    report_json={"fixture": "operator_task_completion.v1"},
                )
            )
        if session.get(PaperSession, "eval_paper") is None:
            session.add(
                PaperSession(
                    id="eval_paper",
                    name="Isolated operator evaluation",
                    status="running",
                    cash=Decimal("100000"),
                    equity=Decimal("100250"),
                    realized_pnl=Decimal("250"),
                    config_json={"fixture": "operator_answer.v1"},
                )
            )
        if session.get(PaperPosition, "eval_position") is None:
            session.add(
                PaperPosition(
                    id="eval_position",
                    session_id="eval_paper",
                    inst_id="ETH-USDT-SWAP",
                    side="long",
                    quantity=Decimal("1"),
                    entry_price=Decimal("3000"),
                    mark_price=Decimal("3025"),
                    notional=Decimal("3025"),
                    unrealized_pnl=Decimal("25"),
                    status="open",
                )
            )
        if session.get(PaperOrder, "eval_order") is None:
            session.add(
                PaperOrder(
                    id="eval_order",
                    session_id="eval_paper",
                    inst_id="ETH-USDT-SWAP",
                    side="buy",
                    quantity=Decimal("1"),
                    target_notional=Decimal("3025"),
                    status="filled",
                    reason="isolated operator evaluation fixture",
                )
            )
        if session.get(LiveOrderIntent, "eval_testnet_intent") is None:
            session.add(
                LiveOrderIntent(
                    id="eval_testnet_intent",
                    environment="testnet",
                    status="pending_approval",
                    inst_id="ETH-USDT-SWAP",
                    side="buy",
                    order_type="market",
                    size=Decimal("1"),
                    source="isolated_operator_eval",
                    risk_status="pending",
                    risk_json={"fixture": "operator_answer.v1"},
                    execution_json={},
                )
            )
        if session.get(RagDocument, "eval_rag_risk") is None:
            session.add(
                RagDocument(
                    id="eval_rag_risk",
                    source_path="eval://risk-controls",
                    content_hash="eval-risk-controls-v1",
                    title="隔离评测风控规则",
                )
            )
            session.add(
                RagChunk(
                    id="eval_rag_risk_chunk",
                    document_id="eval_rag_risk",
                    source_path="eval://risk-controls",
                    title="隔离评测风控规则",
                    chunk_index=0,
                    content="风控规则：每笔交易应先定义止损，单笔风险不得超过预设阈值。",
                    embedding_json=[],
                    embedding_vector=[],
                )
            )
        if session.get(MemoryItem, "eval_memory_momentum") is None:
            session.add(
                MemoryItem(
                    id="eval_memory_momentum",
                    kind="strategy_knowledge",
                    content="momentum_breakout_v1 的历史经验：回撤控制需与趋势过滤共同验证。",
                    source_run_id="eval_research",
                    source_tool="isolated_fixture",
                    importance=Decimal("0.90"),
                    tags=["momentum_breakout_v1", "eval"],
                    confidence=Decimal("0.90"),
                )
            )
    print("operator-answer isolated fixture seed complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
