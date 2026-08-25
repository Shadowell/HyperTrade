"""Deterministic strategy code generation from a research strategy spec.

Turns a `research_strategy_spec.v1` draft into self-contained BitPro `BaseStrategy`
Python. Determinism is a hard requirement, not a style choice: `ExperimentLedger`
fingerprints candidates by `strategy_code_sha256`, so the same spec must always
compile to byte-identical source or replay and idempotent reuse both break.

Generated code runs inside the BitPro strategy runtime, which does not have
`hypertrade` importable. Every indicator is therefore inlined into the emitted
class rather than imported from `hypertrade.strategy.operators`.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Substring guards applied to generated and operator-supplied strategy code alike.
# Matched case-insensitively against the whole source; kept as substrings rather
# than AST checks so obfuscated spellings still trip the gate.
FORBIDDEN_CODE_TOKENS: dict[str, tuple[str, ...]] = {
    "network_access": ("socket", "requests", "urllib", "httpx", "aiohttp"),
    "filesystem_access": ("open(", "pathlib", "os.", "shutil"),
    "process_execution": ("subprocess", "os.system", "popen("),
    "dynamic_execution": ("eval(", "exec(", "compile(", "__import__("),
    "secret_access": ("environ", "getenv", "api_key", "secret", "password"),
    "unbounded_loop": ("while true", "while 1"),
}

_BASE_STRATEGY_SUBCLASS = re.compile(r"class\s+\w+\s*\([^)]*BaseStrategy[^)]*\)\s*:")


_CANONICAL_BASE_STRATEGY_MODULE = "app.core.execution.base_strategy"

# The BaseStrategy method surface strategies may call on `self`: the contract
# methods BitPro actually provides, plus anything the code defines itself.
# Unknown self.<method>() calls are rejected because BitPro's upload checker
# refuses deprecated/shortcuts (open_long, place_order, ...) that once existed
# or never did — each one previously cost a wasted platform upload to discover.
_CONTRACT_METHODS = frozenset(
    {
        "open_contract",
        "close_contract",
        "symbols",
        "on_init",
        "on_bar",
    }
)


def _basestrategy_import_modules(code: str) -> set[str]:
    """Modules from which the code imports a BaseStrategy symbol (AST-based)."""
    import ast

    modules: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return modules
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported = {alias.name for alias in node.names}
            if "BaseStrategy" in imported:
                modules.add(node.module)
    return modules


def static_code_rejections(code: str) -> list[str]:
    """Return sorted reason codes for why `code` may not be run as a strategy.

    Single source of truth for the static gate: both operator-supplied discovery
    proposals and HyperTrade-generated candidates go through this, so a construct
    banned for one path can never be smuggled in via the other.
    """
    lowered = code.casefold()
    reasons: list[str] = []
    if len(_BASE_STRATEGY_SUBCLASS.findall(code)) != 1:
        reasons.append("code_requires_single_basestrategy_subclass")
    else:
        # BitPro's upload checker rejects BaseStrategy imports from any module
        # other than the canonical one; catch it here so the rejection surfaces
        # as a reason code instead of a failed platform upload.
        import_modules = _basestrategy_import_modules(code)
        if import_modules and _CANONICAL_BASE_STRATEGY_MODULE not in import_modules:
            reasons.append("code_requires_canonical_basestrategy_import")
    for reason, tokens in FORBIDDEN_CODE_TOKENS.items():
        if any(token in lowered for token in tokens):
            reasons.append(reason)
    reasons.extend(_unknown_self_method_calls(code))
    return sorted(set(reasons))


def _unknown_self_method_calls(code: str) -> list[str]:
    """Reject self.<method>() calls outside the contract surface."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
    unknown: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            name = node.func.attr
            if name in _CONTRACT_METHODS or name in defined or name.startswith("__"):
                continue
            unknown.add(name)
    return sorted(f"code_uses_unknown_base_strategy_method:{name}" for name in unknown)


class StrategyCodegenError(RuntimeError):
    """Raised when a spec cannot be compiled into admissible strategy code."""


Direction = str  # "long_only" | "short_only" | "long_short"

_LONG_ONLY_MARKERS = (
    "long only",
    "long-only",
    "only long",
    "no short",
    "no shorting",
    "without shorting",
    "禁止做空",
    "不做空",
    "仅做多",
    "只做多",
    "纯做多",
)
_SHORT_ONLY_MARKERS = (
    "short only",
    "short-only",
    "only short",
    "no long",
    "仅做空",
    "只做空",
    "纯做空",
    "禁止做多",
    "不做多",
)
_BIDIRECTIONAL_MARKERS = (
    "short",
    "both directions",
    "long and short",
    "做空",
    "多空",
    "双向",
)


