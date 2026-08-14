"""Historical evidence gate for ARC candidates.

Until now every ARC gate judged a candidate by its declared parameters: the perturbation
attack read the stop-loss width, the friction attack read the signal span, and nothing
ever replayed the candidate on a price series. A candidate with defensible parameters and
no edge at all passed review and could be provisioned onto paper.

This gate replays the candidate over a historical window split into in-sample and
out-of-sample halves. The candidate cannot tell the halves apart — it receives one
ordered stream per half — so the out-of-sample result is the first evidence in the
pipeline that is not a restatement of what the candidate declared about itself.

Data sourcing is archive-first with a live fallback, because a research verdict that
cannot be reproduced tomorrow is not evidence. When no window can be obtained the gate
raises an advisory rather than a blocking objection: missing data is an operator problem,
not a defect in the candidate, and silently failing every candidate would hide it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.findings import (
    MAX_ADMISSIBLE_DRAWDOWN,
    ARCReasonCode,
    AttackFinding,
    FindingSeverity,
)
from hypertrade.backtest.candidate import (
    Bar,
    CandidateBacktestError,
    CandidateBacktestResult,
    bars_from_candles,
    replay_candidate,
)

GATE = "historical_evidence"

# Fraction of the window the candidate is measured on first. The remainder is held back;
# nothing in the pipeline may tune against it, which is what makes it evidence.
IN_SAMPLE_FRACTION = 0.7

# The held-back half has to be long enough for its Sharpe to mean anything; the total
# window requirement follows from the split rather than being a second free parameter.
MIN_OUT_OF_SAMPLE_BARS = 60
MIN_EVIDENCE_BARS = math.ceil(MIN_OUT_OF_SAMPLE_BARS / (1.0 - IN_SAMPLE_FRACTION))

MIN_ADMISSIBLE_OOS_SHARPE = 0.5

# Trades the held-out slice must contain for its Sharpe to be a measurement rather than
# an accident. Below this a single trade moves the Sharpe by more than the admissible
# threshold, so the verdict reports noise with a decimal point on it. The research
# pipeline requires 20 over a full window (`RobustnessPolicyV2.min_trade_count`); the
# held-out slice is roughly a third of one, so the same density lands here.
MIN_OUT_OF_SAMPLE_TRADES = 7

# How much of the in-sample Sharpe may evaporate out of sample. A candidate that only
# works on the half it was selected on is the classic selection-bias failure.
MAX_ADMISSIBLE_SHARPE_DECAY = 0.5

# Ceiling on how much of the window may be spent in a position. A candidate parked in a
# permanent position is expressing a directional view, not a strategy.
MAX_ADMISSIBLE_EXPOSURE = 0.95

# Rolling folds the window is cut into when it is long enough. A single split proves the
# candidate worked once, at one point in time; folds are what distinguish a strategy from
# a period. Each fold trains on everything before it and is judged on the slice after, so
# no fold can see its own future.
WALK_FORWARD_FOLDS = 4

# Fraction of a candidate's folds that must survive. Demanding every fold would reject any
# strategy that has a regime it does not suit, which is most of them; demanding one would
# be indistinguishable from picking the best period after the fact.
MIN_SURVIVING_FOLD_FRACTION = 0.5


class CandleWindowSource(Protocol):
    """Supplies the historical window a candidate is judged on."""

    def read(self, *, symbol: str, timeframe: str, limit: int) -> Sequence[Any]:
        """Return candles oldest-first, or raise if the window is unavailable."""
        ...


@dataclass(frozen=True)
class ArchiveThenLiveWindow:
    """Prefer the reproducible archive; fall back to live only when it is missing.

    Ordering matters for auditability: an archived window replays identically tomorrow,
    while a live pull silently shifts under the verdict it produced.
    """

    archive: CandleWindowSource | None = None
    live: CandleWindowSource | None = None

    def read(self, *, symbol: str, timeframe: str, limit: int) -> Sequence[Any]:
        errors: list[str] = []
        for label, source in (("archive", self.archive), ("live", self.live)):
            if source is None:
                continue
            try:
                candles = source.read(symbol=symbol, timeframe=timeframe, limit=limit)
            except Exception as exc:
                errors.append(f"{label}:{type(exc).__name__}")
                continue
            if candles:
                return candles
            errors.append(f"{label}:empty")
        raise CandidateBacktestError(
            "no_candle_window_available:" + (",".join(errors) or "no_source_configured")
        )


@dataclass(frozen=True)
class ArchiveWindow:
    """Reads the BitPro kline archive, which replays identically on every run."""

    db_path: str

    def read(self, *, symbol: str, timeframe: str, limit: int) -> Sequence[Any]:
        from hypertrade.backtest.bitpro import BitProKlineArchive

        return BitProKlineArchive(self.db_path).read_candles(
            symbol=symbol, bar=timeframe, limit=limit
        )


@dataclass(frozen=True)
class OkxLiveWindow:
    """Live fallback. Capped by the exchange's per-request limit, so the window it
    returns is short and the verdict it supports is correspondingly weaker."""

    settings: Any = None

    def read(self, *, symbol: str, timeframe: str, limit: int) -> Sequence[Any]:
        import asyncio

        from hypertrade.backtest.service import _okx_candles_to_strategy_candles
        from hypertrade.config import get_settings
        from hypertrade.market.client import OkxRestClient

        settings = self.settings or get_settings()
        okx_candles = asyncio.run(
            OkxRestClient(settings).fetch_candles(
                inst_id=symbol, bar=timeframe, limit=max(6, min(limit, 300))
            )
        )
        return _okx_candles_to_strategy_candles(okx_candles)


def build_default_window(settings: Any = None) -> ArchiveThenLiveWindow:
    """Archive first, live only when an operator opted in.

    Returns a window with no sources when nothing is configured, so the gate raises an
    advisory instead of the caller having to special-case an unconfigured deployment.
    The live fallback stays behind a flag: an autonomous loop reaching an exchange on its
    own initiative is a side effect no research verdict should require.
    """
    from hypertrade.config import get_settings

    resolved = settings or get_settings()
    live_enabled = bool(getattr(resolved, "arc_evidence_live_fallback_enabled", False))
    return ArchiveThenLiveWindow(
        archive=_configured_archive(getattr(resolved, "bitpro_sqlite_path", "")),
        live=OkxLiveWindow(resolved) if live_enabled else None,
    )


def _configured_archive(raw_path: Any) -> ArchiveWindow | None:
    """Treat an unset archive path as unset.

    The setting defaults to `Path("")`, which is truthy and stringifies to ".", so a
    deployment with no archive configured produced a window pointing at the working
    directory. It failed on connect and fell through, which meant an unconfigured
    archive was indistinguishable from a broken one in the advisory detail.
    """
    text = str(raw_path or "").strip()
    if text in ("", "."):
        return None
    return ArchiveWindow(text)


# Archive reader already caps at 20_000. Using that as the default means a 1m
# window is judged on the history that is actually mounted, not a 1500-bar stub.
MAX_WINDOW_BARS = 20_000


def preflight_window(
    *,
    symbol: str,
    timeframe: str,
    bars: int = MAX_WINDOW_BARS,
    window: CandleWindowSource | None = None,
) -> dict[str, Any]:
    """Report what evidence a mission on this symbol would actually be able to obtain.

    Without this an operator learns that the archive has no history for a symbol only
    after a mission has spent its candidate budget and completed on advisories alone —
    the run looks successful and the absent evidence is a line in the metrics.
    """
    source = window if window is not None else build_default_window()
    configured = [
        label
        for label, member in (("archive", getattr(source, "archive", None)),
                              ("live", getattr(source, "live", None)))
        if member is not None
    ]
    try:
        candles = source.read(symbol=symbol, timeframe=timeframe, limit=bars)
    except Exception as exc:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "sources_configured": configured,
            "bars_available": 0,
            "evidence_possible": False,
            "walk_forward_folds": 0,
            "detail": str(exc)[:200],
        }

    available = len(bars_from_candles(symbol, candles))
    folds = len(walk_forward_slices(available))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "sources_configured": configured,
        "bars_available": available,
        "bars_required": MIN_EVIDENCE_BARS,
        "evidence_possible": available >= MIN_EVIDENCE_BARS,
        "walk_forward_folds": folds,
        "detail": (
            "ok"
            if folds
            else "window supports a single split but is too short for rolling folds"
        ),
    }


@dataclass(frozen=True)
class EvidenceVerdict:
    """The gate's outcome: blocking objections, advisories, and the evidence itself."""

    findings: tuple[AttackFinding, ...]
    metrics: Mapping[str, Any]

    @property
    def blocking(self) -> tuple[AttackFinding, ...]:
        return tuple(f for f in self.findings if f.severity is FindingSeverity.BLOCKING)

    @property
    def passed(self) -> bool:
        return not self.blocking


