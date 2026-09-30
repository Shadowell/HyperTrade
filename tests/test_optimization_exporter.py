from __future__ import annotations

import pytest

from hypertrade.db import Database, OptimizationStudy, OptimizationTrial
from hypertrade.research.optimization.exporter import export_to_bitpro, export_to_quantlab


def test_exporter_quantlab_and_bitpro() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    with db.session() as session:
        study = OptimizationStudy(
            strategy_identifier="trend_breakout_v1",
            strategy_code="class Strategy: pass",
            objective="composite_score",
            status="completed",
            search_method="grid",
            parameter_space_json={"parameters": [{"name": "fast", "type": "int"}]},
            matrix_config_json={"symbols": ["BTC-USDT-SWAP"], "timeframes": ["15M"]},
            total_trials=10,
            completed_trials=10,
        )
        session.add(study)
        session.flush()

        trial = OptimizationTrial(
            study_id=study.id,
            trial_index=1,
            parameters_json={"fast": 8, "slow": 24},
            status="completed",
            is_metrics_json={"annualized_sharpe": 2.1, "total_return_pct": 35.0, "max_drawdown_pct": 6.5},
            oos_metrics_json={"annualized_sharpe": 1.9, "total_return_pct": 28.0},
            scorecard_json={"verdict": "OPTIMIZED_PROMOTABLE"},
            composite_score=84.5,
            is_promotable=True,
        )
        session.add(trial)
        session.flush()

        study.best_trial_id = trial.id
        study.best_parameters_json = trial.parameters_json
        study.best_score = trial.composite_score

        # Test QuantLab Export
        ql_export = export_to_quantlab(study, trial)
        assert ql_export["target_id"] == "quantlab"
        assert ql_export["format_version"] == "quantlab_strategy_config.v1"
        assert ql_export["strategy_id"] == "trend_breakout_v1"
        assert ql_export["optimized_parameters"] == {"fast": 8, "slow": 24}
        assert ql_export["recommended_timeframe"] == "15M"
        assert ql_export["benchmark_metrics"]["composite_robustness_score"] == 84.5

        # Test BitPro Export
        bp_export = export_to_bitpro(study, trial)
        assert bp_export["target_id"] == "bitpro"
        assert bp_export["format_version"] == "bitpro_strategy_manifest.v3"
        assert bp_export["strategy_key"] == "trend_breakout_v1"
        assert bp_export["parameters"] == {"fast": 8, "slow": 24}
        assert bp_export["timeframe"] == "15M"
        assert bp_export["evidence"]["robustness_score"] == 84.5