# Width of the synthesized sensitivity neighbourhood, as a fraction of the default.
# The matrix and robustness plan both probe the *midpoint* of a parameter's bounds,
# so bounds spanning a family's full admissible range would place the probe far from
# the baseline and measure a different strategy rather than local stability. Anchoring
# the range at the default makes that midpoint a genuine neighbour.
_NEIGHBOURHOOD_FRACTION = 0.5


@dataclass(frozen=True)
class TunableParameter:
    """A parameter the research matrix is allowed to perturb."""

    name: str
    default: float
    minimum: float
    maximum: float
    integral: bool = True

    def clamp(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, value))

    def neighbourhood(self) -> tuple[float, float]:
        """Sensitivity range anchored at the default, clamped to the hard limits."""
        reach = abs(self.default) * _NEIGHBOURHOOD_FRACTION
        if reach <= 0.0:
            # A zero default has no proportional neighbourhood; step off the floor.
            reach = max(1.0, (self.maximum - self.minimum) * 0.1)
        return self.clamp(self.default), self.clamp(self.default + reach)


SIGNATURE_WEIGHT = 10
THEME_WEIGHT = 1


@dataclass(frozen=True)
class StrategyFamily:
    """A distinct trading logic shape with its own indicators and signal rules.

    Vocabulary is split into two tiers because generic style words leak across
    families: a spec can say "breakout" while naming ATR as the actual mechanism.
    `signature` tokens name a concrete indicator and dominate selection; `theme`
    tokens only describe the style and act as tie-breakers.
    """

    key: str
    label: str
    signature: tuple[str, ...]
    theme: tuple[str, ...]
    parameters: tuple[TunableParameter, ...]
    helpers: tuple[str, ...]
    span_expression: str
    needs_high_low: bool = False
    supports_short: bool = True

    def match_score(self, corpus: str) -> int:
        return _tier_score(self.signature, corpus, SIGNATURE_WEIGHT) + _tier_score(
            self.theme, corpus, THEME_WEIGHT
        )

    def signal_lines(self, direction: Direction) -> list[str]:
        block: SignalBlock = _SIGNAL_EMITTERS[self.key](self, direction)
        return list(block.setup) + _emit_state_machine(block, direction)


def _tier_score(tokens: tuple[str, ...], corpus: str, weight: int) -> int:
    """Score matched tokens, ignoring any contained in a longer sibling match.

    Prevents double counting when a phrase and its own substring are both listed,
    e.g. "通道突破" should not also score via "突破".
    """
    matched = [token for token in tokens if token in corpus]
    effective = [
        token
        for token in matched
        if not any(other != token and token in other for other in matched)
    ]
    return weight * len(effective)


def _p(name: str) -> str:
    """Attribute name for a tunable parameter on the generated class."""
    return f"self.p_{name}"


@dataclass(frozen=True)
class SignalBlock:
    """Indicator setup plus the boolean expressions a family trades on.

    Conditions are expressions rather than pre-assigned locals so the state machine
    can inline only the ones the resolved direction uses. Emitting all four would
    leave unused locals in one-sided strategies, which BitPro's ruff gate rejects.
    """

    setup: tuple[str, ...]
    long_entry: str
    short_entry: str
    long_exit: str | None = None
    short_exit: str | None = None


def _emit_ma_crossover(family: StrategyFamily, direction: Direction) -> SignalBlock:
    return SignalBlock(
        setup=(
            "        values = list(self._closes[symbol])",
            f"        fast_ma = self._mean(values[-{_p('fast_window')}:])",
            f"        slow_ma = self._mean(values[-{_p('slow_window')}:])",
        ),
        long_entry="fast_ma > slow_ma",
        short_entry="fast_ma < slow_ma",
    )


def _emit_atr_breakout(family: StrategyFamily, direction: Direction) -> SignalBlock:
    return SignalBlock(
        setup=(
            "        values = list(self._closes[symbol])",
            "        highs = list(self._highs[symbol])",
            "        lows = list(self._lows[symbol])",
            f"        atr = self._atr(highs, lows, values, {_p('atr_period')})",
            f"        middle = self._mean(values[-{_p('atr_period')}:])",
            f"        upper = middle + ({_p('atr_multiplier')} * atr)",
            f"        lower = middle - ({_p('atr_multiplier')} * atr)",
        ),
        long_entry="close > upper",
        short_entry="close < lower",
        long_exit="close < middle",
        short_exit="close > middle",
    )


