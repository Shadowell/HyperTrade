"""
ARC Red-Blue Adversarial Game Engine & Monte Carlo Overfitting Attack Matrix
"""

import hashlib
import random
from collections.abc import Mapping
from typing import Any

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.evidence import HistoricalEvidenceGate
from hypertrade.arc.findings import (
    MAX_ADMISSIBLE_DRAWDOWN,
    MAX_ADMISSIBLE_SHARPE_DEGRADATION,
    MAX_ADMISSIBLE_STOP_LOSS,
    MIN_ADMISSIBLE_LOOKBACK,
    ARCReasonCode,
    AttackFinding,
    FindingSeverity,
    declared_span,
    extract_strategy_parameters,
)
from hypertrade.research.codegen import FAMILIES, generate_strategy


class BlueTeamQuant:
    """
    Blue Team Agent (Inventor): Proposes strategy hypotheses, code AST mutations,
    and higher-order factor integrations targeting user objectives.

    Proposals are compiled by `research.codegen` from the objective's own wording, so
    two different mandates yield two different trading logics. The previous template
    emitted one ATR breakout body for every objective, which made the whole ARC search
    a parameter tweak on a single strategy no matter what the operator asked for.
    """

    def propose_initial_strategy(
        self,
        objective: str,
        symbol: str,
        *,
        timeframe: str = "1H",
        family_key: str | None = None,
        parameter_bounds: Mapping[str, Mapping[str, float]] | None = None,
    ) -> ARCCandidateAttemptV1:
        spec = self.build_spec(
            objective, symbol, timeframe=timeframe, parameter_bounds=parameter_bounds
        )
        if family_key is not None:
            spec["family_key"] = family_key
        generated = generate_strategy(spec)
        # Ids are derived from the mandate so that re-proposing the same objective is
        # idempotent while two objectives never collide on one MCTS root.
        digest = hashlib.blake2s(
            f"{objective}|{symbol}|{timeframe}|{generated.family}".encode(), digest_size=3
        )
        token = digest.hexdigest()
        return ARCCandidateAttemptV1(
            attempt_id=f"att_blue_{token}",
            candidate_id=f"cand_blue_{token}",
            hypothesis=f"{generated.family} ({generated.direction}) on {symbol}: {objective}",
            strategy_code=generated.code,
            strategy_spec={
                "source": "blue_team_codegen",
                # The evidence gate replays the candidate, so the window it must be
                # judged on travels with the candidate rather than being re-derived.
                "symbol": symbol,
                "timeframe": timeframe,
                "family": generated.family,
                "direction": generated.direction,
                "risk_overlays": list(generated.risk_overlays),
                "tunable_parameters": dict(generated.tunable_parameters),
                "parameter_bounds": dict(generated.parameter_bounds),
            },
        )

    def propose_diverse_frontier(
        self,
        objective: str,
        symbol: str,
        count: int,
        *,
        timeframe: str = "1H",
        parameter_bounds: Mapping[str, Mapping[str, float]] | None = None,
    ) -> list[ARCCandidateAttemptV1]:
        """Seed the search with `count` structurally different hypotheses.

        The objective's own reading comes first; the remaining slots walk the family
        catalogue in declaration order so the frontier is reproducible. Without this
        the search could only ever tune the parameters of whichever single family the
        objective's wording happened to match.
        """
        primary = self.propose_initial_strategy(
            objective, symbol, timeframe=timeframe, parameter_bounds=parameter_bounds
        )
        frontier = [primary]
        for family in FAMILIES:
            if len(frontier) >= max(1, count):
                break
            if family.key == primary.strategy_spec["family"]:
                continue
            frontier.append(
                self.propose_initial_strategy(
                    objective,
                    symbol,
                    timeframe=timeframe,
                    family_key=family.key,
                    parameter_bounds=parameter_bounds,
                )
            )
        return frontier

    @staticmethod
    def build_spec(
        objective: str,
        symbol: str,
        *,
        timeframe: str = "1H",
        parameter_bounds: Mapping[str, Mapping[str, float]] | None = None,
    ) -> dict[str, Any]:
        """Project an ARC objective onto the research spec the codegen consumes.

        The objective text is repeated across the fields the family and direction
        selectors read, because ARC goals arrive as one free-text mandate rather than
        the structured entry/exit prose a research mandate carries.
        """
        return {
            "schema_version": "research_strategy_spec.v1",
            "strategy_key": f"arc_{symbol.replace('-', '_').casefold()}",
            "title": f"ARC candidate for {symbol}",
            "hypothesis": objective,
            "entry_logic": objective,
            "exit_logic": objective,
            "symbols": [symbol],
            "timeframes": [timeframe],
            "strategy_category": "ARC",
            "risk_conditions": ["bounded notional", "stop loss"],
            "data_requirements": ["ohlcv"],
            "invalidation_conditions": ["insufficient data"],
            "parameter_bounds": dict(parameter_bounds or {}),
        }


