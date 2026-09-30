"""Service orchestration for strategy parameter optimization studies and trial execution."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import (
    Database,
    OptimizationStudy,
    OptimizationTrial,
    utc_now,
)
from hypertrade.research.codegen import generate_strategy
from hypertrade.research.optimization.exporter import export_to_bitpro, export_to_quantlab
from hypertrade.research.optimization.matrix import (
    BacktestMatrixEngine,
    Bar,
    MatrixTrialResult,
    generate_synthetic_bars,
)
from hypertrade.research.optimization.robustness import RobustnessEvaluator, RobustnessScoreCard
from hypertrade.research.optimization.space import (
    GridSampler,
    LlmMutationSampler,
    ParameterSpace,
    RandomSampler,
    extract_parameter_space_from_code,
)

logger = logging.getLogger(__name__)


class OptimizationService:
    """Orchestrates hyperparameter search space extraction, matrix runs, and robustness scoring."""

    def __init__(
        self,
        db: Database,
        chat_provider: Any = None,
    ) -> None:
        self.db = db
        self.chat_provider = chat_provider

    def start_study(
        self,
        *,
        strategy_identifier: str,
        strategy_code: str | None = None,
        parameter_space: ParameterSpace | dict[str, Any] | None = None,
        symbols: Sequence[str] = ("BTC-USDT-SWAP",),
        timeframes: Sequence[str] = ("1H",),
        search_method: str = "grid",
        max_trials: int = 20,
        is_ratio: float = 0.70,
        objective: str = "composite_score",
        historical_bars: dict[tuple[str, str], Sequence[Bar]] | None = None,
        execute_sync: bool = True,
    ) -> dict[str, Any]:
        """Create and run a parameter optimization study."""
        resolved_symbols = list(symbols) or ["BTC-USDT-SWAP"]
        resolved_tfs = [tf.upper() for tf in timeframes] or ["1H"]

        # Resolve strategy code if none provided
        code = strategy_code
        if not code:
            code = self._default_strategy_code(strategy_identifier)

        # Resolve parameter space
        space: ParameterSpace
        if isinstance(parameter_space, ParameterSpace):
            space = parameter_space
        elif isinstance(parameter_space, dict):
            space = ParameterSpace.from_dict(parameter_space)
        else:
            space = extract_parameter_space_from_code(code)
            if not space.parameters:
                # If still empty, supply reasonable default parameters
                from hypertrade.research.optimization.space import IntParam

                space.add_param(IntParam("fast_period", 5, 20, step=5, default=10))
                space.add_param(IntParam("slow_period", 25, 60, step=10, default=30))

        # Sample candidate parameter variants
        variants = self._sample_variants(
            space=space,
            search_method=search_method,
            max_trials=max_trials,
        )

        matrix_config = {
            "symbols": resolved_symbols,
            "timeframes": resolved_tfs,
            "is_ratio": is_ratio,
            "max_trials": max_trials,
            "objective": objective,
        }

        with self.db.session() as session:
            study = OptimizationStudy(
                strategy_identifier=strategy_identifier,
                strategy_code=code,
                objective=objective,
                status="running" if execute_sync else "pending",
                search_method=search_method,
                parameter_space_json=space.to_dict(),
                matrix_config_json=matrix_config,
                total_trials=len(variants),
                completed_trials=0,
            )
            session.add(study)
            session.flush()
            study_id = study.id

        if execute_sync:
            self._execute_study_sync(
                study_id=study_id,
                code=code,
                space=space,
                variants=variants,
                symbols=resolved_symbols,
                timeframes=resolved_tfs,
                is_ratio=is_ratio,
                historical_bars=historical_bars,
            )

        return self.get_study(study_id) or {}

    def _execute_study_sync(
        self,
        *,
        study_id: str,
        code: str,
        space: ParameterSpace,
        variants: list[dict[str, Any]],
        symbols: list[str],
        timeframes: list[str],
        is_ratio: float,
        historical_bars: dict[tuple[str, str], Sequence[Bar]] | None,
    ) -> None:
        """Run all variants through matrix engine and robustness evaluator."""
        # Ensure historical bars are present
        bars_map = dict(historical_bars or {})
        for sym in symbols:
            for tf in timeframes:
                key = (sym, tf)
                if key not in bars_map:
                    bars_map[key] = generate_synthetic_bars(
                        symbol=sym,
                        count=160,
                        timeframe=tf,
                    )

        matrix_engine = BacktestMatrixEngine(
            strategy_code=code,
            symbols=symbols,
            timeframes=timeframes,
            is_ratio=is_ratio,
        )

        evaluator = RobustnessEvaluator(space=space)

        best_trial_id: str | None = None
        best_params: dict[str, Any] = {}
        best_score: float = -1.0
        completed_count = 0

        trial_results = matrix_engine.run_matrix(
            parameter_variants=variants,
            bars_by_dimension=bars_map,
        )

        with self.db.session() as session:
            study = session.get(OptimizationStudy, study_id)
            if study is None:
                return

            for trial_res in trial_results:
                scorecard = evaluator.evaluate_trial(
                    trial_result=trial_res,
                    matrix_engine=matrix_engine,
                    bars_by_dimension=bars_map,
                )

                trial = OptimizationTrial(
                    study_id=study_id,
                    trial_index=trial_res.trial_index,
                    parameters_json=trial_res.parameters,
                    status="completed" if trial_res.is_successful else "failed",
                    is_metrics_json=trial_res.aggregated_is_metrics.to_dict(),
                    oos_metrics_json=trial_res.aggregated_oos_metrics.to_dict(),
                    scorecard_json=scorecard.to_dict(),
                    composite_score=scorecard.composite_score,
                    is_promotable=scorecard.is_promotable,
                    error_message=trial_res.error,
                )
                session.add(trial)
                session.flush()

                completed_count += 1
                if scorecard.composite_score > best_score:
                    best_score = scorecard.composite_score
                    best_params = trial_res.parameters
                    best_trial_id = trial.id

            study.status = "completed"
            study.completed_trials = completed_count
            study.best_trial_id = best_trial_id
            study.best_parameters_json = best_params
            study.best_score = best_score if best_score >= 0 else None

    def _sample_variants(
        self,
        space: ParameterSpace,
        search_method: str,
        max_trials: int,
    ) -> list[dict[str, Any]]:
        method = search_method.lower()
        if method == "grid":
            sampler = GridSampler(space)
            return sampler.sample_all(max_trials=max_trials)
        elif method == "random":
            r_sampler = RandomSampler(space)
            return r_sampler.sample_n(max_trials)
        elif method == "llm":
            # For initial study without history, sample random then mutate
            r_sampler = RandomSampler(space)
            return r_sampler.sample_n(max_trials)
        else:
            sampler = GridSampler(space)
            return sampler.sample_all(max_trials=max_trials)

    def get_study(self, study_id: str) -> dict[str, Any] | None:
        with self.db.session() as session:
            study = session.get(OptimizationStudy, study_id)
            if study is None:
                return None
            return {
                "id": study.id,
                "strategy_identifier": study.strategy_identifier,
                "objective": study.objective,
                "status": study.status,
                "search_method": study.search_method,
                "total_trials": study.total_trials,
                "completed_trials": study.completed_trials,
                "best_trial_id": study.best_trial_id,
                "best_parameters": study.best_parameters_json,
                "best_score": study.best_score,
                "parameter_space": study.parameter_space_json,
                "matrix_config": study.matrix_config_json,
                "created_at": study.created_at.isoformat() if study.created_at else None,
                "updated_at": study.updated_at.isoformat() if study.updated_at else None,
            }

    def list_studies(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(OptimizationStudy)
                .order_by(desc(OptimizationStudy.created_at))
                .limit(limit)
            ).all()
            return [
                {
                    "id": r.id,
                    "strategy_identifier": r.strategy_identifier,
                    "status": r.status,
                    "search_method": r.search_method,
                    "total_trials": r.total_trials,
                    "completed_trials": r.completed_trials,
                    "best_score": r.best_score,
                    "best_parameters": r.best_parameters_json,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    def get_study_trials(self, study_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            trials = session.scalars(
                select(OptimizationTrial)
                .where(OptimizationTrial.study_id == study_id)
                .order_by(OptimizationTrial.trial_index.asc())
            ).all()
            return [
                {
                    "id": t.id,
                    "trial_index": t.trial_index,
                    "parameters": t.parameters_json,
                    "status": t.status,
                    "is_metrics": t.is_metrics_json,
                    "oos_metrics": t.oos_metrics_json,
                    "scorecard": t.scorecard_json,
                    "composite_score": t.composite_score,
                    "is_promotable": t.is_promotable,
                    "error_message": t.error_message,
                }
                for t in trials
            ]

    def export_study(self, study_id: str, target_format: str = "quantlab") -> dict[str, Any]:
        with self.db.session() as session:
            study = session.get(OptimizationStudy, study_id)
            if study is None:
                raise KeyError(f"Optimization study not found: {study_id}")

            trial: OptimizationTrial | None = None
            if study.best_trial_id:
                trial = session.get(OptimizationTrial, study.best_trial_id)

            if target_format.lower() == "bitpro":
                return export_to_bitpro(study, trial or {})
            return export_to_quantlab(study, trial or {})

    def _default_strategy_code(self, identifier: str) -> str:
        """Produce standard compliant BaseStrategy code via codegen."""
        generated = generate_strategy(
            {
                "schema_version": "research_strategy_spec.v1",
                "strategy_key": identifier,
                "hypothesis": "自主参数优化自合成均线策略",
                "entry_logic": "快线上穿慢线做多",
                "exit_logic": "快线下穿慢线平仓",
                "risk_conditions": ["stop loss"],
            }
        )
        return generated.code
