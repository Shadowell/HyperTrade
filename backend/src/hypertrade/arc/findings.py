"""Structured adversarial findings shared by the red team and the reflexion ledger.

The red team and the reflexion ledger used to communicate through free-form English
sentences: attacks emitted prose like `"BLACK_SWAN_FAIL: Wide stop-loss failed..."`
while the ledger searched for `"Stop loss is too wide"`. The strings never matched,
so the attribution branch for `red_team_attack_failed` was unreachable and the
`reason_codes` field carried human sentences rather than codes.

A closed enum plus a typed finding makes that class of drift impossible: the ledger
switches on `ARCReasonCode`, and adding a code without a constraint mapping is a
visible gap rather than a silently dead branch.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

# Admissibility thresholds the attacks judge candidates against. Named rather than
# inlined so the ledger's remediation advice and the attack's verdict cannot disagree
# about where the boundary is.
MAX_ADMISSIBLE_STOP_LOSS = 0.10
MIN_ADMISSIBLE_LOOKBACK = 10
MAX_ADMISSIBLE_DRAWDOWN = 0.15
MAX_ADMISSIBLE_SHARPE_DEGRADATION = 0.25


class ARCReasonCode(StrEnum):
    """Stable identifiers for why a candidate failed adversarial review."""

    WIDE_STOP_LOSS = "WIDE_STOP_LOSS"
    SHORT_LOOKBACK_OVERFIT = "SHORT_LOOKBACK_OVERFIT"
    PARAMETER_JITTER_DEGRADATION = "PARAMETER_JITTER_DEGRADATION"
    LIQUIDITY_CRASH_DRAWDOWN = "LIQUIDITY_CRASH_DRAWDOWN"
    FRICTION_NEGATIVE_NET_RETURN = "FRICTION_NEGATIVE_NET_RETURN"
    DRAWDOWN_EXCEEDED = "DRAWDOWN_EXCEEDED"
    SHARPE_TOO_LOW = "SHARPE_TOO_LOW"
    REGIME_UNDERPERFORMANCE = "REGIME_UNDERPERFORMANCE"
    PAPER_OBSERVATION_ANOMALY = "PAPER_OBSERVATION_ANOMALY"
    NO_HISTORICAL_EVIDENCE = "NO_HISTORICAL_EVIDENCE"
    EVIDENCE_REPLAY_FAILED = "EVIDENCE_REPLAY_FAILED"
    INERT_NO_TRADES = "INERT_NO_TRADES"
    OOS_SHARPE_TOO_LOW = "OOS_SHARPE_TOO_LOW"
    OOS_DRAWDOWN_EXCEEDED = "OOS_DRAWDOWN_EXCEEDED"
    IS_OOS_DEGRADATION = "IS_OOS_DEGRADATION"
    PERMANENT_EXPOSURE = "PERMANENT_EXPOSURE"
    WALK_FORWARD_INCONSISTENT = "WALK_FORWARD_INCONSISTENT"
    OOS_SAMPLE_TOO_SMALL = "OOS_SAMPLE_TOO_SMALL"
    # The platform failed, not the candidate. Every self-test failure that did not name
    # a success criterion used to be filed as EVIDENCE_REPLAY_FAILED, so a BitPro outage
    # was recorded as "this strategy cannot execute, regenerate it": a sound candidate
    # was discarded and the ledger learned a lesson that was not true.
    BITPRO_SELF_TEST_UNAVAILABLE = "BITPRO_SELF_TEST_UNAVAILABLE"


class FindingSeverity(StrEnum):
    """Whether an objection disqualifies the candidate or merely annotates it.

    A missing data window says nothing about the candidate, so it must not read as a
    defect; but it also must not vanish, because a verdict reached without evidence has
    to be visible as such downstream.
    """

    BLOCKING = "blocking"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class AttackFinding:
    """One reviewer objection: a stable code, the gate it failed, and the detail."""

    code: ARCReasonCode
    gate: str
    detail: str
    severity: FindingSeverity = FindingSeverity.BLOCKING

    def render(self) -> str:
        """Operator-facing rendering. Never parsed; `code` is the machine contract."""
        return f"{self.code.value}: {self.detail}"


# Every knob a strategy family uses to set its indicator span. Reviewers judge the
# signal horizon, and compiled candidates name that knob after their indicator rather
# than calling it `lookback_period`, so a reader hardwired to one name would treat
# every compiled candidate as having declared no horizon at all.
SPAN_PARAMETER_NAMES: tuple[str, ...] = (
    "lookback_period",
    "slow_window",
    "fast_window",
    "atr_period",
    "zscore_window",
    "rsi_period",
    "channel_period",
    "roc_period",
)


def declared_span(parameters: Mapping[str, float]) -> float | None:
    """The candidate's effective signal span, or None if it declares none.

    Takes the longest declared window: for a two-legged construction such as a moving
    average crossover it is the slow leg that governs how often a signal can fire, so
    the longest window is the turnover proxy as well as the memory requirement.
    """
    spans = [
        value
        for name, value in parameters.items()
        if name in SPAN_PARAMETER_NAMES and value > 0
    ]
    return max(spans) if spans else None


class RemediationMode(StrEnum):
    """Which side of a bound a parameter has to move to."""

    AT_MOST = "at_most"
    AT_LEAST = "at_least"


@dataclass(frozen=True)
class ParameterRemediation:
    """The concrete repair a reviewer objection implies for a named parameter."""

    parameter: str
    mode: RemediationMode
    bound: float

    def repair(self, current: float) -> float:
        """Return the value satisfying the bound, or `current` if already compliant.

        Repairs land strictly inside the bound rather than exactly on it: a candidate
        parked on the boundary passes the threshold check but still fails the
        perturbation gate, because parameter error then crosses the cliff.
        """
        if self.mode is RemediationMode.AT_MOST:
            return min(current, self.bound * _REPAIR_MARGIN)
        return max(current, self.bound / _REPAIR_MARGIN)


# How far inside a violated bound a repair lands. Leaves the mutated candidate room to
# survive the perturbation gate instead of sitting on the admissibility cliff.
_REPAIR_MARGIN = 0.8

# The mutator switches on reason codes rather than on the ledger's Chinese constraint
# prose, so rewording operator-facing advice cannot silently disable mutation.
REMEDIATION_BY_REASON_CODE: dict[ARCReasonCode, ParameterRemediation] = {
    ARCReasonCode.WIDE_STOP_LOSS: ParameterRemediation(
        "stop_loss", RemediationMode.AT_MOST, MAX_ADMISSIBLE_STOP_LOSS
    ),
    ARCReasonCode.LIQUIDITY_CRASH_DRAWDOWN: ParameterRemediation(
        "stop_loss", RemediationMode.AT_MOST, MAX_ADMISSIBLE_STOP_LOSS
    ),
    ARCReasonCode.DRAWDOWN_EXCEEDED: ParameterRemediation(
        "stop_loss", RemediationMode.AT_MOST, MAX_ADMISSIBLE_STOP_LOSS
    ),
    ARCReasonCode.PARAMETER_JITTER_DEGRADATION: ParameterRemediation(
        "stop_loss", RemediationMode.AT_MOST, MAX_ADMISSIBLE_STOP_LOSS
    ),
    ARCReasonCode.SHORT_LOOKBACK_OVERFIT: ParameterRemediation(
        "lookback_period", RemediationMode.AT_LEAST, MIN_ADMISSIBLE_LOOKBACK
    ),
    ARCReasonCode.FRICTION_NEGATIVE_NET_RETURN: ParameterRemediation(
        "lookback_period", RemediationMode.AT_LEAST, MIN_ADMISSIBLE_LOOKBACK
    ),
}


def _numeric_constant(node: ast.expr) -> float | None:
    if not isinstance(node, ast.Constant):
        return None
    raw = node.value
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _research_parameter_lookup(node: ast.Call) -> tuple[str, float] | None:
    """Recognise the `params.get("name", default)` form emitted by the codegen.

    Generated strategies resolve their knobs from the research parameter map instead
    of module-level literals, so a reader that only understands `name = 0.12` sees a
    compiled candidate as having declared nothing at all.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "get":
        return None
    if len(node.args) != 2:
        return None
    name_node = node.args[0]
    if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
        return None
    default = _numeric_constant(node.args[1])
    if default is None:
        return None
    return name_node.value, default


def extract_strategy_parameters(code: str) -> dict[str, float]:
    """Read numeric parameter declarations out of strategy source via AST.

    Replaces substring probes like `"stop_loss = 0.12" in code`, which only ever
    recognised the two literals the demo happened to emit and silently treated every
    other value — including a deliberately reckless one — as acceptable. Walking the
    tree also makes the read insensitive to formatting and comments, and covers both
    hand-written literals and codegen's `params.get(...)` defaults.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    parameters: dict[str, float] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            lookup = _research_parameter_lookup(node)
            if lookup is not None:
                parameters[lookup[0]] = lookup[1]
            continue
        if not isinstance(node, ast.Assign):
            continue
        value = _numeric_constant(node.value)
        if value is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                parameters[target.id] = value
    return parameters