class MonteCarloParamPerturbationAttack:
    """Parametric risk proxy: jitters declared parameters to expose curve fitting.

    NOT a historical backtest. The projection is driven by the candidate's declared
    risk parameters, so it measures whether the parameterisation is defensible, not
    whether the trading logic has edge. A strategy with sound parameters and no signal
    will still pass this gate; catching that requires the real backtest engine.

    The projection is continuous in stop-loss width rather than a two-value lookup, so
    every value is judged rather than only the two literals the demo emitted.
    """

    JITTER_TRIALS = 100
    JITTER_SIGMA = 0.15
    ADVERSE_PERCENTILE = 5

    @staticmethod
    def _project(stop_loss: float) -> tuple[float, float]:
        """Project (Sharpe, drawdown) from a stop-loss width.

        Continuous in `stop_loss` so every value is judged, and so perturbing the
        parameter actually moves the projection.
        """
        overshoot = max(0.0, stop_loss - MAX_ADMISSIBLE_STOP_LOSS) / MAX_ADMISSIBLE_STOP_LOSS
        return (
            max(0.15, 1.85 / (1.0 + 2.0 * overshoot)),
            min(0.60, 0.07 * (1.0 + 1.6 * overshoot)),
        )

    def attack(
        self, attempt: ARCCandidateAttemptV1
    ) -> tuple[bool, AttackFinding | None, dict[str, float]]:
        parameters = extract_strategy_parameters(attempt.strategy_code)
        stop_loss = parameters.get("stop_loss", MAX_ADMISSIBLE_STOP_LOSS * 1.2)
        baseline_sharpe, baseline_dd = self._project(stop_loss)

        # Jitter the declared parameter and re-project, rather than jittering the
        # outcome directly. Perturbing the outcome around its own mean made the
        # median converge on the baseline, so the degradation gate could never fire
        # and measured only the jitter width. Perturbing the input instead exposes
        # candidates parked against an admissibility cliff, where a small parameter
        # error crosses the boundary.
        rng = random.Random(42)
        sharpes: list[float] = []
        drawdowns: list[float] = []
        for _ in range(self.JITTER_TRIALS):
            jittered = max(1e-4, stop_loss * rng.gauss(1.0, self.JITTER_SIGMA))
            sharpe, drawdown = self._project(jittered)
            sharpes.append(sharpe)
            drawdowns.append(drawdown)

        sharpes.sort()
        adverse_sharpe = sharpes[self.ADVERSE_PERCENTILE]
        max_dd = max(drawdowns)
        degradation = (
            (baseline_sharpe - adverse_sharpe) / baseline_sharpe if baseline_sharpe > 0 else 1.0
        )

        metrics = {
            "baseline_sharpe": baseline_sharpe,
            "median_perturbed_sharpe": sharpes[self.JITTER_TRIALS // 2],
            "adverse_perturbed_sharpe": adverse_sharpe,
            "sharpe_degradation": degradation,
            "max_perturbed_drawdown": max_dd,
            "declared_stop_loss": stop_loss,
        }

        if stop_loss > MAX_ADMISSIBLE_STOP_LOSS:
            return (
                False,
                AttackFinding(
                    code=ARCReasonCode.WIDE_STOP_LOSS,
                    gate="parameter_perturbation",
                    detail=(
                        f"declared stop_loss {stop_loss:.1%} exceeds the admissible "
                        f"{MAX_ADMISSIBLE_STOP_LOSS:.0%} ceiling; perturbed drawdown "
                        f"reached {max_dd:.1%}"
                    ),
                ),
                metrics,
            )
        if degradation > MAX_ADMISSIBLE_SHARPE_DEGRADATION or max_dd > MAX_ADMISSIBLE_DRAWDOWN:
            return (
                False,
                AttackFinding(
                    code=ARCReasonCode.PARAMETER_JITTER_DEGRADATION,
                    gate="parameter_perturbation",
                    detail=(
                        f"Sharpe degraded {degradation:.1%} under parameter jitter and "
                        f"drawdown reached {max_dd:.1%}"
                    ),
                ),
                metrics,
            )
        return True, None, metrics


class BlackSwanScenarioReplayAttack:
    """Projects candidate risk parameters onto extreme liquidity crash conditions.

    NOT a replay of historical bars; it judges whether the declared loss guard could
    have survived a gap of crash magnitude. Wiring this to real 2020-03-12 / LUNA
    candles requires the backtest engine.
    """

    CRASH_GAP = 0.18

    def attack(self, attempt: ARCCandidateAttemptV1) -> tuple[bool, AttackFinding | None]:
        parameters = extract_strategy_parameters(attempt.strategy_code)
        stop_loss = parameters.get("stop_loss", MAX_ADMISSIBLE_STOP_LOSS * 1.2)
        if stop_loss > MAX_ADMISSIBLE_STOP_LOSS:
            return False, AttackFinding(
                code=ARCReasonCode.LIQUIDITY_CRASH_DRAWDOWN,
                gate="black_swan_replay",
                detail=(
                    f"stop_loss {stop_loss:.1%} leaves the position exposed to a "
                    f"{self.CRASH_GAP:.0%} crash gap"
                ),
            )
        return True, None


class StochasticFrictionStressAttack:
    """Flags parameterisations whose turnover cannot survive slippage and fees.

    Uses the declared lookback as a turnover proxy: a very short lookback implies
    frequent re-entry, which friction erodes first.
    """

    def attack(self, attempt: ARCCandidateAttemptV1) -> tuple[bool, AttackFinding | None]:
        parameters = extract_strategy_parameters(attempt.strategy_code)
        span = declared_span(parameters)
        if span is not None and span < MIN_ADMISSIBLE_LOOKBACK:
            return False, AttackFinding(
                code=ARCReasonCode.SHORT_LOOKBACK_OVERFIT,
                gate="friction_stress",
                detail=(
                    f"declared signal span {span:.0f} bars is below the admissible "
                    f"{MIN_ADMISSIBLE_LOOKBACK}; implied turnover produces negative "
                    "net return under slippage stress"
                ),
            )
        return True, None


class RedTeamQuant:
    """
    Red Team Agent (Falsifier / Adversary): Orchestrates Monte Carlo, Black Swan,
    and Stochastic Friction attacks against candidate strategies.
    """

    def __init__(self, evidence_gate: HistoricalEvidenceGate | None = None) -> None:
        self.mc_attack = MonteCarloParamPerturbationAttack()
        self.bs_attack = BlackSwanScenarioReplayAttack()
        self.friction_attack = StochasticFrictionStressAttack()
        # The three parametric attacks only read what the candidate declares about
        # itself. The evidence gate is the one tier that replays it on prices.
        self.evidence_gate = evidence_gate or HistoricalEvidenceGate()

    def evaluate_adversarial_attack(
        self, attempt: ARCCandidateAttemptV1
    ) -> tuple[bool, dict[str, Any], list[AttackFinding]]:
        findings: list[AttackFinding] = []

        mc_pass, mc_finding, mc_metrics = self.mc_attack.attack(attempt)
        if not mc_pass and mc_finding is not None:
            findings.append(mc_finding)

        bs_pass, bs_finding = self.bs_attack.attack(attempt)
        if not bs_pass and bs_finding is not None:
            findings.append(bs_finding)

        friction_pass, friction_finding = self.friction_attack.attack(attempt)
        if not friction_pass and friction_finding is not None:
            findings.append(friction_finding)

        verdict = self.evidence_gate.evaluate(attempt)
        findings.extend(verdict.findings)

        # Advisories annotate the verdict without disqualifying the candidate: a window
        # that could not be fetched says nothing about the strategy.
        passed = not any(
            finding.severity is FindingSeverity.BLOCKING for finding in findings
        )
        observed_metrics: dict[str, Any] = {
            "max_drawdown_after_attack": mc_metrics["max_perturbed_drawdown"],
            "sharpe_after_attack": mc_metrics["adverse_perturbed_sharpe"],
            "sharpe_degradation": mc_metrics["sharpe_degradation"],
            "declared_stop_loss": mc_metrics["declared_stop_loss"],
            "liquidity_stress_passed": bs_pass and friction_pass,
            "advisories": [
                finding.render()
                for finding in findings
                if finding.severity is FindingSeverity.ADVISORY
            ],
        }
        observed_metrics.update(verdict.metrics)

        # The win rate is read off the replayed trades. It used to be assigned 0.65 on a
        # pass and 0.42 on a failure, which is a restatement of the verdict wearing the
        # costume of a measurement — and it flowed onward into the paper handoff.
        win_rate = verdict.metrics.get("out_of_sample_win_rate")
        if win_rate is not None:
            observed_metrics["win_rate"] = win_rate

        # Rank on held-out evidence when there is any. `sharpe_after_attack` is projected
        # from the declared parameters, so ordering candidates by it means the search
        # picks its winner by what the candidate says about itself.
        oos_sharpe = verdict.metrics.get("out_of_sample_sharpe")
        observed_metrics["ranking_sharpe"] = (
            float(oos_sharpe)
            if oos_sharpe is not None
            else float(mc_metrics["adverse_perturbed_sharpe"])
        )
        observed_metrics["ranking_basis"] = (
            "out_of_sample" if oos_sharpe is not None else "declared_projection"
        )
        return passed, observed_metrics, findings


class ARCAdversarialEngine:
    """
    Orchestrates the Red-Blue adversarial game session for a strategy attempt.
    """

    def __init__(self, evidence_gate: HistoricalEvidenceGate | None = None) -> None:
        self.blue_team = BlueTeamQuant()
        self.red_team = RedTeamQuant(evidence_gate=evidence_gate)

    def run_adversarial_session(
        self, attempt: ARCCandidateAttemptV1
    ) -> tuple[bool, dict[str, Any], list[AttackFinding]]:
        return self.red_team.evaluate_adversarial_attack(attempt)
