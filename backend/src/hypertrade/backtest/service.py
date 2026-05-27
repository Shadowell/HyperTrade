from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.backtest.engine import BacktestEngine
from hypertrade.db import BacktestRun, Database
from hypertrade.strategy.sdk import Candle, sample_candles
from hypertrade.strategy.service import StrategyResearchService


class BacktestService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.engine = BacktestEngine()

    def run(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        candles: list[Candle] | None = None,
        initial_cash: Decimal = Decimal("100000"),
    ) -> dict[str, Any]:
        if research_id:
            research = StrategyResearchService(self.db).get(research_id)
            if research is None:
                raise KeyError(research_id)
            strategy_key = str(research["strategy_key"])
        result = self.engine.run(
            strategy_key=strategy_key,
            candles=candles or sample_candles(),
            initial_cash=initial_cash,
        )
        with self.db.session() as session:
            run = BacktestRun(
                research_id=research_id,
                strategy_key=result.strategy_key,
                status="completed",
                start_cash=result.start_cash,
                end_value=result.end_value,
                total_return_pct=result.total_return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                trade_count=result.trade_count,
                report_markdown=result.report_markdown,
                report_json=result.report_json,
            )
            session.add(run)
            session.flush()
            return _run_to_dict(run)

    def latest(self) -> dict[str, Any] | None:
        with self.db.session() as session:
            run = session.scalar(
                select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(1)
            )
            return _run_to_dict(run) if run else None

    def list_recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.db.session() as session:
            runs = session.scalars(
                select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)
            ).all()
            return [_run_to_dict(run) for run in runs]


def _run_to_dict(run: BacktestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "research_id": run.research_id,
        "strategy_key": run.strategy_key,
        "status": run.status,
        "metrics": {
            "start_cash": str(run.start_cash),
            "end_value": str(run.end_value),
            "total_return_pct": str(run.total_return_pct),
            "max_drawdown_pct": str(run.max_drawdown_pct),
            "trade_count": run.trade_count,
        },
        "report_markdown": run.report_markdown,
        "report_json": run.report_json,
        "created_at": run.created_at.isoformat(),
    }