def _emit_mean_reversion_zscore(family: StrategyFamily, direction: Direction) -> SignalBlock:
    return SignalBlock(
        setup=(
            "        values = list(self._closes[symbol])",
            f"        window = values[-{_p('zscore_window')}:]",
            "        avg = self._mean(window)",
            "        dispersion = self._stdev(window)",
            "        if dispersion <= 0.0:",
            "            return None",
            "        zscore = (close - avg) / dispersion",
        ),
        long_entry=f"zscore <= -{_p('entry_zscore')}",
        short_entry=f"zscore >= {_p('entry_zscore')}",
        long_exit=f"zscore >= -{_p('exit_zscore')}",
        short_exit=f"zscore <= {_p('exit_zscore')}",
    )


def _emit_rsi_reversal(family: StrategyFamily, direction: Direction) -> SignalBlock:
    return SignalBlock(
        setup=(
            "        values = list(self._closes[symbol])",
            f"        rsi = self._rsi(values, {_p('rsi_period')})",
        ),
        long_entry=f"rsi <= {_p('oversold_level')}",
        short_entry=f"rsi >= {_p('overbought_level')}",
        long_exit="rsi >= 50.0",
        short_exit="rsi <= 50.0",
    )


def _emit_donchian_breakout(family: StrategyFamily, direction: Direction) -> SignalBlock:
    return SignalBlock(
        setup=(
            "        highs = list(self._highs[symbol])",
            "        lows = list(self._lows[symbol])",
            f"        prior_highs = highs[-({_p('channel_period')} + 1):-1]",
            f"        prior_lows = lows[-({_p('channel_period')} + 1):-1]",
            "        if not prior_highs or not prior_lows:",
            "            return None",
            "        channel_high = max(prior_highs)",
            "        channel_low = min(prior_lows)",
        ),
        long_entry="close > channel_high",
        short_entry="close < channel_low",
    )


def _emit_momentum_roc(family: StrategyFamily, direction: Direction) -> SignalBlock:
    return SignalBlock(
        setup=(
            "        values = list(self._closes[symbol])",
            f"        reference = values[-({_p('roc_period')} + 1)]",
            "        if reference <= 0.0:",
            "            return None",
            "        roc = (close - reference) / reference",
            f"        threshold = {_p('roc_threshold')} / 100.0",
        ),
        long_entry="roc >= threshold",
        short_entry="roc <= -threshold",
    )


def _emit_state_machine(block: SignalBlock, direction: Direction) -> list[str]:
    """Emit the flat/long/short transition block shared by every family.

    Exit conditions fall back to the opposing entry condition so a family that only
    declares one threshold pair still closes positions instead of holding forever.
    """
    long_close = block.long_exit or block.short_entry
    short_close = block.short_exit or block.long_entry
    lines = ["        if state == 0:"]
    if direction in ("long_only", "long_short"):
        lines += [
            f"            if {block.long_entry}:",
            '                await self._enter(symbol, "long", close)',
            "                return None",
        ]
    if direction in ("short_only", "long_short"):
        lines += [
            f"            if {block.short_entry}:",
            '                await self._enter(symbol, "short", close)',
            "                return None",
        ]
    if direction == "short_only":
        lines += [
            f"        if state < 0 and {short_close}:",
            '            await self._exit(symbol, "short")',
        ]
    elif direction == "long_only":
        lines += [
            f"        if state > 0 and {long_close}:",
            '            await self._exit(symbol, "long")',
        ]
    else:
        lines += [
            f"        if state > 0 and {long_close}:",
            '            await self._exit(symbol, "long")',
            f"        elif state < 0 and {short_close}:",
            '            await self._exit(symbol, "short")',
        ]
    return lines


_SIGNAL_EMITTERS: dict[str, Any] = {
    "ma_crossover": _emit_ma_crossover,
    "atr_breakout": _emit_atr_breakout,
    "mean_reversion_zscore": _emit_mean_reversion_zscore,
    "rsi_reversal": _emit_rsi_reversal,
    "donchian_breakout": _emit_donchian_breakout,
    "momentum_roc": _emit_momentum_roc,
}


