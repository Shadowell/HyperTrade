"""The historical evidence gate.

Every other ARC gate reads what the candidate declares about itself, so a strategy with
defensible parameters and no edge passed review and could be provisioned onto paper. This
gate is the first one whose verdict is not a restatement of the candidate's own source.
"""


import random
from decimal import Decimal

import pytest
from hypertrade.arc.adversarial import BlueTeamQuant, RedTeamQuant
from hypertrade.arc.evidence import (
    IN_SAMPLE_FRACTION,
    MIN_EVIDENCE_BARS,
    MIN_OUT_OF_SAMPLE_BARS,
    ArchiveThenLiveWindow,
    HistoricalEvidenceGate,
)
from hypertrade.arc.findings import ARCReasonCode, FindingSeverity
from hypertrade.backtest.candidate import CandidateBacktestError
from hypertrade.strategy.sdk import Candle


class _StaticWindow:
    def __init__(self, candles):
        self.candles = candles
        self.calls: list[dict] = []

    def read(self, *, symbol: str, timeframe: str, limit: int):
        self.calls.append({"symbol": symbol, "timeframe": timeframe, "limit": limit})
        return self.candles


class _BrokenWindow:
    def read(self, *, symbol: str, timeframe: str, limit: int):
        raise FileNotFoundError("/no/such/archive.sqlite")


def _candles(
    count: int,
    *,
    seed: int = 5,
    drift: float = 0.0005,
    start_index: int = 0,
    start_price: float = 100.0,
) -> list[Candle]:
    rnd = random.Random(seed)
    price = start_price
    candles = []
    for offset in range(count):
        index = start_index + offset
        price *= 1.0 + rnd.gauss(drift, 0.012)
        candles.append(
            Candle(
                timestamp=f"2026-01-01T{index:05d}",
                open=Decimal(str(round(price, 4))),
                high=Decimal(str(round(price * 1.004, 4))),
                low=Decimal(str(round(price * 0.996, 4))),
                close=Decimal(str(round(price, 4))),
                volume=Decimal("10"),
            )
        )
    return candles


def _candidate(objective: str = "均线金叉趋势", **kwargs):
    return BlueTeamQuant().propose_initial_strategy(objective, "BTC-USDT-SWAP", **kwargs)


def test_the_smallest_accepted_window_still_holds_back_enough_bars():
    """Two independent constants could drift apart; the total is derived from the split."""
    split = int(MIN_EVIDENCE_BARS * IN_SAMPLE_FRACTION)
    assert MIN_EVIDENCE_BARS - split >= MIN_OUT_OF_SAMPLE_BARS


def test_gate_replays_the_candidate_and_reports_held_back_evidence():
    window = _StaticWindow(_candles(600))
    verdict = HistoricalEvidenceGate(window).evaluate(_candidate())

    assert verdict.metrics["evidence_available"] is True
    # The two halves must be disjoint and add up to the window.
    assert verdict.metrics["in_sample_bars"] + verdict.metrics["out_of_sample_bars"] == 600
    assert verdict.metrics["out_of_sample_bars"] >= MIN_OUT_OF_SAMPLE_BARS
    assert "replay_assumptions" in verdict.metrics
    # The window the candidate declared is the one that was fetched.
    assert window.calls[0]["symbol"] == "BTC-USDT-SWAP"
    assert window.calls[0]["timeframe"] == "1H"


def test_missing_window_is_advisory_not_a_verdict_against_the_candidate():
    """A data outage is an operator problem; failing every candidate would hide it."""
    for gate in (
        HistoricalEvidenceGate(),
        HistoricalEvidenceGate(_BrokenWindow()),
        HistoricalEvidenceGate(_StaticWindow(_candles(MIN_EVIDENCE_BARS - 1))),
    ):
        verdict = gate.evaluate(_candidate())
        assert verdict.passed is True
        assert verdict.blocking == ()
        assert [f.code for f in verdict.findings] == [ARCReasonCode.NO_HISTORICAL_EVIDENCE]
        assert verdict.findings[0].severity is FindingSeverity.ADVISORY
        assert verdict.metrics["evidence_available"] is False


