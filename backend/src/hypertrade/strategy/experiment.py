"""Multi-step strategy research workflow.

The experiment service is a small deterministic workflow that mirrors how an
Agent should research a strategy: form a hypothesis, select data, run backtest,
critique the result, suggest the next experiment, and render a report. It is
kept deterministic so acceptance tests can verify the workflow without LLM keys.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.backtest.service import BacktestService
from hypertrade.db import Database, StrategyExperiment
from hypertrade.memory.service import MemoryService
from hypertrade.strategy.evidence import StrategyEvidence
from hypertrade.strategy.iteration import StrategyIterationService
from hypertrade.strategy.service import StrategyResearchService

MIN_TRADE_COUNT = 1
MAX_DRAWDOWN_PCT = Decimal("20")
EVIDENCE_GATES = {
    "min_trade_count": MIN_TRADE_COUNT,
    "max_drawdown_pct": str(MAX_DRAWDOWN_PCT),
    "require_non_negative_return": True,
}
STRATEGY_KNOWLEDGE_BOUNDARIES = [
    "research_only",
    "no_bitpro_write",
    "no_live_or_testnet_order",
]


class StrategyExperimentService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, prompt: str) -> dict[str, Any]:
        research = StrategyResearchService(self.db).create(prompt)
        backtest_service = BacktestService(self.db)
        variants = [
            _variant_record(
                candidate,
                backtest_service.run(
                    research_id=str(research["id"]),
                    strategy_params=candidate["strategy_params"],
                ),
            )
            for candidate in _candidate_variants()
        ]
        winner = _select_winner(variants)
        report_json = {
            "workflow": [
                "hypothesis",
                "data_selection",
                "variant_backtests",
                "variant_comparison",
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
                "source": winner["data_selection"].get("source", "sample_candles"),
                "inst_id": winner["data_selection"].get("inst_id", ""),
                "bar": winner["data_selection"].get("bar", ""),
                "candle_count": winner["data_selection"].get("candle_count", 0),
            },
            "backtest": {
                "id": winner["backtest_id"],
                "metrics": winner["metrics"],
            },
            "variants": variants,
            "winner": _winner_summary(winner),
            "evidence_gates": EVIDENCE_GATES,
            "critique": _critique(winner),
            "revision_suggestion": {
                # The workflow stops at a recommendation. It does not mutate git
                # strategy code or auto-promote ideas to live trading.
                "next_experiment": _next_experiment(winner),
                "risk_note": (
                    "Treat this as research only; do not convert directly into live trading."
                ),
            },
            "disclaimer": "Research output only. Not investment advice.",
        }
        report_markdown = _render_experiment_report(
            prompt=prompt,
            research=research,
            report_json=report_json,
        )
        with self.db.session() as session:
            experiment = StrategyExperiment(
                prompt=prompt,
                status="completed",
                research_id=str(research["id"]),
                backtest_id=str(winner["backtest_id"]),
                report_markdown=report_markdown,
                report_json=report_json,
            )
            session.add(experiment)
            session.flush()
            result = _experiment_to_dict(experiment)
        _write_strategy_knowledge_memory(self.db, result)
        return result

    def create_iteration(
        self,
        prompt: str,
        *,
        strategy_key: str = "momentum_breakout_v1",
        max_variants: int = 3,
    ) -> dict[str, Any]:
        iteration = StrategyIterationService(self.db, max_variants=max_variants)
        plan = iteration.plan(
            prompt,
            strategy_key=strategy_key,
            max_variants=max_variants,
        )
        research = StrategyResearchService(self.db).create(prompt)
        backtest_service = BacktestService(self.db)
        variants = [
            _variant_record(
                candidate,
                backtest_service.run(
                    research_id=str(research["id"]),
                    strategy_params=candidate["strategy_params"],
                ),
            )
            for candidate in plan["variants"]
        ]
        winner = _select_winner(variants)
        winner_summary = _winner_summary(winner)
        comparison = iteration.compare_result(winner_summary, plan)
        report_json = {
            "workflow": [
                "strategy_library_search",
                "iteration_plan",
                "hypothesis",
                "data_selection",
                "variant_backtests",
                "variant_comparison",
                "result_comparison",
                "critique",
                "revision_suggestion",
                "report",
            ],
            "hypothesis": {
                "prompt": prompt,
                "strategy_key": research["strategy_key"],
                "summary": (
                    "Trend breakout iteration generated from prior source-bound evidence."
                ),
            },
            "prior_evidence": plan["prior_evidence"],
            "variant_plan": plan,
            "data_selection": {
                "source": winner["data_selection"].get("source", "sample_candles"),
                "inst_id": winner["data_selection"].get("inst_id", ""),
                "bar": winner["data_selection"].get("bar", ""),
                "candle_count": winner["data_selection"].get("candle_count", 0),
            },
            "backtest": {
                "id": winner["backtest_id"],
                "metrics": winner["metrics"],
            },
            "variants": variants,
            "winner": winner_summary,
            "evidence_gates": EVIDENCE_GATES,
            "result_comparison": comparison,
            "critique": _critique(winner),
            "revision_suggestion": {
                "next_experiment": _next_experiment(winner),
                "risk_note": (
                    "Treat this as research only; do not convert directly into live trading."
                ),
            },
            "disclaimer": "Research output only. Not investment advice.",
        }
        report_markdown = _render_experiment_report(
            prompt=prompt,
            research=research,
            report_json=report_json,
        )
        with self.db.session() as session:
            experiment = StrategyExperiment(
                prompt=prompt,
                status="completed",
                research_id=str(research["id"]),
                backtest_id=str(winner["backtest_id"]),
                report_markdown=report_markdown,
                report_json=report_json,
            )
            session.add(experiment)
            session.flush()
            result = _experiment_to_dict(experiment)
        _write_strategy_knowledge_memory(self.db, result)
        return result

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


def _candidate_variants() -> list[dict[str, Any]]:
    return [
        {
            "variant_id": "baseline",
            "name": "Baseline SMA5 breakout",
            "strategy_params": {"sma_period": 5, "breakout_pct": 0.0},
        },
        {
            "variant_id": "fast",
            "name": "Fast SMA3 breakout",
            "strategy_params": {"sma_period": 3, "breakout_pct": 0.0},
        },
        {
            "variant_id": "conservative",
            "name": "Conservative SMA8 breakout",
            "strategy_params": {"sma_period": 8, "breakout_pct": 0.005},
        },
    ]


def _variant_record(candidate: dict[str, Any], backtest: dict[str, Any]) -> dict[str, Any]:
    metrics = backtest["metrics"]
    gate_results = _evaluate_gates(metrics)
    score = _variant_score(metrics, gate_results)
    report_json = backtest.get("report_json", {})
    report_json = report_json if isinstance(report_json, dict) else {}
    record = {
        "variant_id": candidate["variant_id"],
        "name": candidate["name"],
        "strategy_key": backtest["strategy_key"],
        "strategy_params": {
            key: str(value) for key, value in candidate["strategy_params"].items()
        },
        "backtest_id": backtest["id"],
        "metrics": metrics,
        "data_selection": {
            "source": report_json.get("data_source", "sample_candles"),
            "inst_id": report_json.get("inst_id", ""),
            "bar": report_json.get("bar", ""),
            "candle_count": report_json.get("candle_count", 0),
        },
        "gate_results": gate_results,
        "passed": all(gate_results.values()),
        "score": str(score.quantize(Decimal("0.000001"))),
    }
    for field in (
        "reason",
        "source_memory_id",
        "source_experiment_id",
        "source_backtest_id",
    ):
        if field in candidate:
            record[field] = str(candidate.get(field, ""))
    return record


def _evaluate_gates(metrics: dict[str, Any]) -> dict[str, bool]:
    return {
        "min_trade_count": int(metrics.get("trade_count", 0) or 0) >= MIN_TRADE_COUNT,
        "max_drawdown_pct": _metric_decimal(metrics, "max_drawdown_pct") <= MAX_DRAWDOWN_PCT,
        "require_non_negative_return": _metric_decimal(metrics, "total_return_pct") >= 0,
    }


def _variant_score(metrics: dict[str, Any], gate_results: dict[str, bool]) -> Decimal:
    total_return = _metric_decimal(metrics, "total_return_pct")
    drawdown = _metric_decimal(metrics, "max_drawdown_pct")
    trade_count = Decimal(str(int(metrics.get("trade_count", 0) or 0)))
    score = total_return - (drawdown * Decimal("0.5")) + (
        min(trade_count, Decimal("20")) * Decimal("0.1")
    )
    if not all(gate_results.values()):
        score -= Decimal("1000")
    return score


def _select_winner(variants: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        variants,
        key=lambda row: (
            bool(row["passed"]),
            Decimal(str(row["score"])),
            _metric_decimal(row["metrics"], "total_return_pct"),
            -_metric_decimal(row["metrics"], "max_drawdown_pct"),
        ),
    )


def _winner_summary(winner: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "variant_id": winner["variant_id"],
        "name": winner["name"],
        "backtest_id": winner["backtest_id"],
        "strategy_params": winner["strategy_params"],
        "metrics": winner["metrics"],
        "gate_results": winner["gate_results"],
        "failure_reasons": _failure_reasons(winner["gate_results"]),
        "score": winner["score"],
        "passed": winner["passed"],
        "selection_reason": (
            "Selected by pass/fail gates first, then return/drawdown/trade-count score."
        ),
    }
    for field in (
        "reason",
        "source_memory_id",
        "source_experiment_id",
        "source_backtest_id",
    ):
        if field in winner:
            summary[field] = winner[field]
    return summary


def _next_experiment(winner: dict[str, Any]) -> str:
    params = winner["strategy_params"]
    return (
        "Use the winning variant as baseline, then test adjacent SMA windows around "
        f"{params.get('sma_period')} and breakout_pct around {params.get('breakout_pct')} "
        "on a larger live or BitPro MCP candle window."
    )


def _metric_decimal(metrics: dict[str, Any], key: str) -> Decimal:
    return Decimal(str(metrics.get(key, "0") or "0"))


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
    report_json: dict[str, Any],
) -> str:
    winner = report_json["winner"]
    metrics = winner["metrics"]
    critique = report_json["critique"]
    variant_rows = [
        (
            "| {variant} | `{backtest}` | {params} | {ret}% | {drawdown}% | "
            "{trades} | {score} | {passed} |"
        ).format(
            variant=row["variant_id"],
            backtest=row["backtest_id"],
            params=", ".join(f"{key}={value}" for key, value in row["strategy_params"].items()),
            ret=row["metrics"].get("total_return_pct", "n/a"),
            drawdown=row["metrics"].get("max_drawdown_pct", "n/a"),
            trades=row["metrics"].get("trade_count", "n/a"),
            score=row["score"],
            passed="pass" if row["passed"] else "fail",
        )
        for row in report_json["variants"]
    ]
    prior_lines = _render_prior_evidence_lines(report_json)
    plan_lines = _render_variant_plan_lines(report_json)
    comparison_lines = _render_evidence_comparison_lines(report_json)
    return "\n".join(
        [
            "# 策略研究实验报告",
            "",
            f"**Prompt**: {prompt}",
            f"**Research**: `{research['id']}`",
            f"**Winning Backtest**: `{winner['backtest_id']}`",
            "",
            "## Hypothesis",
            f"- Strategy: `{research['strategy_key']}`",
            "- 趋势突破信号可能捕捉短线动量延续。",
            "",
            *prior_lines,
            *plan_lines,
            "## 候选版本对比",
            "| Variant | Backtest | Params | Return | Drawdown | Trades | Score | Gates |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            *variant_rows,
            "",
            "## 胜出版本",
            f"- Variant: `{winner['variant_id']}` / {winner['name']}",
            f"- Backtest: `{winner['backtest_id']}`",
            f"- Params: {winner['strategy_params']}",
            f"- Selection: {winner['selection_reason']}",
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
            *comparison_lines,
            "风险提示：本报告输出仅用于研究辅助，不构成投资建议。",
        ]
    )


def _render_prior_evidence_lines(report_json: dict[str, Any]) -> list[str]:
    prior = _as_dict(report_json.get("prior_evidence"))
    if not prior:
        return []
    source_ids = [str(item) for item in prior.get("source_memory_ids", [])]
    best = _as_dict(prior.get("best"))
    lines = [
        "## Prior Evidence",
        f"- Source: {prior.get('source', 'memory.strategy_knowledge')}",
        f"- Source memory ids: {', '.join(source_ids) if source_ids else 'none'}",
    ]
    if best:
        lines.append(
            "- Best prior: "
            f"memory={best.get('memory_id', 'n/a')} "
            f"experiment={best.get('experiment_id', 'n/a')} "
            f"backtest={best.get('backtest_id', 'n/a')} "
            f"return={best.get('total_return_pct', 'n/a')}% "
            f"drawdown={best.get('max_drawdown_pct', 'n/a')}%"
        )
    else:
        lines.append("- No prior evidence matched; this run creates a first baseline.")
    lines.append("")
    return lines


def _render_variant_plan_lines(report_json: dict[str, Any]) -> list[str]:
    plan = _as_dict(report_json.get("variant_plan"))
    if not plan:
        return []
    variants = plan.get("variants")
    variants = variants if isinstance(variants, list) else []
    lines = [
        "## Variant Plan",
        f"- Mode: {plan.get('mode', 'n/a')}",
        f"- Summary: {plan.get('summary', '')}",
    ]
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        source = str(variant.get("source_memory_id", "") or "none")
        lines.append(
            f"- {variant.get('variant_id', 'variant')}: {variant.get('reason', '')} "
            f"(source_memory_id={source})"
        )
    lines.append("")
    return lines


def _render_evidence_comparison_lines(report_json: dict[str, Any]) -> list[str]:
    comparison = _as_dict(report_json.get("result_comparison"))
    if not comparison:
        return []
    claim_text = "可声明改进" if comparison.get("can_claim_improvement") else "未声称改进"
    return [
        "## Evidence Comparison",
        f"- Claim: {comparison.get('claim', 'n/a')} ({claim_text})",
        f"- Reason: {comparison.get('reason', '')}",
        "",
    ]


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


def _write_strategy_knowledge_memory(db: Database, experiment: dict[str, Any]) -> None:
    report_json = _as_dict(experiment.get("report_json"))
    winner = _as_dict(report_json.get("winner"))
    if not winner:
        return
    hypothesis = _as_dict(report_json.get("hypothesis"))
    data_selection = _as_dict(report_json.get("data_selection"))
    strategy_key = str(hypothesis.get("strategy_key", "") or winner.get("strategy_key", ""))
    winner_id = str(winner.get("variant_id", ""))
    MemoryService(db).write(
        content=_strategy_evidence_from_experiment(
            experiment=experiment,
            report_json=report_json,
            winner=winner,
            strategy_key=strategy_key,
        ).to_memory_content(),
        kind="strategy_knowledge",
        source_run_id=str(experiment.get("id", "")),
        source_tool="strategy.experiment",
        tags=_strategy_knowledge_tags(strategy_key=strategy_key, winner_id=winner_id),
        importance=Decimal("0.82") if bool(winner.get("passed")) else Decimal("0.68"),
        confidence=_strategy_knowledge_confidence(
            winner=winner,
            data_selection=data_selection,
        ),
    )


def _strategy_evidence_from_experiment(
    *,
    experiment: dict[str, Any],
    report_json: dict[str, Any],
    winner: dict[str, Any],
    strategy_key: str,
) -> StrategyEvidence:
    metrics = {key: str(value) for key, value in _as_dict(winner.get("metrics")).items()}
    metrics["score"] = str(winner.get("score", "n/a") or "n/a")
    revision = _as_dict(report_json.get("revision_suggestion"))
    variants = report_json.get("variants")
    variant_count = len(variants) if isinstance(variants, list) else 0
    failure_reasons = winner.get("failure_reasons")
    return StrategyEvidence(
        strategy_key=strategy_key,
        experiment_id=str(experiment.get("id", "")),
        research_id=str(experiment.get("research_id", "")),
        backtest_id=str(winner.get("backtest_id", "")),
        bitpro_result_id=str(winner.get("bitpro_result_id", "")),
        variant_id=str(winner.get("variant_id", "") or "n/a"),
        variant_count=variant_count,
        parameters={
            key: str(value)
            for key, value in _as_dict(winner.get("strategy_params")).items()
        },
        metrics=metrics,
        gate_results={
            key: bool(value) for key, value in _as_dict(winner.get("gate_results")).items()
        },
        failure_reasons=[
            str(reason)
            for reason in (failure_reasons if isinstance(failure_reasons, list) else [])
        ],
        source_data={
            key: str(value) for key, value in _as_dict(report_json.get("data_selection")).items()
        },
        next_experiment=str(revision.get("next_experiment", "")),
        boundaries=STRATEGY_KNOWLEDGE_BOUNDARIES,
        passed=bool(winner.get("passed")),
    )


def _render_strategy_knowledge_memory(
    *,
    experiment: dict[str, Any],
    report_json: dict[str, Any],
    winner: dict[str, Any],
    strategy_key: str,
) -> str:
    metrics = _as_dict(winner.get("metrics"))
    data_selection = _as_dict(report_json.get("data_selection"))
    variants = report_json.get("variants")
    variants = variants if isinstance(variants, list) else []
    gate_results = _as_dict(winner.get("gate_results"))
    failure_reasons = winner.get("failure_reasons")
    failure_reasons = failure_reasons if isinstance(failure_reasons, list) else []
    gates = _as_dict(report_json.get("evidence_gates"))
    revision = _as_dict(report_json.get("revision_suggestion"))
    return "\n".join(
        [
            "策略经验: local strategy experiment evidence",
            (
                f"experiment={experiment.get('id', '')}; "
                f"research={experiment.get('research_id', '')}; "
                f"backtest={winner.get('backtest_id', '')}; "
                f"strategy={strategy_key}; "
                f"winner={winner.get('variant_id', '')}; "
                f"passed={str(bool(winner.get('passed'))).lower()}"
            ),
            f"variant_count={len(variants)}",
            f"params={_stable_mapping(_as_dict(winner.get('strategy_params')))}",
            (
                "metrics="
                f"total_return_pct={metrics.get('total_return_pct', 'n/a')}; "
                f"max_drawdown_pct={metrics.get('max_drawdown_pct', 'n/a')}; "
                f"trade_count={metrics.get('trade_count', 'n/a')}; "
                f"score={winner.get('score', 'n/a')}"
            ),
            (
                "data="
                f"source={data_selection.get('source', 'n/a')}; "
                f"inst_id={data_selection.get('inst_id', '')}; "
                f"bar={data_selection.get('bar', '')}; "
                f"candle_count={data_selection.get('candle_count', 'n/a')}"
            ),
            f"evidence_gates={_stable_mapping(gates)}",
            f"gate_results={_stable_mapping(gate_results)}",
            f"failure_reasons={', '.join(failure_reasons) if failure_reasons else 'none'}",
            f"next_experiment={revision.get('next_experiment', '')}",
            "boundary=research_only; no_bitpro_write; no_live_or_testnet_order",
        ]
    )


def _strategy_knowledge_tags(*, strategy_key: str, winner_id: str) -> list[str]:
    tags = [
        "strategy",
        "strategy_knowledge",
        "strategy_experiment",
        "evidence",
        "backtest",
    ]
    if strategy_key:
        tags.append(strategy_key)
        tags.append(f"strategy:{strategy_key}")
    if winner_id:
        tags.append(f"winner:{winner_id}")
    return tags


def _strategy_knowledge_confidence(
    *,
    winner: dict[str, Any],
    data_selection: dict[str, Any],
) -> Decimal:
    metrics = _as_dict(winner.get("metrics"))
    confidence = Decimal("0.62")
    if str(data_selection.get("source", "")) not in {"", "sample_candles"}:
        confidence += Decimal("0.08")
    trade_count = _safe_int(metrics.get("trade_count", 0))
    if trade_count >= 10:
        confidence += Decimal("0.08")
    elif trade_count >= 3:
        confidence += Decimal("0.04")
    return min(confidence, Decimal("0.90"))


def _stable_mapping(mapping: dict[str, Any]) -> str:
    if not mapping:
        return "none"
    return ", ".join(f"{key}={mapping[key]}" for key in sorted(mapping))


def _failure_reasons(gate_results: dict[str, bool]) -> list[str]:
    return [key for key, passed in sorted(gate_results.items()) if not passed]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