FAMILIES: tuple[StrategyFamily, ...] = (
    StrategyFamily(
        key="ma_crossover",
        label="moving-average crossover trend follower",
        signature=(
            "moving average",
            "moving_average",
            "crossover",
            "cross over",
            "golden cross",
            "均线",
            "金叉",
            "死叉",
        ),
        theme=("trend follow", "trend_following", "trend", "趋势跟踪", "趋势"),
        parameters=(
            TunableParameter("fast_window", 8, 2, 120),
            TunableParameter("slow_window", 32, 3, 400),
        ),
        helpers=("_mean",),
        span_expression="max(self.p_slow_window, self.p_fast_window) + 1",
    ),
    StrategyFamily(
        key="atr_breakout",
        label="ATR volatility channel breakout",
        signature=(
            "atr",
            "average true range",
            "keltner",
            "波动率通道",
            "波动率突破",
            "真实波幅",
        ),
        theme=(
            "volatility channel",
            "volatility breakout",
            "volatility regime",
            "volatility",
            "波动",
        ),
        parameters=(
            TunableParameter("atr_period", 14, 3, 200),
            TunableParameter("atr_multiplier", 2.0, 0.5, 6.0, integral=False),
        ),
        helpers=("_mean", "_atr"),
        span_expression="self.p_atr_period + 2",
        needs_high_low=True,
    ),
    StrategyFamily(
        key="mean_reversion_zscore",
        label="z-score mean reversion",
        signature=(
            "mean reversion",
            "mean-reversion",
            "mean_reversion",
            "z-score",
            "zscore",
            "z score",
            "vwap",
            "均值回归",
            "标准分",
            "标准差",
        ),
        theme=("reversion", "overextended", "回归", "偏离"),
        parameters=(
            TunableParameter("zscore_window", 20, 5, 200),
            TunableParameter("entry_zscore", 2.0, 0.5, 5.0, integral=False),
            TunableParameter("exit_zscore", 0.5, 0.0, 3.0, integral=False),
        ),
        helpers=("_mean", "_stdev"),
        span_expression="self.p_zscore_window + 1",
    ),
    StrategyFamily(
        key="rsi_reversal",
        label="RSI oscillator reversal",
        signature=(
            "rsi",
            "relative strength",
            "overbought",
            "oversold",
            "超买",
            "超卖",
            "相对强弱",
        ),
        theme=("oscillator", "振荡", "摆动"),
        parameters=(
            TunableParameter("rsi_period", 14, 3, 100),
            TunableParameter("oversold_level", 30, 5, 49),
            TunableParameter("overbought_level", 70, 51, 95),
        ),
        helpers=("_rsi",),
        span_expression="self.p_rsi_period + 2",
    ),
    StrategyFamily(
        key="donchian_breakout",
        label="Donchian channel breakout",
        signature=(
            "donchian",
            "turtle",
            "highest high",
            "channel breakout",
            "海龟",
            "新高",
            "唐奇安",
            # Names the family, so it belongs with the signature tier. Filed as a theme
            # it scored no higher than the incidental "趋势" in "捕捉下行趋势", and the
            # tie went to whichever family was declared first: a mandate that asked for
            # a channel breakout in Chinese got a moving-average crossover.
            "通道突破",
        ),
        theme=("breakout", "break out", "range break", "突破", "区间"),
        parameters=(TunableParameter("channel_period", 20, 3, 300),),
        helpers=(),
        span_expression="self.p_channel_period + 2",
        needs_high_low=True,
    ),
    StrategyFamily(
        key="momentum_roc",
        label="rate-of-change momentum",
        signature=("rate of change", "rate_of_change", "roc", "变化率", "涨跌幅"),
        theme=("momentum", "impulse", "acceleration", "动量", "加速"),
        parameters=(
            TunableParameter("roc_period", 12, 2, 200),
            TunableParameter("roc_threshold", 1.5, 0.1, 25.0, integral=False),
        ),
        helpers=(),
        span_expression="self.p_roc_period + 2",
    ),
)

_FAMILY_BY_KEY = {family.key: family for family in FAMILIES}

# Risk overlays are additive guards layered on top of any family's signal. Defaults
# are deliberately active values: an overlay is only emitted when the spec asks for
# it, so a 0 default would silently produce a guard that never fires. The matrix can
# still disable one by tuning it to the 0 lower bound.
_RISK_OVERLAYS: tuple[TunableParameter, ...] = (
    TunableParameter("stop_loss", 0.05, 0.0, 0.5, integral=False),
    TunableParameter("take_profit", 0.10, 0.0, 2.0, integral=False),
    TunableParameter("max_holding_bars", 48, 0, 10_000),
)