def test_a_candidate_that_never_trades_is_flagged_rather_than_scored_as_flawless():
    """An inert candidate has zero Sharpe and no drawdown, which thresholds read as caution."""
    # A signal span far longer than the window guarantees no position is ever opened.
    candidate = _candidate(parameter_bounds={"slow_window": {"min": 390, "max": 400}})
    verdict = HistoricalEvidenceGate(_StaticWindow(_candles(600))).evaluate(candidate)

    assert verdict.passed is False
    assert ARCReasonCode.INERT_NO_TRADES in {f.code for f in verdict.blocking}


def test_out_of_sample_failure_blocks_the_candidate():
    """A drifting-down series gives a long-biased trend follower no out-of-sample edge."""
    verdict = HistoricalEvidenceGate(
        _StaticWindow(_candles(800, seed=17, drift=-0.0015))
    ).evaluate(_candidate())

    assert verdict.passed is False
    assert ARCReasonCode.OOS_SHARPE_TOO_LOW in {f.code for f in verdict.blocking}


def test_replay_failure_is_attributed_to_the_candidate_not_to_the_data():
    class _Boom:
        def __call__(self, *args, **kwargs):
            raise CandidateBacktestError("candidate_syntax_error:3")

    verdict = HistoricalEvidenceGate(_StaticWindow(_candles(400)), replay=_Boom()).evaluate(
        _candidate()
    )
    assert verdict.passed is False
    assert [f.code for f in verdict.blocking] == [ARCReasonCode.EVIDENCE_REPLAY_FAILED]


def test_archive_is_preferred_over_the_live_source():
    """An archived window replays identically tomorrow; a live pull shifts underneath."""
    archive = _StaticWindow(_candles(400, seed=1))
    live = _StaticWindow(_candles(400, seed=2))
    window = ArchiveThenLiveWindow(archive=archive, live=live)

    window.read(symbol="BTC-USDT-SWAP", timeframe="1H", limit=400)
    assert archive.calls and not live.calls


def test_live_source_is_used_only_when_the_archive_is_unavailable():
    live = _StaticWindow(_candles(400))
    window = ArchiveThenLiveWindow(archive=_BrokenWindow(), live=live)

    assert window.read(symbol="BTC-USDT-SWAP", timeframe="1H", limit=400)
    assert live.calls

    empty = ArchiveThenLiveWindow(archive=_StaticWindow([]), live=_StaticWindow([]))
    with pytest.raises(CandidateBacktestError, match="no_candle_window_available"):
        empty.read(symbol="BTC-USDT-SWAP", timeframe="1H", limit=400)

    with pytest.raises(CandidateBacktestError, match="no_source_configured"):
        ArchiveThenLiveWindow().read(symbol="BTC-USDT-SWAP", timeframe="1H", limit=400)


def test_red_team_blocks_a_candidate_that_fails_out_of_sample():
    """Wiring check: evidence findings have to reach the red team's verdict."""
    red_team = RedTeamQuant(
        evidence_gate=HistoricalEvidenceGate(_StaticWindow(_candles(800, seed=17, drift=-0.0015)))
    )
    passed, metrics, findings = red_team.evaluate_adversarial_attack(_candidate())

    assert passed is False
    assert metrics["evidence_available"] is True
    assert any(f.gate == "historical_evidence" for f in findings)


def test_walk_forward_folds_tile_the_window_without_overlapping():
    """An overlapping fold counts the same bars twice, making one good run look repeated."""
    from hypertrade.arc.evidence import WALK_FORWARD_FOLDS, walk_forward_slices

    slices = walk_forward_slices(1_000)
    assert len(slices) == WALK_FORWARD_FOLDS
    for (_, previous_end), (next_start, _) in zip(slices, slices[1:], strict=False):
        assert previous_end == next_start
    # The first fold starts after a training portion, so no fold can see its own future.
    assert slices[0][0] > 0
    for start, end in slices:
        assert end - start >= MIN_OUT_OF_SAMPLE_BARS
        assert end <= 1_000


