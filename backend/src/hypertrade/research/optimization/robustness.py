"""Walk-Forward validation, parameter sensitivity testing, and composite robustness scoring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hypertrade.research.optimization.matrix import (
    BacktestMatrixEngine,
    MatrixTrialResult,
)
from hypertrade.research.optimization.space import ParameterSpace


@dataclass(frozen=True)
class RobustnessScoreCard:
    composite_score: float
    return_sharpe_score: float
    drawdown_calmar_score: float
    oos_stability_score: float
    sensitivity_flatness_score: float
    is_promotable: bool
    verdict: str
    reasons: tuple[str, ...]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite_score": round(self.composite_score, 2),
            "return_sharpe_score": round(self.return_sharpe_score, 2),
            "drawdown_calmar_score": round(self.drawdown_calmar_score, 2),
            "oos_stability_score": round(self.oos_stability_score, 2),
            "sensitivity_flatness_score": round(self.sensitivity_flatness_score, 2),
            "is_promotable": self.is_promotable,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobustnessScoreCard:
        return cls(
            composite_score=float(data["composite_score"]),
            return_sharpe_score=float(data["return_sharpe_score"]),
            drawdown_calmar_score=float(data["drawdown_calmar_score"]),
            oos_stability_score=float(data["oos_stability_score"]),
            sensitivity_flatness_score=float(data["sensitivity_flatness_score"]),
            is_promotable=bool(data["is_promotable"]),
            verdict=str(data["verdict"]),
            reasons=tuple(data.get("reasons", [])),
            details=dict(data.get("details", {})),
        )


class RobustnessEvaluator:
    """Evaluates trials against overfitting via WFO stability and parameter sensitivity."""

    def __init__(
        self,
        space: ParameterSpace,
        min_trades: int = 5,
        max_drawdown_limit_pct: float = 25.0,
        promotion_threshold: float = 70.0,
    ) -> None:
        self.space = space
        self.min_trades = min_trades
        self.max_drawdown_limit_pct = max_drawdown_limit_pct
        self.promotion_threshold = promotion_threshold

    def evaluate_trial(
        self,
        trial_result: MatrixTrialResult,
        matrix_engine: BacktestMatrixEngine | None = None,
        bars_by_dimension: dict[tuple[str, str], Sequence[Any]] | None = None,
        n_neighbors: int = 3,
    ) -> RobustnessScoreCard:
        """Score a trial by combining IS/OOS stability and parameter plateau test."""
        reasons: list[str] = []
        is_m = trial_result.aggregated_is_metrics
        oos_m = trial_result.aggregated_oos_metrics

        # 1. Return & Sharpe Score (0 - 100)
        sharpe_val = is_m.annualized_sharpe
        if sharpe_val <= 0:
            return_sharpe_score = 0.0
        elif sharpe_val >= 2.5:
            return_sharpe_score = 100.0
        else:
            return_sharpe_score = (sharpe_val / 2.5) * 100.0

        # 2. Drawdown & Calmar Score (0 - 100)
        dd = is_m.max_drawdown_pct
        calmar = is_m.calmar_ratio
        if dd >= self.max_drawdown_limit_pct:
            drawdown_calmar_score = max(0.0, 50.0 - (dd - self.max_drawdown_limit_pct) * 2.0)
            reasons.append(f"high_drawdown:{dd:.1f}%")
        else:
            dd_factor = max(0.0, 1.0 - (dd / self.max_drawdown_limit_pct))
            calmar_factor = min(1.0, calmar / 3.0) if calmar > 0 else 0.0
            drawdown_calmar_score = (dd_factor * 0.6 + calmar_factor * 0.4) * 100.0

        # 3. OOS Stability Score (0 - 100)
        # Compare IS Sharpe with OOS Sharpe
        if is_m.is_inert or oos_m.is_inert or is_m.trade_count < self.min_trades:
            oos_stability_score = 20.0
            reasons.append("insufficient_trades_for_oos_test")
        else:
            if is_m.annualized_sharpe > 0.1:
                ratio = oos_m.annualized_sharpe / is_m.annualized_sharpe
                if ratio >= 0.8:
                    oos_stability_score = 100.0
                elif ratio >= 0.5:
                    oos_stability_score = 75.0
                elif ratio >= 0.2:
                    oos_stability_score = 40.0
                    reasons.append(f"moderate_oos_decay:{ratio:.2f}")
                else:
                    oos_stability_score = max(0.0, ratio * 100.0)
                    reasons.append(f"severe_oos_decay_overfit:{ratio:.2f}")
            else:
                oos_stability_score = 40.0 if oos_m.annualized_sharpe > 0 else 10.0

        # 4. Parameter Sensitivity / Ridge Test (0 - 100)
        sensitivity_score = 75.0  # Default neutral
        if (
            matrix_engine is not None
            and bars_by_dimension is not None
            and not is_m.is_inert
            and is_m.annualized_sharpe > 0.5
        ):
            sensitivity_score = self._run_sensitivity_test(
                trial_result.parameters,
                matrix_engine,
                bars_by_dimension,
                n_neighbors=n_neighbors,
                baseline_sharpe=is_m.annualized_sharpe,
                reasons=reasons,
            )

        # 5. Composite Score Calculation
        composite = (
            0.35 * return_sharpe_score
            + 0.25 * drawdown_calmar_score
            + 0.20 * oos_stability_score
            + 0.20 * sensitivity_score
        )

        # Promotability Gates
        total_trades = is_m.trade_count + oos_m.trade_count
        is_promotable = False
        verdict = "SUBOPTIMAL"

        if total_trades < self.min_trades:
            verdict = "INSUFFICIENT_TRADES"
            reasons.append(f"total_trades_{total_trades}_below_{self.min_trades}")
        elif dd > self.max_drawdown_limit_pct:
            verdict = "HIGH_RISK_REJECTED"
        elif any(
            flag in "".join(reasons) for flag in ("severe_oos_decay_overfit", "knife_edge_overfit")
        ):
            verdict = "OVERFIT_REJECTED"
        elif composite >= self.promotion_threshold:
            verdict = "OPTIMIZED_PROMOTABLE"
            is_promotable = True

        return RobustnessScoreCard(
            composite_score=round(composite, 2),
            return_sharpe_score=round(return_sharpe_score, 2),
            drawdown_calmar_score=round(drawdown_calmar_score, 2),
            oos_stability_score=round(oos_stability_score, 2),
            sensitivity_flatness_score=round(sensitivity_score, 2),
            is_promotable=is_promotable,
            verdict=verdict,
            reasons=tuple(reasons),
            details={
                "is_sharpe": round(is_m.annualized_sharpe, 3),
                "oos_sharpe": round(oos_m.annualized_sharpe, 3),
                "is_return_pct": round(is_m.total_return_pct, 2),
                "oos_return_pct": round(oos_m.total_return_pct, 2),
                "max_drawdown_pct": round(dd, 2),
                "total_trades": total_trades,
            },
        )

    def _run_sensitivity_test(
        self,
        center_params: dict[str, Any],
        matrix_engine: BacktestMatrixEngine,
        bars_by_dimension: dict[tuple[str, str], Sequence[Any]],
        n_neighbors: int,
        baseline_sharpe: float,
        reasons: list[str],
    ) -> float:
        """Perturb center parameters by 5%-10% and test if performance collapses."""
        neighbors: list[dict[str, Any]] = []
        for _ in range(n_neighbors):
            perturbed = self.space.perturb(center_params, ratio=0.10)
            if perturbed != center_params and perturbed not in neighbors:
                neighbors.append(perturbed)

        if not neighbors:
            return 80.0

        neighbor_results = matrix_engine.run_matrix(
            parameter_variants=neighbors,
            bars_by_dimension=bars_by_dimension,
        )

        neighbor_sharpes: list[float] = [
            r.aggregated_is_metrics.annualized_sharpe
            for r in neighbor_results
            if r.is_successful and not r.aggregated_is_metrics.is_inert
        ]

        if not neighbor_sharpes:
            reasons.append("neighbors_inert_knife_edge")
            return 20.0

        avg_neighbor_sharpe = sum(neighbor_sharpes) / len(neighbor_sharpes)
        retention = avg_neighbor_sharpe / max(0.1, baseline_sharpe)

        if retention >= 0.85:
            # Broad robust plateau!
            return 100.0
        elif retention >= 0.65:
            return 80.0
        elif retention >= 0.40:
            reasons.append(f"moderate_sensitivity_decay:{retention:.2f}")
            return 50.0
        else:
            reasons.append(f"knife_edge_overfit:{retention:.2f}")
            return 15.0