_STOP_LOSS_MARKERS = ("stop loss", "stop-loss", "stoploss", "止损", "最大亏损", "drawdown")
_TAKE_PROFIT_MARKERS = ("take profit", "take-profit", "profit target", "止盈", "目标收益")
_MAX_HOLDING_MARKERS = (
    "holding period",
    "max holding",
    "time stop",
    "time-based exit",
    "持仓时间",
    "最长持仓",
    "超时",
)

# Plain methods, not `@staticmethod`. BitPro executes strategy code with a curated
# `__builtins__` that omits `staticmethod`, so the decorator raised NameError while
# BitPro was building the class and `strategy_validate_code` reported it as a tool
# failure -- indistinguishable, from ARC's side, from BitPro being down. Every call
# site already goes through `self`, so binding these costs nothing.
_HELPER_SOURCES: dict[str, tuple[str, ...]] = {
    "_mean": (
        "    def _mean(self, values):",
        "        return sum(values) / len(values) if values else 0.0",
    ),
    "_stdev": (
        "    def _stdev(self, values):",
        "        if len(values) < 2:",
        "            return 0.0",
        "        avg = sum(values) / len(values)",
        "        variance = sum((v - avg) ** 2 for v in values) / len(values)",
        "        return variance ** 0.5",
    ),
    "_atr": (
        "    def _atr(self, highs, lows, closes, period):",
        "        span = min(len(highs), len(lows), len(closes))",
        "        if span < 2:",
        "            return 0.0",
        "        ranges = []",
        "        for i in range(1, span):",
        "            prev_close = closes[i - 1]",
        "            ranges.append(",
        "                max(",
        "                    highs[i] - lows[i],",
        "                    abs(highs[i] - prev_close),",
        "                    abs(lows[i] - prev_close),",
        "                )",
        "            )",
        "        recent = ranges[-period:] if period > 0 else ranges",
        "        return sum(recent) / len(recent) if recent else 0.0",
    ),
    "_rsi": (
        "    def _rsi(self, closes, period):",
        "        if len(closes) < period + 1 or period <= 0:",
        "            return 50.0",
        "        window = closes[-(period + 1):]",
        "        gains = 0.0",
        "        losses = 0.0",
        "        for i in range(1, len(window)):",
        "            change = window[i] - window[i - 1]",
        "            if change >= 0.0:",
        "                gains += change",
        "            else:",
        "                losses -= change",
        "        if losses <= 0.0:",
        "            return 100.0 if gains > 0.0 else 50.0",
        "        rs = (gains / period) / (losses / period)",
        "        return 100.0 - (100.0 / (1.0 + rs))",
    ),
}


@dataclass(frozen=True)
class GeneratedStrategy:
    """A compiled candidate plus the provenance of how it was derived."""

    code: str
    class_name: str
    family: str
    direction: Direction
    tunable_parameters: dict[str, float] = field(default_factory=dict)
    parameter_bounds: dict[str, dict[str, float]] = field(default_factory=dict)
    risk_overlays: tuple[str, ...] = ()
    indicators: tuple[str, ...] = ()


def _spec_corpus(spec: Mapping[str, Any]) -> str:
    """Flatten every free-text field that may describe the trading logic."""
    parts: list[str] = []
    for key in (
        "strategy_key",
        "title",
        "strategy_category",
        "hypothesis",
        "entry_logic",
        "exit_logic",
    ):
        value = spec.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("risk_conditions", "data_requirements", "invalidation_conditions"):
        value = spec.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            parts.extend(str(item) for item in value)
    return " \n ".join(parts).casefold()


def select_family(spec: Mapping[str, Any]) -> StrategyFamily:
    """Pick the trading logic family that best matches the spec's own words.

    Scoring is longest-keyword-wins so that a specific phrase ("mean reversion")
    outranks a generic one ("trend") that happens to also appear in the prose.
    Ties break on declaration order, keeping the mapping stable across runs.

    An explicit `family_key` short-circuits inference. A search process asking for a
    named family needs that family, not the one its objective prose happens to read
    like; inference is for specs that only describe intent.
    """
    requested = spec.get("family_key")
    if isinstance(requested, str) and requested in _FAMILY_BY_KEY:
        return _FAMILY_BY_KEY[requested]
    corpus = _spec_corpus(spec)
    best: StrategyFamily | None = None
    best_score = 0
    for family in FAMILIES:
        score = family.match_score(corpus)
        if score > best_score:
            best_score = score
            best = family
    if best is not None:
        return best
    # No vocabulary matched. Fall back on a stable hash of the strategy key so
    # unlabelled specs still spread across families instead of collapsing onto one.
    key = str(spec.get("strategy_key", "")) or "unspecified"
    return FAMILIES[sum(key.encode("utf-8")) % len(FAMILIES)]