def test_a_window_too_short_to_cut_yields_no_folds():
    """A fold shorter than the out-of-sample floor would weaken the verdict, not support it."""
    from hypertrade.arc.evidence import walk_forward_slices

    assert walk_forward_slices(MIN_EVIDENCE_BARS) == ()
    verdict = HistoricalEvidenceGate(_StaticWindow(_candles(MIN_EVIDENCE_BARS + 10))).evaluate(
        _candidate()
    )
    assert verdict.metrics["walk_forward_folds"] == 0
    assert ARCReasonCode.WALK_FORWARD_INCONSISTENT not in {f.code for f in verdict.findings}


def test_rolling_windows_are_reported_and_judged_together():
    window = _StaticWindow(_candles(1_200))
    verdict = HistoricalEvidenceGate(window).evaluate(_candidate())

    from hypertrade.arc.evidence import WALK_FORWARD_FOLDS

    assert verdict.metrics["walk_forward_folds"] == WALK_FORWARD_FOLDS
    assert len(verdict.metrics["walk_forward_sharpes"]) == WALK_FORWARD_FOLDS
    # Folds are separately replayed, so their results must not all be identical.
    assert len(set(verdict.metrics["walk_forward_trades"])) > 1


def test_a_result_that_holds_in_only_one_period_is_rejected():
    """The failure a single split cannot see: profitable once, not repeatable."""
    # One strong leg followed by a long drift down: a trend follower clears the early
    # folds and fails the later ones.
    rally = _candles(400, seed=4, drift=0.006)
    slump = _candles(
        800, seed=9, drift=-0.002, start_index=400, start_price=float(rally[-1].close)
    )

    verdict = HistoricalEvidenceGate(_StaticWindow(rally + slump)).evaluate(_candidate())
    surviving = sum(1 for value in verdict.metrics["walk_forward_sharpes"] if value >= 0.5)

    assert surviving < 2  # ceil(4 folds * 0.5) are required
    assert ARCReasonCode.WALK_FORWARD_INCONSISTENT in {f.code for f in verdict.blocking}


def test_reported_win_rate_is_measured_rather_than_derived_from_the_verdict():
    """It used to be 0.65 on a pass and 0.42 on a failure: the verdict in metric costume."""
    from hypertrade.arc.adversarial import RedTeamQuant

    candidate = _candidate()
    gate = HistoricalEvidenceGate(_StaticWindow(_candles(1_200)))
    _, metrics, _ = RedTeamQuant(evidence_gate=gate).evaluate_adversarial_attack(candidate)

    assert metrics["win_rate"] == metrics["out_of_sample_win_rate"]
    assert metrics["win_rate"] not in (0.65, 0.42)
    # A closed trade is either a win or a loss, so the rate is a multiple of 1/n.
    trades = metrics["out_of_sample_trades"]
    assert abs(metrics["win_rate"] * trades - round(metrics["win_rate"] * trades)) < 1e-9


def test_an_inert_candidate_reports_no_win_rate_rather_than_zero():
    """Zero would read as a candidate that traded and lost every time."""
    from hypertrade.arc.adversarial import RedTeamQuant

    candidate = _candidate(parameter_bounds={"slow_window": {"min": 390, "max": 400}})
    gate = HistoricalEvidenceGate(_StaticWindow(_candles(600)))
    _, metrics, _ = RedTeamQuant(evidence_gate=gate).evaluate_adversarial_attack(candidate)

    assert metrics["out_of_sample_win_rate"] is None
    assert "win_rate" not in metrics


