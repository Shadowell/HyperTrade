"""Export optimized strategy configurations for QuantLab and BitPro workbenches."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hypertrade.db import OptimizationStudy, OptimizationTrial, utc_now


def export_to_quantlab(
    study: OptimizationStudy,
    trial: OptimizationTrial | dict[str, Any],
) -> dict[str, Any]:
    """Format optimized strategy configuration for QuantLab workbench."""
    if isinstance(trial, OptimizationTrial):
        params = dict(trial.parameters_json)
        score = trial.composite_score
        is_metrics = dict(trial.is_metrics_json)
        oos_metrics = dict(trial.oos_metrics_json)
        scorecard = dict(trial.scorecard_json)
        trial_id = trial.id
    else:
        params = dict(trial.get("parameters", {}))
        score = float(trial.get("composite_score", 0.0))
        is_metrics = dict(trial.get("is_metrics", {}))
        oos_metrics = dict(trial.get("oos_metrics", {}))
        scorecard = dict(trial.get("scorecard", {}))
        trial_id = str(trial.get("id", ""))

    matrix_cfg = dict(study.matrix_config_json or {})
    recommended_timeframe = (
        matrix_cfg.get("timeframes", ["1H"])[0] if matrix_cfg.get("timeframes") else "1H"
    )
    recommended_symbols = (
        matrix_cfg.get("symbols", ["BTC-USDT-SWAP"])
        if matrix_cfg.get("symbols")
        else ["BTC-USDT-SWAP"]
    )

    return {
        "target_id": "quantlab",
        "format_version": "quantlab_strategy_config.v1",
        "strategy_id": study.strategy_identifier,
        "study_id": study.id,
        "trial_id": trial_id,
        "optimized_parameters": params,
        "recommended_timeframe": recommended_timeframe,
        "recommended_symbols": recommended_symbols,
        "risk_envelope": {
            "max_drawdown_limit_pct": 25.0,
            "suggested_leverage": 1.0,
            "position_sizing_pct": 10.0,
        },
        "benchmark_metrics": {
            "composite_robustness_score": score,
            "is_sharpe": is_metrics.get("annualized_sharpe"),
            "oos_sharpe": oos_metrics.get("annualized_sharpe"),
            "is_return_pct": is_metrics.get("total_return_pct"),
            "oos_return_pct": oos_metrics.get("total_return_pct"),
            "max_drawdown_pct": is_metrics.get("max_drawdown_pct"),
            "win_rate": is_metrics.get("win_rate"),
            "calmar_ratio": is_metrics.get("calmar_ratio"),
            "verdict": scorecard.get("verdict", "OPTIMIZED_PROMOTABLE"),
        },
        "exported_at": utc_now().isoformat(),
    }


def export_to_bitpro(
    study: OptimizationStudy,
    trial: OptimizationTrial | dict[str, Any],
) -> dict[str, Any]:
    """Format optimized strategy configuration for BitPro runtime/manifest."""
    if isinstance(trial, OptimizationTrial):
        params = dict(trial.parameters_json)
        score = trial.composite_score
        is_metrics = dict(trial.is_metrics_json)
        oos_metrics = dict(trial.oos_metrics_json)
        trial_id = trial.id
    else:
        params = dict(trial.get("parameters", {}))
        score = float(trial.get("composite_score", 0.0))
        is_metrics = dict(trial.get("is_metrics", {}))
        oos_metrics = dict(trial.get("oos_metrics", {}))
        trial_id = str(trial.get("id", ""))

    matrix_cfg = dict(study.matrix_config_json or {})
    timeframe = matrix_cfg.get("timeframes", ["1H"])[0] if matrix_cfg.get("timeframes") else "1H"
    symbols = (
        matrix_cfg.get("symbols", ["BTC-USDT-SWAP"])
        if matrix_cfg.get("symbols")
        else ["BTC-USDT-SWAP"]
    )

    return {
        "target_id": "bitpro",
        "format_version": "bitpro_strategy_manifest.v3",
        "strategy_key": study.strategy_identifier,
        "study_id": study.id,
        "trial_id": trial_id,
        "parameters": params,
        "exchange": "okx",
        "market_type": "swap",
        "timeframe": timeframe,
        "symbols": symbols,
        "evidence": {
            "robustness_score": score,
            "is_sharpe": is_metrics.get("annualized_sharpe"),
            "oos_sharpe": oos_metrics.get("annualized_sharpe"),
            "max_drawdown_pct": is_metrics.get("max_drawdown_pct"),
            "total_return_pct": is_metrics.get("total_return_pct"),
        },
        "exported_at": utc_now().isoformat(),
    }