class HistoricalEvidenceGate:
    """Replays a candidate on held-out history and reports what it actually did."""

    def __init__(
        self,
        window: CandleWindowSource | None = None,
        *,
        bars: int = MAX_WINDOW_BARS,
        replay: Callable[..., CandidateBacktestResult] = replay_candidate,
    ) -> None:
        self.window = window
        self.bars = bars
        self._replay = replay

    def evaluate(self, attempt: ARCCandidateAttemptV1) -> EvidenceVerdict:
        symbol = str(attempt.strategy_spec.get("symbol") or "BTC-USDT-SWAP")
        timeframe = str(attempt.strategy_spec.get("timeframe") or "1H")

        if self.window is None:
            return _advisory("no_candle_window_configured")
        try:
            candles = self.window.read(symbol=symbol, timeframe=timeframe, limit=self.bars)
        except Exception as exc:
            return _advisory(str(exc)[:200])

        bars = bars_from_candles(symbol, candles)
        if len(bars) < MIN_EVIDENCE_BARS:
            return _advisory(
                f"window of {len(bars)} bars is shorter than the {MIN_EVIDENCE_BARS} "
                "needed for an out-of-sample half to be meaningful"
            )

        split = int(len(bars) * IN_SAMPLE_FRACTION)
        try:
            # Replay with the candidate's own declared defaults rather than a supplied
            # parameter set: mutation rewrites those defaults, so the code is the only
            # honest statement of what this particular candidate does.
            in_sample = self._run(attempt, bars[:split], timeframe)
            out_of_sample = self._run(attempt, bars[split:], timeframe)
            folds = self._walk_forward(attempt, bars, timeframe)
        except CandidateBacktestError as exc:
            return EvidenceVerdict(
                findings=(
                    AttackFinding(
                        code=ARCReasonCode.EVIDENCE_REPLAY_FAILED,
                        gate=GATE,
                        detail=f"candidate could not be replayed: {exc}",
                    ),
                ),
                metrics={"evidence_available": False},
            )

        findings = _judge(in_sample, out_of_sample) + _judge_folds(folds)
        metrics = _metrics(in_sample, out_of_sample)
        metrics.update(_fold_metrics(folds))
        return EvidenceVerdict(findings=findings, metrics=metrics)

    def _walk_forward(
        self,
        attempt: ARCCandidateAttemptV1,
        bars: Sequence[Bar],
        timeframe: str,
    ) -> tuple[CandidateBacktestResult, ...]:
        """Replay each rolling out-of-sample slice the window can support.

        A single split shows the candidate worked once. Folds show whether it keeps
        working as the market changes, which is the difference between a strategy and a
        period. Returns empty when the window is too short to cut, so the single-split
        verdict stands alone rather than being weakened by folds too small to read.
        """
        results: list[CandidateBacktestResult] = []
        for start, end in walk_forward_slices(len(bars)):
            results.append(self._run(attempt, bars[start:end], timeframe))
        return tuple(results)

    def _run(
        self,
        attempt: ARCCandidateAttemptV1,
        bars: Sequence[Bar],
        timeframe: str,
    ) -> CandidateBacktestResult:
        return self._replay(attempt.strategy_code, list(bars), timeframe=timeframe)