def test_search_ranks_on_held_out_evidence_when_a_window_exists():
    """Ranking by the declared projection means the winner is self-reported."""
    from hypertrade.arc.adversarial import RedTeamQuant

    candidate = _candidate()
    with_window = RedTeamQuant(evidence_gate=HistoricalEvidenceGate(_StaticWindow(_candles(1_200))))
    _, evidenced, _ = with_window.evaluate_adversarial_attack(candidate)

    assert evidenced["ranking_basis"] == "out_of_sample"
    assert evidenced["ranking_sharpe"] == evidenced["out_of_sample_sharpe"]

    # With no window the search still has to order candidates somehow, but the basis for
    # the ordering must be visible as the weaker one.
    _, unevidenced, _ = RedTeamQuant(
        evidence_gate=HistoricalEvidenceGate(None)
    ).evaluate_adversarial_attack(candidate)
    assert unevidenced["ranking_basis"] == "declared_projection"
    assert unevidenced["ranking_sharpe"] == unevidenced["sharpe_after_attack"]


def test_gate_reads_a_real_bitpro_archive_end_to_end(tmp_path):
    """The archive route has only been exercised against fakes.

    On the server the window comes from a mounted sqlite file with BitPro's schema and a
    symbol spelled `BTC/USDT:USDT`, while ARC asks for `BTC-USDT-SWAP`. Everything
    between those two facts has to hold before a real mission can produce evidence.
    """
    from hypertrade.arc.evidence import build_default_window
    from hypertrade.config import Settings

    db_path = tmp_path / "crypto_data.db"
    _seed_bitpro_archive(db_path, table="kline_1h", symbol="BTC/USDT:USDT", rows=1_200)

    window = build_default_window(
        Settings(BITPRO_SQLITE_PATH=db_path, ARC_EVIDENCE_LIVE_FALLBACK_ENABLED=False)
    )
    assert window.archive is not None
    assert window.live is None  # no exchange call is made on the archive route

    verdict = HistoricalEvidenceGate(window).evaluate(_candidate())

    assert verdict.metrics["evidence_available"] is True
    assert verdict.metrics["out_of_sample_bars"] >= MIN_OUT_OF_SAMPLE_BARS
    assert verdict.metrics["walk_forward_folds"] > 0


def test_a_sharpe_computed_from_a_handful_of_trades_is_not_accepted_as_evidence(tmp_path):
    """A probe on real archive data passed candidates whose out-of-sample Sharpe of 8
    came from five trades. One trade moved it by more than the admissible threshold, so
    the number was noise with a decimal point on it."""
    from hypertrade.arc.evidence import MIN_OUT_OF_SAMPLE_TRADES, build_default_window
    from hypertrade.config import Settings

    db_path = tmp_path / "crypto_data.db"
    _seed_bitpro_archive(db_path, table="kline_1h", symbol="BTC/USDT:USDT", rows=1_200)
    window = build_default_window(Settings(BITPRO_SQLITE_PATH=db_path))

    # A span long relative to the window fires rarely without being inert.
    sparse = _candidate(parameter_bounds={"slow_window": {"min": 150, "max": 160}})
    verdict = HistoricalEvidenceGate(window).evaluate(sparse)

    assert verdict.metrics["out_of_sample_trades"] < MIN_OUT_OF_SAMPLE_TRADES
    assert ARCReasonCode.OOS_SAMPLE_TOO_SMALL in {f.code for f in verdict.blocking}
    # Distinct from being inert: this candidate did trade, just not enough to measure.
    assert ARCReasonCode.INERT_NO_TRADES not in {f.code for f in verdict.findings}