def direction_is_mandated(spec: Mapping[str, Any]) -> bool:
    """Whether the spec's own words constrain direction, rather than leaving it open.

    A search process needs to tell "the operator forbade shorting" apart from "the
    operator did not mention direction". Both currently compile to `long_only`, so
    without this distinction the search cannot know whether the other directions are
    off the table or merely unexplored.
    """
    corpus = _spec_corpus(spec)
    return any(
        marker in corpus
        for markers in (_SHORT_ONLY_MARKERS, _LONG_ONLY_MARKERS, _BIDIRECTIONAL_MARKERS)
        for marker in markers
    )


def detect_direction(spec: Mapping[str, Any], family: StrategyFamily) -> Direction:
    """Resolve trade direction from the spec, honouring explicit prohibitions first.

    An explicit `direction` short-circuits inference, for the same reason `family_key`
    does: a search asking for a named direction needs that direction, not the one the
    objective prose happens to read like. A direction the family cannot express is
    downgraded rather than emitted, since `supports_short=False` is a property of the
    logic, not a preference.
    """
    requested = spec.get("direction")
    if isinstance(requested, str) and requested in ("long_only", "short_only", "long_short"):
        if requested != "long_only" and not family.supports_short:
            return "long_only"
        return requested
    corpus = _spec_corpus(spec)
    if any(marker in corpus for marker in _SHORT_ONLY_MARKERS):
        return "short_only" if family.supports_short else "long_only"
    if any(marker in corpus for marker in _LONG_ONLY_MARKERS):
        return "long_only"
    if family.supports_short and any(marker in corpus for marker in _BIDIRECTIONAL_MARKERS):
        return "long_short"
    return "long_only"


def _resolve_parameters(
    family: StrategyFamily,
    spec: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, dict[str, float]], tuple[str, ...]]:
    """Merge family defaults with operator-declared bounds and risk overlays.

    Operator `parameter_bounds` narrow the search space but never widen a family's
    own admissible range: a spec asking for a 900-bar fast window is clamped, not
    honoured, so generated code cannot outrun its indicator span.
    """
    declared = spec.get("parameter_bounds")
    declared_bounds: Mapping[str, Any] = declared if isinstance(declared, Mapping) else {}
    corpus = _spec_corpus(spec)

    active: list[TunableParameter] = list(family.parameters)
    overlays: list[str] = []
    for overlay in _RISK_OVERLAYS:
        markers = {
            "stop_loss": _STOP_LOSS_MARKERS,
            "take_profit": _TAKE_PROFIT_MARKERS,
            "max_holding_bars": _MAX_HOLDING_MARKERS,
        }[overlay.name]
        requested = overlay.name in declared_bounds or any(m in corpus for m in markers)
        if requested:
            overlays.append(overlay.name)
            active.append(overlay)
        elif overlay.name == "stop_loss":
            # A candidate with no loss guard at all is not admissible for research.
            overlays.append(overlay.name)
            active.append(overlay)

    defaults: dict[str, float] = {}
    bounds: dict[str, dict[str, float]] = {}
    for param in active:
        # An operator who declared a range asked for that exploration explicitly, so
        # honour it (intersected with the hard limits). Otherwise synthesize a local
        # neighbourhood, because the full admissible range is far too wide to read as
        # a sensitivity probe.
        low, high = param.neighbourhood()
        raw = declared_bounds.get(param.name)
        if isinstance(raw, Mapping):
            try:
                declared_low = float(raw.get("min", param.minimum))
                declared_high = float(raw.get("max", param.maximum))
            except (TypeError, ValueError):
                declared_low, declared_high = param.minimum, param.maximum
            if declared_low <= declared_high:
                low = max(param.minimum, declared_low)
                high = min(param.maximum, declared_high)
            if low > high:
                low, high = param.neighbourhood()
        default = param.clamp(max(low, min(high, param.default)))
        if param.integral:
            defaults[param.name] = float(int(round(default)))
            bounds[param.name] = {"min": float(int(round(low))), "max": float(int(round(high)))}
        else:
            defaults[param.name] = round(default, 6)
            bounds[param.name] = {"min": round(low, 6), "max": round(high, 6)}
    return defaults, bounds, tuple(overlays)


