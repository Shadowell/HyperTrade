"""Slice 2 of the ARC real-closure contract: the provider hypothesis channel.

The provider proposes; deterministic systems dispose. These tests pin the channel's
boundaries: a valid proposal joins the same frontier and budget as family
candidates with full provenance, an overreaching or malformed reply is discarded
with an explicit reason code, and a missing provider never blocks the
deterministic search.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.provider_hypothesis import (
    PROVIDER_SPEC_INVALID,
    PROVIDER_UNAVAILABLE,
    ProviderHypothesist,
    build_provider_hypothesist,
)
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop
from hypertrade.arc.store import reset_store


class _FakeChatProvider:
    """Minimal ChatProvider shape: name/model/chat returning one scripted reply."""

    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.name = "fake"
        self.model = "fake-model-1"

    def chat(self, messages: list[dict[str, Any]], tools: Any = None) -> Any:
        from hypertrade.providers.chat import ChatResponse

        if isinstance(self._reply, Exception):
            raise self._reply
        return ChatResponse(content=self._reply)


def _valid_reply() -> str:
    return json.dumps(
        {
            "hypothesis": "Donchian breakout persists in trending regimes on BTC 1H",
            "family_key": "donchian_breakout",
            "direction": "long_only",
            "entry_logic": "close above N-bar high confirms breakout continuation",
            "exit_logic": "stop loss below channel mid; take profit at 2R",
            "risk_conditions": ["stop loss", "take profit"],
            "parameter_bounds": {"channel_period": {"min": 20, "max": 60}},
        },
        ensure_ascii=False,
    )


def test_valid_proposal_compiles_with_provenance() -> None:
    hypothesist = ProviderHypothesist(_FakeChatProvider(_valid_reply()))
    proposal, status = hypothesist.propose(
        objective="趋势突破策略",
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
    )
    assert status == "ok" and proposal is not None
    assert proposal.spec["family_key"] == "donchian_breakout"
    assert proposal.spec["direction"] == "long_only"
    assert proposal.model == "fake-model-1"
    assert len(proposal.request_hash) == 16

    # Same spec compiles byte-identically twice: reproducibility unit is the spec.
    from hypertrade.research.codegen import generate_strategy

    first = generate_strategy(proposal.spec).code
    second = generate_strategy(proposal.spec).code
    assert first == second

    # BlueTeam mints the attempt with provider provenance.
    from hypertrade.arc.adversarial import BlueTeamQuant

    attempt = BlueTeamQuant().propose_from_provider(proposal)
    assert attempt.origin == "provider_hypothesis"
    assert attempt.provider_model == "fake:fake-model-1"
    assert attempt.attempt_id.startswith("att_prov_")
    assert attempt.strategy_spec["source"] == "provider_hypothesis"


def test_overreach_is_powerless_by_construction() -> None:
    """Budget/criteria/authorization keys in the reply simply do not exist in the spec."""
    reply = json.dumps(
        {
            **json.loads(_valid_reply()),
            "budget": {"max_candidates": 9999},
            "success_criteria": {"min_oos_sharpe": -100},
            "paper_authorization": {"approved_by": "model"},
            "live_allowed": True,
        },
        ensure_ascii=False,
    )
    hypothesist = ProviderHypothesist(_FakeChatProvider(reply))
    proposal, status = hypothesist.propose(
        objective="趋势突破策略", symbol="BTC-USDT-SWAP", timeframe="1H"
    )
    assert status == "ok" and proposal is not None
    assert "budget" not in proposal.spec
    assert "success_criteria" not in proposal.spec
    assert "paper_authorization" not in proposal.spec
    assert "live_allowed" not in proposal.spec

    from hypertrade.arc.contracts import ARCGoalV1

    goal = ARCGoalV1(objective="x")
    assert goal.live_allowed is False
    assert goal.budget.max_candidates != 9999


def test_unknown_family_or_direction_fails_closed() -> None:
    for mutation in ({"family_key": "quantum_arbitrage"}, {"direction": "all_in"}):
        reply = json.dumps({**json.loads(_valid_reply()), **mutation})
        hypothesist = ProviderHypothesist(_FakeChatProvider(reply))
        proposal, status = hypothesist.propose(
            objective="x", symbol="BTC-USDT-SWAP", timeframe="1H"
        )
        assert proposal is None
        assert status == PROVIDER_SPEC_INVALID


def test_malformed_and_outage_replies_are_explicit_failures() -> None:
    hypothesist = ProviderHypothesist(_FakeChatProvider("我觉得应该买"))
    proposal, status = hypothesist.propose(
        objective="x", symbol="BTC-USDT-SWAP", timeframe="1H"
    )
    assert proposal is None and status == PROVIDER_SPEC_INVALID

    outage = ProviderHypothesist(_FakeChatProvider(RuntimeError("connection reset")))
    proposal, status = outage.propose(objective="x", symbol="BTC-USDT-SWAP", timeframe="1H")
    assert proposal is None and status == PROVIDER_UNAVAILABLE


def test_flag_off_means_no_channel_even_with_a_provider(monkeypatch) -> None:
    """Default-off keeps deterministic tests and deployments free of paid calls."""
    from hypertrade.providers.runtime import ProviderRuntime

    monkeypatch.setattr(
        ProviderRuntime,
        "get_chat_provider",
        lambda self, selected=None, selected_model=None: _FakeChatProvider(_valid_reply()),
    )
    assert build_provider_hypothesist() is None


def test_no_provider_configured_returns_none_not_a_crash(monkeypatch) -> None:
    from hypertrade.providers.runtime import ProviderRuntime

    class _Settings:
        arc_provider_hypotheses_enabled = True

    monkeypatch.setattr("hypertrade.config.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        ProviderRuntime,
        "get_chat_provider",
        lambda self, selected=None, selected_model=None: None,
    )
    assert build_provider_hypothesist() is None


class _StaticWindow:
    """Minimal candle source; origin-unaware, like any injected test fake."""

    def __init__(self, candles: list[Any]) -> None:
        self._candles = candles

    def read(self, *, symbol: str, timeframe: str, limit: int) -> list[Any]:
        return list(self._candles)


def _candles(count: int = 800) -> list[Any]:
    from hypertrade.strategy.sdk import Candle

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


def test_golden_path_mission_carries_both_origins(monkeypatch) -> None:
    """One mission: family candidates AND a provider candidate reach the same gate."""
    monkeypatch.setattr(
        "hypertrade.arc.router.build_provider_hypothesist",
        lambda: ProviderHypothesist(_FakeChatProvider(_valid_reply())),
    )

    class _Settings:
        arc_evidence_archive_origin = ""
        bitpro_sqlite_path = ""

    monkeypatch.setattr("hypertrade.config.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        "hypertrade.arc.router.build_default_window",
        lambda *a, **k: __import__(
            "hypertrade.arc.evidence", fromlist=["ArchiveThenLiveWindow"]
        ).ArchiveThenLiveWindow(archive=_StaticWindow(_candles(800))),
    )

    goal = ARCGoalV1(
        objective="BTC 趋势策略研究",
        budget=ARCBudgetV1(max_candidates=4),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
        alternative_source_confirmed=True,
    )
    reset_store()
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
        attempts = ctrl.projection.attempts
        origins = {item.origin for item in attempts}
        assert "deterministic_family" in origins
        assert "provider_hypothesis" in origins
        provider_rows = [a for a in attempts if a.origin == "provider_hypothesis"]
        assert provider_rows and all(a.provider_model for a in provider_rows)
        # Both kinds went through the same red-team gate.
        tested = {
            e.payload.get("attempt_id")
            for e in ctrl.projection.events
            if e.event_type == "red_team_tested"
        }
        assert provider_rows[0].attempt_id in tested
    finally:
        _ARC_MISSIONS.pop(ctrl.mission_id, None)


def test_unavailable_provider_records_fact_and_deterministic_path_runs(monkeypatch) -> None:
    def _broken() -> ProviderHypothesist:
        return ProviderHypothesist(_FakeChatProvider(RuntimeError("provider down")))

    monkeypatch.setattr("hypertrade.arc.router.build_provider_hypothesist", _broken)

    class _Settings:
        arc_evidence_archive_origin = ""
        bitpro_sqlite_path = ""

    monkeypatch.setattr("hypertrade.config.get_settings", lambda: _Settings())
    from hypertrade.arc.evidence import ArchiveThenLiveWindow

    monkeypatch.setattr(
        "hypertrade.arc.router.build_default_window",
        lambda *a, **k: ArchiveThenLiveWindow(archive=_StaticWindow(_candles(800))),
    )

    goal = ARCGoalV1(
        objective="BTC 趋势策略研究",
        budget=ARCBudgetV1(max_candidates=3),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
        alternative_source_confirmed=True,
    )
    reset_store()
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
        statuses = [
            e.payload.get("status")
            for e in ctrl.projection.events
            if e.event_type == "provider_status"
        ]
        assert "provider_spec_invalid" in statuses or "provider_unavailable" in statuses
        # The deterministic search still proposed and tested candidates.
        assert any(item.origin == "deterministic_family" for item in ctrl.projection.attempts)
        assert any(
            e.event_type == "red_team_tested" for e in ctrl.projection.events
        )
    finally:
        _ARC_MISSIONS.pop(ctrl.mission_id, None)