def walk_forward_slices(total_bars: int) -> tuple[tuple[int, int], ...]:
    """Rolling out-of-sample slices, expressed as [start, end) bar indices.

    Anchored so each fold begins where the previous one ended: the folds tile the
    held-out portion without overlapping, because an overlapping fold would count the
    same bars twice and make an accidental good run look repeated.
    """
    fold_bars = total_bars // (WALK_FORWARD_FOLDS + 1)
    if fold_bars < MIN_OUT_OF_SAMPLE_BARS:
        return ()
    return tuple(
        (fold_bars * index, fold_bars * (index + 1))
        for index in range(1, WALK_FORWARD_FOLDS + 1)
    )


def _judge_folds(folds: Sequence[CandidateBacktestResult]) -> tuple[AttackFinding, ...]:
    if not folds:
        return ()
    surviving = sum(
        1
        for fold in folds
        if not fold.is_inert
        and fold.sharpe >= MIN_ADMISSIBLE_OOS_SHARPE
        and fold.max_drawdown <= MAX_ADMISSIBLE_DRAWDOWN
    )
    required = math.ceil(len(folds) * MIN_SURVIVING_FOLD_FRACTION)
    if surviving >= required:
        return ()
    return (
        AttackFinding(
            code=ARCReasonCode.WALK_FORWARD_INCONSISTENT,
            gate=GATE,
            detail=(
                f"only {surviving} of {len(folds)} rolling windows cleared the "
                f"out-of-sample bar, below the {required} required; the result does not "
                "hold across market conditions"
            ),
        ),
    )


def _fold_metrics(folds: Sequence[CandidateBacktestResult]) -> dict[str, Any]:
    if not folds:
        return {"walk_forward_folds": 0}
    return {
        "walk_forward_folds": len(folds),
        "walk_forward_sharpes": [fold.sharpe for fold in folds],
        "walk_forward_returns": [fold.total_return for fold in folds],
        "walk_forward_drawdowns": [fold.max_drawdown for fold in folds],
        "walk_forward_trades": [fold.trade_count for fold in folds],
    }