def _class_name(strategy_key: str) -> str:
    parts = [part for part in re.split(r"[^a-zA-Z0-9]+", strategy_key) if part]
    joined = "".join(part.capitalize() for part in parts)
    return "Research" + (joined[:80] or "Candidate")


def _docstring_lines(
    spec: Mapping[str, Any],
    family: StrategyFamily,
    direction: Direction,
    overlays: tuple[str, ...],
) -> list[str]:
    def clean(value: Any, limit: int = 220) -> str:
        text = " ".join(str(value or "").split())
        text = text.replace("\\", " ").replace('"""', " ")
        return text[:limit] or "unspecified"

    return [
        f'    """{clean(spec.get("title"), 120)}',
        "",
        f"    Family: {family.label}",
        f"    Direction: {direction}",
        f"    Risk overlays: {', '.join(overlays) or 'none'}",
        f'    Hypothesis: {clean(spec.get("hypothesis"))}',
        f'    Entry: {clean(spec.get("entry_logic"))}',
        f'    Exit: {clean(spec.get("exit_logic"))}',
        "",
        "    Generated deterministically from research_strategy_spec.v1.",
        '    """',
    ]


def _on_init_lines(
    family: StrategyFamily,
    defaults: Mapping[str, float],
    overlays: tuple[str, ...],
) -> list[str]:
    lines = [
        "    async def on_init(self):",
        '        params = self.config.get("research_parameters", {})',
    ]
    for param in list(family.parameters) + [o for o in _RISK_OVERLAYS if o.name in overlays]:
        default = defaults[param.name]
        if param.integral:
            lines.append(
                f'        self.p_{param.name} = int(max({int(param.minimum)}, '
                f'min({int(param.maximum)}, int(float(params.get("{param.name}", '
                f"{int(default)}))))))"
            )
        else:
            lines.append(
                f'        self.p_{param.name} = float(max({param.minimum}, '
                f'min({param.maximum}, float(params.get("{param.name}", {default})))))'
            )
    if family.key == "ma_crossover":
        lines.append(
            "        self.p_slow_window = max(self.p_fast_window + 1, self.p_slow_window)"
        )
    if family.key == "rsi_reversal":
        lines.append(
            "        self.p_overbought_level = max("
            "self.p_oversold_level + 1.0, self.p_overbought_level)"
        )
    if family.key == "mean_reversion_zscore":
        lines.append(
            "        self.p_exit_zscore = min(self.p_exit_zscore, self.p_entry_zscore)"
        )
    lines += [
        "        self.trade_notional_usdt = float("
        'self.config.get("trade_notional_usdt", 1000.0))',
        '        self.leverage = float(self.config.get("leverage", 2.0))',
        f"        self._span = int({family.span_expression})",
        "        self._closes = {",
        "            symbol: deque(maxlen=self._span) for symbol in self.symbols()",
        "        }",
    ]
    if family.needs_high_low:
        lines += [
            "        self._highs = {",
            "            symbol: deque(maxlen=self._span) for symbol in self.symbols()",
            "        }",
            "        self._lows = {",
            "            symbol: deque(maxlen=self._span) for symbol in self.symbols()",
            "        }",
        ]
    lines += [
        "        self._state = {symbol: 0 for symbol in self.symbols()}",
        "        self._entry_price = {symbol: 0.0 for symbol in self.symbols()}",
        "        self._bars_held = {symbol: 0 for symbol in self.symbols()}",
    ]
    return lines


def _lifecycle_lines() -> list[str]:
    return [
        "    async def _enter(self, symbol, side, close):",
        "        await self.open_contract(",
        "            symbol, side, self.trade_notional_usdt, leverage=self.leverage",
        "        )",
        '        self._state[symbol] = 1 if side == "long" else -1',
        "        self._entry_price[symbol] = close",
        "        self._bars_held[symbol] = 0",
        "",
        "    async def _exit(self, symbol, side):",
        "        await self.close_contract(symbol, side)",
        "        self._state[symbol] = 0",
        "        self._entry_price[symbol] = 0.0",
        "        self._bars_held[symbol] = 0",
    ]


