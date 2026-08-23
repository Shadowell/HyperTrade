"""Slice 1 of the ARC real-closure contract: evidence-window provenance.

A research verdict is only as honest as the window it replays on. These tests pin
three facts: preflight names where the bars come from, the loop refuses to spend a
candidate budget on a non-OKX window the operator never confirmed, and every attempt
carries the provenance of the exact window it was judged on.
"""

from decimal import Decimal

from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.evidence import (
    ORIGIN_ALTERNATIVE,
    ORIGIN_ARCHIVE_UNKNOWN,
    ArchiveThenLiveWindow,
    HistoricalEvidenceGate,
    build_default_window,
    preflight_window,
)
from hypertrade.arc.router import (
    _ARC_MISSIONS,
    CreateARCMissionRequest,
    run_autonomous_arc_loop,
)
from hypertrade.strategy.sdk import Candle


class _StaticWindow:
    """Minimal candle source; origin-unaware, like any injected test fake."""

    def __init__(self, candles):
        self._candles = candles
        self.calls: list[dict[str, object]] = []

    def read(self, *, symbol: str, timeframe: str, limit: int):
        self.calls.append({"symbol": symbol, "timeframe": timeframe, "limit": limit})
        return list(self._candles)


class _BrokenWindow:
    def read(self, *, symbol: str, timeframe: str, limit: int):
        raise RuntimeError("archive offline")


def _candles(count: int = 800) -> list[Candle]:
    price = Decimal("100")
    return [
        Candle(
            timestamp=f"2026-01-01T{index:05d}",
            open=price,
            high=price,
            low=price,
            close=price,
            volume=Decimal("10"),
        )
        for index in range(count)
    ]


def test_preflight_injected_bare_window_has_no_provable_origin():
    report = preflight_window(
        symbol="BTC-USDT-SWAP", timeframe="1H", bars=400, window=_StaticWindow(_candles())
    )
    # An injected bare fake has no provable origin: None, not a guess.
    assert report["source_origin"] is None
    assert report["alternative_source_confirmation_required"] is False
    assert report["evidence_possible"] is True
    assert report["window_as_of"] == "2026-01-01T00799"
    assert len(report["window_source_hash"]) == 64


def test_mission_request_defaults_to_unconfirmed_alternative_source():
    request = CreateARCMissionRequest(objective="research a BTC trend strategy")
    assert request.alternative_source_confirmed is False


def test_preflight_attributes_archive_origin_from_declaration(monkeypatch):
    class _Settings:
        arc_evidence_archive_origin = "alternative_exchange"

    monkeypatch.setattr(
        "hypertrade.config.get_settings", lambda: _Settings()
    )
    archive = _StaticWindow(_candles())
    window = ArchiveThenLiveWindow(archive=archive)
    report = preflight_window(
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        bars=400,
        window=window,
    )
    assert report["sources_configured"] == ["archive"]
    assert report["source_origin"] == ORIGIN_ALTERNATIVE
    assert report["alternative_source_confirmation_required"] is True


def test_preflight_undeclared_archive_is_unknown_and_needs_confirmation(monkeypatch):
    class _Settings:
        arc_evidence_archive_origin = ""

    monkeypatch.setattr("hypertrade.config.get_settings", lambda: _Settings())
    report = preflight_window(
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        bars=400,
        window=ArchiveThenLiveWindow(archive=_StaticWindow(_candles())),
    )
    assert report["source_origin"] == ORIGIN_ARCHIVE_UNKNOWN
    assert report["alternative_source_confirmation_required"] is True


def test_preflight_missing_window_keeps_provenance_fields_present():
    report = preflight_window(
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        bars=400,
        window=ArchiveThenLiveWindow(),
    )
    assert report["evidence_possible"] is False
    assert report["source_origin"] is None
    assert report["alternative_source_confirmation_required"] is False
    assert report["detail"].startswith("no_candle_window_available")


def test_goal_defaults_to_unconfirmed_alternative_source():
    goal = ARCGoalV1(objective="research a BTC trend strategy")
    assert goal.alternative_source_confirmed is False
    assert goal.live_allowed is False


def test_loop_stops_on_unconfirmed_alternative_source_before_spending_budget(monkeypatch):
    from hypertrade.arc.contracts import ARCBudgetV1, PaperPreauthorizationV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.store import reset_store

    monkeypatch.setattr(
        "hypertrade.arc.router.build_default_window",
        lambda *a, **k: ArchiveThenLiveWindow(archive=_StaticWindow(_candles())),
    )

    class _Settings:
        arc_evidence_archive_origin = "alternative_exchange"
        bitpro_sqlite_path = ""

    monkeypatch.setattr("hypertrade.config.get_settings", lambda: _Settings())

    goal = ARCGoalV1(
        objective="BTC trend strategy",
        budget=ARCBudgetV1(max_candidates=3),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    reset_store()
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
        projection = ctrl.projection
        assert projection.state == "needs_operator"
        blocked = [e for e in projection.events if e.event_type == "operator_needed"]
        assert blocked and blocked[-1].payload.get("reason") == "evidence_window_unavailable"
        assert blocked[-1].payload.get("preflight", {}).get("source_origin") == (
            ORIGIN_ALTERNATIVE
        )
        # The refusal happens before research starts: zero attempts, zero spend.
        assert projection.attempts == []
    finally:
        _ARC_MISSIONS.pop(ctrl.mission_id, None)


def test_confirmed_alternative_source_lets_the_loop_reach_candidates(monkeypatch):
    from hypertrade.arc.contracts import ARCBudgetV1, PaperPreauthorizationV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.store import reset_store

    monkeypatch.setattr(
        "hypertrade.arc.router.build_default_window",
        lambda *a, **k: ArchiveThenLiveWindow(archive=_StaticWindow(_candles(800))),
    )

    class _Settings:
        arc_evidence_archive_origin = "alternative_exchange"
        bitpro_sqlite_path = ""

    monkeypatch.setattr("hypertrade.config.get_settings", lambda: _Settings())

    goal = ARCGoalV1(
        objective="BTC trend strategy",
        budget=ARCBudgetV1(max_candidates=2),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
        alternative_source_confirmed=True,
    )
    reset_store()
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
        projection = ctrl.projection
        assert projection.attempts != [], "confirmed consent must let research start"
        first = [e for e in projection.events if e.event_type == "candidate_proposed"]
        assert first
    finally:
        _ARC_MISSIONS.pop(ctrl.mission_id, None)


def test_gate_records_window_provenance_on_every_verdict():
    verdict = HistoricalEvidenceGate(_StaticWindow(_candles(600))).evaluate(
        _arc_candidate()
    )
    metrics = dict(verdict.metrics)
    # Injected fakes carry no declared origin, but the fingerprint must still exist.
    assert "window_as_of" in metrics
    assert metrics["window_bars"] == 600
    assert len(metrics["window_source_hash"]) == 64
    assert metrics["window_source_origin"] is None


def _arc_candidate():
    from hypertrade.arc.adversarial import BlueTeamQuant

    return BlueTeamQuant().propose_initial_strategy("均线金叉趋势", "BTC-USDT-SWAP")


def test_build_default_window_reads_declared_origin_setting(monkeypatch):
    class _Settings:
        arc_evidence_live_fallback_enabled = True
        arc_evidence_archive_origin = "okx_swap"
        bitpro_sqlite_path = "/tmp/some-archive.sqlite"

    window = build_default_window(_Settings())
    members = window.members()
    assert [label for label, _ in members] == ["archive", "live"]
