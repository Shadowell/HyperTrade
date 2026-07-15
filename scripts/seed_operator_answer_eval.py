#!/usr/bin/env python3
"""Seed only the synthetic facts required by the isolated operator-answer suite.

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
    PaperOrder,
    PaperPosition,
    PaperSession,
)


def main() -> int:
    settings = get_settings()
    if os.getenv("HYPERTRADE_EVAL_TARGET") != "isolated" or settings.app_env != "evaluation":
        raise SystemExit("operator-answer fixtures require the isolated evaluation target")
    database = Database(settings.database_url)
    with database.session() as session:
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
    print("operator-answer isolated fixture seed complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