def _risk_lines(overlays: tuple[str, ...]) -> list[str]:
    if not overlays:
        return []
    lines = [
        "        if state != 0:",
        "            entry_price = self._entry_price[symbol]",
        '            side = "long" if state > 0 else "short"',
        "            edge = (close - entry_price) / entry_price if entry_price > 0 else 0.0",
        "            if state < 0:",
        "                edge = -edge",
    ]
    if "stop_loss" in overlays:
        lines += [
            "            if self.p_stop_loss > 0.0 and edge <= -self.p_stop_loss:",
            "                await self._exit(symbol, side)",
            "                return None",
        ]
    if "take_profit" in overlays:
        lines += [
            "            if self.p_take_profit > 0.0 and edge >= self.p_take_profit:",
            "                await self._exit(symbol, side)",
            "                return None",
        ]
    if "max_holding_bars" in overlays:
        lines += [
            "            if (",
            "                self.p_max_holding_bars > 0",
            "                and self._bars_held[symbol] >= self.p_max_holding_bars",
            "            ):",
            "                await self._exit(symbol, side)",
            "                return None",
        ]
    return lines


def _on_bar_lines(
    family: StrategyFamily,
    direction: Direction,
    overlays: tuple[str, ...],
) -> list[str]:
    lines = [
        "    async def on_bar(self, bar):",
        "        symbol = bar.symbol",
        "        close = float(bar.close)",
        "        if symbol not in self._closes or close <= 0.0:",
        "            return None",
        "        self._closes[symbol].append(close)",
    ]
    if family.needs_high_low:
        lines += [
            # Read the fields directly. BitPro's code check forbids `getattr`, so every
            # high/low family (donchian, atr_breakout) failed `strategy_validate_code`
            # and no candidate from them could ever be validated. The fallback was also
            # unsound: both runtimes declare high and low as required, and silently
            # substituting close would degrade a channel into a close-only signal, so
            # BitPro would trade something other than what the evidence measured.
            "        high = float(bar.high)",
            "        low = float(bar.low)",
            "        self._highs[symbol].append(max(high, close))",
            "        self._lows[symbol].append(min(low, close))",
        ]
    lines += [
        "        state = self._state[symbol]",
        "        if state != 0:",
        "            self._bars_held[symbol] += 1",
        "        if len(self._closes[symbol]) < self._span:",
        "            return None",
    ]
    lines += _risk_lines(overlays)
    lines += family.signal_lines(direction)
    lines.append("        return None")
    return lines


def generate_strategy(spec: Mapping[str, Any]) -> GeneratedStrategy:
    """Compile a `research_strategy_spec.v1` mapping into a BaseStrategy candidate.

    Raises `StrategyCodegenError` if the emitted source is not parseable Python or
    trips the static gate. Failing closed here means a malformed spec can never
    reach BitPro's validator or the experiment ledger.
    """
    strategy_key = str(spec.get("strategy_key") or "").strip()
    if not strategy_key:
        raise StrategyCodegenError("strategy_spec_missing_strategy_key")

    family = select_family(spec)
    direction = detect_direction(spec, family)
    defaults, bounds, overlays = _resolve_parameters(family, spec)
    class_name = _class_name(strategy_key)

    helper_lines: list[str] = []
    for helper in family.helpers:
        helper_lines.extend(_HELPER_SOURCES[helper])
        helper_lines.append("")

    body = [
        "from collections import deque",
        "",
        "from app.core.execution.base_strategy import BaseStrategy",
        "",
        "",
        f"class {class_name}(BaseStrategy):",
        *_docstring_lines(spec, family, direction, overlays),
        "",
        *_on_init_lines(family, defaults, overlays),
        "",
        *helper_lines,
        *_lifecycle_lines(),
        "",
        *_on_bar_lines(family, direction, overlays),
        "",
    ]
    code = "\n".join(body)

    try:
        ast.parse(code)
    except SyntaxError as exc:  # pragma: no cover - guards a codegen regression
        raise StrategyCodegenError(f"generated_code_syntax_error:{exc.lineno}") from exc

    rejections = static_code_rejections(code)
    if rejections:  # pragma: no cover - guards a codegen regression
        raise StrategyCodegenError(f"generated_code_rejected:{','.join(rejections)}")

    return GeneratedStrategy(
        code=code,
        class_name=class_name,
        family=family.key,
        direction=direction,
        tunable_parameters=defaults,
        parameter_bounds=bounds,
        risk_overlays=overlays,
        indicators=family.helpers,
    )


def compile_strategy_code(spec: Mapping[str, Any]) -> str:
    """Convenience wrapper returning only the generated source."""
    return generate_strategy(spec).code
