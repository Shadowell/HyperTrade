"""
ARC Portfolio MCTS Co-Evolution Engine & Low-Correlation Portfolio Allocator
"""

import math

from pydantic import BaseModel, Field

from hypertrade.arc.contracts import ARCCandidateAttemptV1


class PortfolioConstituent(BaseModel):
    attempt_id: str
    strategy_name: str
    weight: float = 1.0
    historical_returns: list[float] = Field(default_factory=list)


class PortfolioEvaluationResult(BaseModel):
    is_accepted: bool
    max_pairwise_correlation: float
    net_portfolio_sharpe: float
    marginal_sharpe_improvement_pct: float
    reasons: list[str] = Field(default_factory=list)


class ARCPortfolioCoEvolutionEngine:
    """
    Evaluates strategy candidates for joint portfolio co-evolution, enforcing
    pairwise low-correlation thresholds and net portfolio Sharpe ratio enhancement.
    """

    def __init__(
        self,
        max_correlation_threshold: float = 0.35,
        min_sharpe_improvement_pct: float = 0.15,
    ) -> None:
        self.max_correlation_threshold = max_correlation_threshold
        self.min_sharpe_improvement_pct = min_sharpe_improvement_pct

    def compute_pairwise_correlation(
        self, returns_a: list[float], returns_b: list[float]
    ) -> float:
        """
        Computes Pearson correlation coefficient between two strategy return series.
        """
        if not returns_a or not returns_b or len(returns_a) != len(returns_b):
            return 0.0

        n = len(returns_a)
        mean_a = sum(returns_a) / n
        mean_b = sum(returns_b) / n

        cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b, strict=False))
        var_a = sum((a - mean_a) ** 2 for a in returns_a)
        var_b = sum((b - mean_b) ** 2 for b in returns_b)

        std_a = math.sqrt(var_a)
        std_b = math.sqrt(var_b)

        if std_a == 0.0 or std_b == 0.0:
            return 0.0

        return cov / (std_a * std_b)

    def calculate_sharpe(self, returns: list[float]) -> float:
        if not returns:
            return 0.0
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / n if n > 1 else 0.0
        std_r = math.sqrt(var)
        return (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0

    def evaluate_candidate_for_portfolio(
        self,
        candidate: ARCCandidateAttemptV1,
        candidate_returns: list[float],
        existing_constituents: list[PortfolioConstituent],
    ) -> PortfolioEvaluationResult:
        """
        Evaluates whether candidate strategy should be admitted into the portfolio.
        """
        reasons: list[str] = []

        if not existing_constituents:
            sharpe = self.calculate_sharpe(candidate_returns)
            return PortfolioEvaluationResult(
                is_accepted=True,
                max_pairwise_correlation=0.0,
                net_portfolio_sharpe=sharpe,
                marginal_sharpe_improvement_pct=1.0,
                reasons=["Added as initial baseline portfolio constituent"],
            )

        # 1. Compute pairwise correlations
        max_corr = -1.0
        for constituent in existing_constituents:
            corr = self.compute_pairwise_correlation(
                candidate_returns, constituent.historical_returns
            )
            if corr > max_corr:
                max_corr = corr

        if max_corr >= self.max_correlation_threshold:
            reasons.append(
                f"CORRELATION_TOO_HIGH: Max pairwise correlation ({max_corr:.2f}) "
                f"exceeds threshold ({self.max_correlation_threshold:.2f})"
            )
            return PortfolioEvaluationResult(
                is_accepted=False,
                max_pairwise_correlation=max_corr,
                net_portfolio_sharpe=0.0,
                marginal_sharpe_improvement_pct=0.0,
                reasons=reasons,
            )

        # 2. Compute existing portfolio return series
        min_len = min(
            len(c.historical_returns) for c in existing_constituents
        )
        if min_len == 0:
            existing_returns = [0.0]
        else:
            existing_returns = [
                sum(c.historical_returns[i] for c in existing_constituents)
                / len(existing_constituents)
                for i in range(min_len)
            ]

        baseline_sharpe = self.calculate_sharpe(existing_returns)

        # 3. Compute new combined portfolio return series
        comb_len = min(min_len, len(candidate_returns))
        new_constituents_count = len(existing_constituents) + 1
        new_returns = [
            (
                sum(c.historical_returns[i] for c in existing_constituents)
                + candidate_returns[i]
            )
            / new_constituents_count
            for i in range(comb_len)
        ]

        new_sharpe = self.calculate_sharpe(new_returns)
        improvement = (
            (new_sharpe - baseline_sharpe) / abs(baseline_sharpe)
            if baseline_sharpe > 0
            else 1.0
        )

        if improvement < self.min_sharpe_improvement_pct:
            reasons.append(
                f"INSUFFICIENT_SHARPE_IMPROVEMENT: Marginal Sharpe gain ({improvement:.1%}) "
                f"is below threshold ({self.min_sharpe_improvement_pct:.1%})"
            )
            return PortfolioEvaluationResult(
                is_accepted=False,
                max_pairwise_correlation=max_corr,
                net_portfolio_sharpe=new_sharpe,
                marginal_sharpe_improvement_pct=improvement,
                reasons=reasons,
            )

        return PortfolioEvaluationResult(
            is_accepted=True,
            max_pairwise_correlation=max_corr,
            net_portfolio_sharpe=new_sharpe,
            marginal_sharpe_improvement_pct=improvement,
            reasons=["Successfully passed pairwise low-correlation & Sharpe improvement gates"],
        )
