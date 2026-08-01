"""
ARC Vectorized MCTS Two-Stage Screening Engine (Fast Vector Screening + Backtrader Validation)
"""

from typing import Any

import numpy as np


class VectorizedMCTSScreeningEngine:
    """
    Two-Stage Screening Pipeline for High-Throughput MCTS Candidate AST Evaluation:
    Stage 1: Vectorized fast screening (filters 90% of low-performing candidates in milliseconds).
    Stage 2: Full event-driven Backtrader evaluation for passing top candidates.
    """

    def __init__(
        self,
        min_fast_sharpe: float = 0.8,
        max_fast_drawdown: float = 0.25,
        stage1_pass_ratio: float = 0.20,
    ) -> None:
        self.min_fast_sharpe = min_fast_sharpe
        self.max_fast_drawdown = max_fast_drawdown
        self.stage1_pass_ratio = stage1_pass_ratio

    def stage1_vector_screening(
        self,
        close_prices: list[float],
        candidate_signals: list[list[int]],
    ) -> list[dict[str, Any]]:
        """
        Stage 1: Vectorized vectorized evaluation using NumPy array math.
        Evaluates N candidate strategy signal series in parallel.
        Returns passing candidates with fast metrics.
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
                # Fallback truncate to minimum length
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
            max_dd = np.max(drawdowns) if len(drawdowns) > 0 else 0.0

            passed = (sharpe >= self.min_fast_sharpe) and (max_dd <= self.max_fast_drawdown)

            results.append(
                {
                    "candidate_index": idx,
                    "fast_sharpe": round(float(sharpe), 4),
                    "fast_drawdown": round(float(max_dd), 4),
                    "total_return": round(float(np.sum(strat_rets)), 4),
                    "stage1_passed": passed,
                }
            )

        # Filter passed results
        passed_results = [r for r in results if r["stage1_passed"]]
        # Sort by fast_sharpe descending
        passed_results.sort(key=lambda x: x["fast_sharpe"], reverse=True)

        return passed_results

    def execute_two_stage_pipeline(
        self,
        close_prices: list[float],
        candidate_signals: list[list[int]],
        backtrader_eval_fn: Any,
    ) -> list[dict[str, Any]]:
        """
        Executes full 2-stage pipeline:
        Stage 1: Fast vector screening.
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
