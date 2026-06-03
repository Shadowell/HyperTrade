from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from hypertrade.backtest.service import BacktestService
from hypertrade.db import Database, StrategyExperiment
from hypertrade.strategy.service import StrategyResearchService


class StrategyExperimentService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, prompt: str) -> dict[str, Any]:
        research = StrategyResearchService(self.db).create(prompt)
        backtest = BacktestService(self.db).run(research_id=str(research["id"]))
        report_json = {
            "workflow": [
                "hypothesis",
                "data_selection",
                "backtest",
                "critique",
                "revision_suggestion",
                "report",
            ],
            "hypothesis": {
                "prompt": prompt,
                "strategy_key": research["strategy_key"],
                "summary": "Trend breakout hypothesis generated from the user research prompt.",
            },
            "data_selection": {
                "source": backtest["report_json"].get("data_source", "sample_candles"),
                "inst_id": backtest["report_json"].get("inst_id", ""),
                "bar": backtest["report_json"].get("bar", ""),
                "candle_count": backtest["report_json"].get("candle_count", 0),
            },
            "backtest": {
                "id": backtest["id"],
                "metrics": backtest["metrics"],
            },
            "critique": _critique(backtest),
            "revision_suggestion": {
                "next_experiment": (
                    "Sweep breakout window and stop-loss settings before any testnet signal use."
                ),
                "risk_note": (
                    "Treat this as research only; do not convert directly into live trading."
                ),
            },
            "disclaimer": "Research output only. Not investment advice.",
        }
        report_markdown = _render_experiment_report(
            prompt=prompt,
            research=research,
            backtest=backtest,
            report_json=report_json,
        )
        with self.db.session() as session:
            experiment = StrategyExperiment(
                prompt=prompt,
                status="completed",
                research_id=str(research["id"]),
                backtest_id=str(backtest["id"]),
                report_markdown=report_markdown,
                report_json=report_json,
            )
            session.add(experiment)
            session.flush()
            return _experiment_to_dict(experiment)

    def latest(self) -> dict[str, Any] | None:
        with self.db.session() as session:
            experiment = session.scalar(
                select(StrategyExperiment).order_by(desc(StrategyExperiment.created_at)).limit(1)
            )
            return _experiment_to_dict(experiment) if experiment else None

    def list_recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyExperiment)
                .order_by(desc(StrategyExperiment.created_at))
                .limit(limit)
            ).all()
            return [_experiment_to_dict(row) for row in rows]


def _critique(backtest: dict[str, Any]) -> dict[str, Any]:
    metrics = backtest.get("metrics", {})
    trade_count = metrics.get("trade_count", 0) if isinstance(metrics, dict) else 0
    return {
        "trade_count": trade_count,
        "notes": [
            "Sample-size is small unless a live or archived candle source is selected.",
            "Check drawdown sensitivity before increasing leverage.",
            "Compare against a no-trade baseline and a simpler momentum baseline.",
        ],
    }


def _render_experiment_report(
    *,
    prompt: str,
    research: dict[str, Any],
    backtest: dict[str, Any],
    report_json: dict[str, Any],
) -> str:
    metrics = backtest["metrics"]
    critique = report_json["critique"]
    return "\n".join(
        [
            "# 策略研究实验报告",
            "",
            f"**Prompt**: {prompt}",
            f"**Research**: `{research['id']}`",
            f"**Backtest**: `{backtest['id']}`",
            "",
            "## Hypothesis",
            f"- Strategy: `{research['strategy_key']}`",
            "- 趋势突破信号可能捕捉短线动量延续。",
            "",
            "## Backtest Summary",
            f"- Return: {metrics.get('total_return_pct', 'n/a')}%",
            f"- Max drawdown: {metrics.get('max_drawdown_pct', 'n/a')}%",
            f"- Trades: {metrics.get('trade_count', 'n/a')}",
            "",
            "## Critique",
            *[f"- {note}" for note in critique["notes"]],
            "",
            "## Next Experiment",
            f"- {report_json['revision_suggestion']['next_experiment']}",
            "",
            "风险提示：本报告仅用于研究和学习，不构成投资建议。",
        ]
    )


def _experiment_to_dict(experiment: StrategyExperiment) -> dict[str, Any]:
    return {
        "id": experiment.id,
        "prompt": experiment.prompt,
        "status": experiment.status,
        "research_id": experiment.research_id,
        "backtest_id": experiment.backtest_id,
        "report_markdown": experiment.report_markdown,
        "report_json": experiment.report_json,
        "created_at": experiment.created_at.isoformat(),
    }
