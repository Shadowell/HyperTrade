"""
ARC Vectorized MCTS Two-Stage Screening Engine (Fast Vector Screening + Backtrader Validation)
"""

from typing import Any

import numpy as np


class VectorizedMCTSScreeningEngine:
    """
    Two-Stage Screening Pipeline for High-Throughput MCTS Candidate AST Evaluation:
    Stage 1: Multi-metric Vectorized Fast Screening (Sharpe, Sortino, Calmar, CVaR, Profit Factor).
    Stage 2: Full event-driven Backtrader evaluation for passing top candidates.
    """

    def __init__(
        self,
        min_fast_sharpe: float = 0.8,
        max_fast_drawdown: float = 0.25,
        min_fast_sortino: float = 1.0,
        stage1_pass_ratio: float = 0.20,
    ) -> None:
        self.min_fast_sharpe = min_fast_sharpe
        self.max_fast_drawdown = max_fast_drawdown
        self.min_fast_sortino = min_fast_sortino
        self.stage1_pass_ratio = stage1_pass_ratio

    @staticmethod
    def compute_fast_sortino_ratio(
        strat_rets: np.ndarray, sharpe: float = 0.0
    ) -> float:
        """
        Computes fast Sortino ratio using downside risk standard deviation.
        """
        if len(strat_rets) == 0:
            return 0.0
        mean_ret = float(np.mean(strat_rets))
        downside_rets = strat_rets[strat_rets < 0]
        if len(downside_rets) == 0:
            return round(max(float(sharpe), 2.0), 4) if mean_ret > 0 else 0.0

        downside_std = float(np.std(downside_rets))
        if downside_std <= 1e-9:
            return round(max(float(sharpe), 2.0), 4) if mean_ret > 0 else 0.0

        sortino = (mean_ret / downside_std) * np.sqrt(252 * 24)
        return round(float(sortino), 4)

    @staticmethod
    def compute_fast_calmar_ratio(total_return: float, max_drawdown: float) -> float:
        """
        Computes fast Calmar ratio: total return / max drawdown.
        """
        if max_drawdown <= 1e-6:
            return round(total_return * 10.0, 4) if total_return > 0 else 0.0
        return round(total_return / max_drawdown, 4)

    @staticmethod
    def compute_fast_tail_risk_cvar(strat_rets: np.ndarray, alpha: float = 0.05) -> float:
        """
        Computes 95% Conditional Value-at-Risk (CVaR / Expected Shortfall).
        """
        if len(strat_rets) == 0:
            return 0.0
        sorted_rets = np.sort(strat_rets)
        cutoff = int(np.floor(alpha * len(sorted_rets)))
        if cutoff == 0:
            cutoff = 1
        cvar = float(np.mean(sorted_rets[:cutoff]))
        return round(abs(cvar), 4)

    @staticmethod
    def compute_fast_profit_factor(strat_rets: np.ndarray) -> float:
        """
        Computes fast Profit Factor: Gross Gains / Gross Losses.
        """
        gains = np.sum(strat_rets[strat_rets > 0])
        losses = np.abs(np.sum(strat_rets[strat_rets < 0]))
        if losses <= 1e-9:
            return round(float(gains), 4) if gains > 0 else 1.0
        return round(float(gains / losses), 4)

    def stage1_vector_screening(
        self,
        close_prices: list[float],
        candidate_signals: list[list[int]],
    ) -> list[dict[str, Any]]:
        """
        Stage 1: Multi-metric Vectorized Evaluation using NumPy array math.
        Evaluates candidate signals across Sharpe, Sortino, Calmar, CVaR, Profit Factor.
        """
        if not close_prices or not candidate_signals:
            return []

        prices = np.array(close_prices, dtype=np.float64)
        if len(prices) < 2:
            return []

        # Vectorized log returns
        returns = np.diff(prices) / prices[:-1]

        results: list[dict[str, Any]] = []

        for idx, sigs in enumerate(candidate_signals):
            signals = np.array(sigs[:-1], dtype=np.float64)  # Align with returns
            if len(signals) != len(returns):
                min_len = min(len(signals), len(returns))
                signals = signals[:min_len]
                rets = returns[:min_len]
            else:
                rets = returns

            # Strategy returns
            strat_rets = signals * rets
            if len(strat_rets) == 0:
                continue

            mean_ret = np.mean(strat_rets)
            std_ret = np.std(strat_rets)
            sharpe = (mean_ret / (std_ret + 1e-9)) * np.sqrt(252 * 24)  # Hourly Sharpe

            # Cumulative returns and drawdown
            cum_rets = np.cumsum(strat_rets)
            running_max = np.maximum.accumulate(cum_rets)
            drawdowns = running_max - cum_rets
            max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

            total_ret = float(np.sum(strat_rets))
            sortino = self.compute_fast_sortino_ratio(strat_rets, float(sharpe))
            calmar = self.compute_fast_calmar_ratio(total_ret, max_dd)
            cvar = self.compute_fast_tail_risk_cvar(strat_rets)
            profit_factor = self.compute_fast_profit_factor(strat_rets)

            # Composite multi-metric score
            composite_score = (
                0.4 * float(sharpe) + 0.3 * sortino + 0.2 * calmar + 0.1 * profit_factor
            )

            passed = (
                (sharpe >= self.min_fast_sharpe)
                and (max_dd <= self.max_fast_drawdown)
                and (sortino >= self.min_fast_sortino)
            )

            results.append(
                {
                    "candidate_index": idx,
                    "fast_sharpe": round(float(sharpe), 4),
                    "fast_sortino": sortino,
                    "fast_calmar": calmar,
                    "fast_cvar": cvar,
                    "fast_profit_factor": profit_factor,
                    "fast_drawdown": round(max_dd, 4),
                    "total_return": round(total_ret, 4),
                    "composite_score": round(composite_score, 4),
                    "stage1_passed": passed,
                }
            )

        # Filter passed results
        passed_results = [r for r in results if r["stage1_passed"]]
        # Sort by composite_score descending
        passed_results.sort(key=lambda x: x["composite_score"], reverse=True)

        return passed_results

    def execute_two_stage_pipeline(
        self,
        close_prices: list[float],
        candidate_signals: list[list[int]],
        backtrader_eval_fn: Any,
    ) -> list[dict[str, Any]]:
        """
        Executes full 2-stage pipeline:
        Stage 1: Fast vector multi-metric screening.
        Stage 2: Full Backtrader evaluation on top Stage 1 survivors.
        """
        stage1_survivors = self.stage1_vector_screening(close_prices, candidate_signals)
        final_results: list[dict[str, Any]] = []

        for item in stage1_survivors:
            idx = item["candidate_index"]
            # Run Stage 2 Backtrader evaluation
            stage2_metrics = backtrader_eval_fn(idx, candidate_signals[idx])
            final_results.append(
                {
                    **item,
                    "stage2_backtrader_metrics": stage2_metrics,
                    "stage2_passed": stage2_metrics.get("sharpe", 0.0) >= 1.0,
                }
            )

        return final_results