def test_preflight_tells_an_operator_what_a_mission_could_prove(tmp_path):
    """Operators must see whether a symbol has a window before the budget is spent."""
    from hypertrade.arc.evidence import build_default_window, preflight_window
    from hypertrade.config import Settings

    db_path = tmp_path / "crypto_data.db"
    _seed_bitpro_archive(db_path, table="kline_1h", symbol="BTC/USDT:USDT", rows=1_200)
    window = build_default_window(Settings(BITPRO_SQLITE_PATH=db_path))

    stocked = preflight_window(symbol="BTC-USDT-SWAP", timeframe="1H", window=window)
    assert stocked["evidence_possible"] is True
    assert stocked["bars_available"] >= MIN_EVIDENCE_BARS
    assert stocked["walk_forward_folds"] > 0
    assert stocked["sources_configured"] == ["archive"]

    # A symbol the archive has never heard of has to be distinguishable from a stocked
    # one before the budget is spent, not after.
    missing = preflight_window(symbol="DOGE-USDT-SWAP", timeframe="1H", window=window)
    assert missing["evidence_possible"] is False
    assert missing["bars_available"] == 0
    assert missing["walk_forward_folds"] == 0


def test_preflight_reports_an_unconfigured_deployment_as_such():
    from hypertrade.arc.evidence import preflight_window

    report = preflight_window(symbol="BTC-USDT-SWAP", timeframe="1H", window=_EmptyWindow())
    assert report["sources_configured"] == []
    assert report["evidence_possible"] is False
    assert "no_source_configured" in report["detail"]


class _EmptyWindow:
    def read(self, *, symbol: str, timeframe: str, limit: int):
        raise CandidateBacktestError("no_candle_window_available:no_source_configured")


def _seed_bitpro_archive(db_path, *, table: str, symbol: str, rows: int) -> None:
    """Write BitPro's kline table shape so the reader is exercised, not stubbed."""
    import sqlite3

    rnd = random.Random(11)
    price = 30_000.0
    base_ts = 1_780_272_000_000
    records = []
    for index in range(rows):
        open_price = price
        price *= 1.0 + rnd.gauss(0.0004, 0.011)
        records.append(
            (
                "okx",
                symbol,
                base_ts + index * 3_600_000,
                open_price,
                max(open_price, price) * 1.001,
                min(open_price, price) * 0.999,
                price,
                1_000.0 + index,
                100_000.0 + index,
            )
        )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL,
                UNIQUE(exchange, symbol, timestamp)
            )
            """
        )
        connection.executemany(
            f"""
            INSERT INTO {table}
                (exchange, symbol, timestamp, open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )


def test_live_fallback_is_off_unless_an_operator_enabled_it():
    """An autonomous loop must not reach an exchange on its own initiative."""
    from hypertrade.arc.evidence import build_default_window

    class _Settings:
        bitpro_sqlite_path = ""
        arc_evidence_live_fallback_enabled = False

    window = build_default_window(_Settings())
    assert window.archive is None
    assert window.live is None

    enabled = _Settings()
    enabled.arc_evidence_live_fallback_enabled = True
    assert build_default_window(enabled).live is not None


def test_an_unset_archive_path_is_not_treated_as_a_configured_archive():
    """`Path("")` is truthy and stringifies to ".", so the default pointed at the cwd."""
    from pathlib import Path

    from hypertrade.arc.evidence import build_default_window

    class _Settings:
        bitpro_sqlite_path = Path("")
        arc_evidence_live_fallback_enabled = False

    assert build_default_window(_Settings()).archive is None

    configured = _Settings()
    configured.bitpro_sqlite_path = Path("/bitpro-data/crypto_data.db")
    archive = build_default_window(configured).archive
    assert archive is not None
    assert archive.db_path == "/bitpro-data/crypto_data.db"


def test_every_blocking_evidence_code_has_remediation_advice():
    from hypertrade.arc.reflexion import _CONSTRAINT_BY_REASON_CODE

    blocking_codes = {
        ARCReasonCode.INERT_NO_TRADES,
        ARCReasonCode.OOS_SHARPE_TOO_LOW,
        ARCReasonCode.OOS_DRAWDOWN_EXCEEDED,
        ARCReasonCode.IS_OOS_DEGRADATION,
        ARCReasonCode.PERMANENT_EXPOSURE,
        ARCReasonCode.EVIDENCE_REPLAY_FAILED,
    }
    assert blocking_codes <= set(_CONSTRAINT_BY_REASON_CODE)