def _advisory(detail: str) -> EvidenceVerdict:
    return EvidenceVerdict(
        findings=(
            AttackFinding(
                code=ARCReasonCode.NO_HISTORICAL_EVIDENCE,
                gate=GATE,
                detail=detail,
                severity=FindingSeverity.ADVISORY,
            ),
        ),
        metrics={"evidence_available": False},
    )


def _judge(
    in_sample: CandidateBacktestResult,
    out_of_sample: CandidateBacktestResult,
) -> tuple[AttackFinding, ...]:
    findings: list[AttackFinding] = []

    if out_of_sample.is_inert:
        # Reported before the ratio checks: an inert candidate has a zero Sharpe and no
        # drawdown, which a threshold read in isolation cannot distinguish from caution.
        findings.append(
            AttackFinding(
                code=ARCReasonCode.INERT_NO_TRADES,
                gate=GATE,
                detail=(
                    f"no position was opened across {out_of_sample.bars} out-of-sample "
                    "bars, so the window produced no evidence either way"
                ),
            )
        )
        return tuple(findings)

    if out_of_sample.trade_count < MIN_OUT_OF_SAMPLE_TRADES:
        findings.append(
            AttackFinding(
                code=ARCReasonCode.OOS_SAMPLE_TOO_SMALL,
                gate=GATE,
                detail=(
                    f"the held-out window contains {out_of_sample.trade_count} trades, "
                    f"below the {MIN_OUT_OF_SAMPLE_TRADES} needed for its Sharpe of "
                    f"{out_of_sample.sharpe:.2f} to be a measurement rather than an accident"
                ),
            )
        )

    if out_of_sample.sharpe < MIN_ADMISSIBLE_OOS_SHARPE:
        findings.append(
            AttackFinding(
                code=ARCReasonCode.OOS_SHARPE_TOO_LOW,
                gate=GATE,
                detail=(
                    f"out-of-sample Sharpe {out_of_sample.sharpe:.2f} is below the "
                    f"admissible {MIN_ADMISSIBLE_OOS_SHARPE:.2f}"
                ),
            )
        )

    if out_of_sample.max_drawdown > MAX_ADMISSIBLE_DRAWDOWN:
        findings.append(
            AttackFinding(
                code=ARCReasonCode.OOS_DRAWDOWN_EXCEEDED,
                gate=GATE,
                detail=(
                    f"out-of-sample drawdown {out_of_sample.max_drawdown:.1%} exceeds the "
                    f"admissible {MAX_ADMISSIBLE_DRAWDOWN:.0%}"
                ),
            )
        )

    if in_sample.sharpe > 0 and out_of_sample.sharpe < in_sample.sharpe * (
        1.0 - MAX_ADMISSIBLE_SHARPE_DECAY
    ):
        findings.append(
            AttackFinding(
                code=ARCReasonCode.IS_OOS_DEGRADATION,
                gate=GATE,
                detail=(
                    f"Sharpe fell from {in_sample.sharpe:.2f} in sample to "
                    f"{out_of_sample.sharpe:.2f} out of sample, more than the "
                    f"{MAX_ADMISSIBLE_SHARPE_DECAY:.0%} decay a selection-bias check allows"
                ),
            )
        )

    if out_of_sample.exposure > MAX_ADMISSIBLE_EXPOSURE:
        findings.append(
            AttackFinding(
                code=ARCReasonCode.PERMANENT_EXPOSURE,
                gate=GATE,
                detail=(
                    f"a position was held for {out_of_sample.exposure:.0%} of the window, "
                    "which is a directional view rather than a strategy"
                ),
            )
        )

    return tuple(findings)


def _metrics(
    in_sample: CandidateBacktestResult,
    out_of_sample: CandidateBacktestResult,
) -> dict[str, Any]:
    return {
        "evidence_available": True,
        "in_sample_bars": in_sample.bars,
        "in_sample_sharpe": in_sample.sharpe,
        "in_sample_return": in_sample.total_return,
        "in_sample_trades": in_sample.trade_count,
        "out_of_sample_bars": out_of_sample.bars,
        "out_of_sample_sharpe": out_of_sample.sharpe,
        "out_of_sample_return": out_of_sample.total_return,
        "out_of_sample_max_drawdown": out_of_sample.max_drawdown,
        "out_of_sample_trades": out_of_sample.trade_count,
        "out_of_sample_win_rate": out_of_sample.win_rate,
        "out_of_sample_turnover": out_of_sample.turnover,
        "out_of_sample_exposure": out_of_sample.exposure,
        "out_of_sample_fees_paid": out_of_sample.fees_paid,
        "replay_assumptions": dict(out_of_sample.assumptions),
    }
