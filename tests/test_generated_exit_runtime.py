import asyncio
import json
from collections import deque
from types import SimpleNamespace

import pytest
from hypertrade.research.codegen import StrategyCodegenError, generate_strategy


class Runtime:
    def __init__(self, saved=None, positions=None, config=None):
        self.config = {"paper_instance_id": "paper-test", **(config or {})}
        self.state = SimpleNamespace(positions=saved or {})
        self.positions = positions if positions is not None else {}
        self.broker = SimpleNamespace(equity=100)
        self.exits = []

    def symbols(self):
        return ["BTC"]

    async def on_start(self):
        pass

    async def open_contract(self, symbol, side, amount, leverage):
        self.positions[symbol] = {"entry_price": 100.0, "side": side, "contracts": 1.0}
        return {"status": "filled"}

    async def get_contract_position(self, symbol, side):
        p = self.positions.get(symbol)
        return p if p and p["side"] == side else None

    async def close_contract(self, symbol, side, price=None):
        self.exits.append((side, price))
        self.positions.pop(symbol, None)
        return {"status": "closed"}


def factory(**spec):
    generated = generate_strategy({"strategy_key": "guard", "family_key": "ma_crossover", **spec})
    body = "\n".join(
        line for line in generated.code.splitlines() if not line.startswith(("import ", "from "))
    )
    namespace = {"BaseStrategy": Runtime, "deque": deque, "BarData": object}
    exec(compile(body, "<generated-exit-test>", "exec"), namespace)
    return namespace[generated.class_name], generated


def bar(high, low, close=100, timestamp=60000, opening=100):
    return SimpleNamespace(
        symbol="BTC", timestamp=timestamp, open=opening, high=high, low=low, close=close, volume=1
    )


def test_every_generated_candidate_has_strict_positive_dual_protection():
    _, generated = factory()
    assert {"stop_loss", "take_profit"} <= set(generated.risk_overlays)
    for key in ("stop_loss", "take_profit"):
        assert generated.parameter_bounds[key]["min"] > 0
        assert generated.tunable_parameters[key] > 0


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan")])
def test_generated_runtime_rejects_disabled_or_nonfinite_exit(value):
    cls, _ = factory()
    with pytest.raises(ValueError):
        asyncio.run(cls(config={"research_parameters": {"stop_loss": value}}).on_init())


@pytest.mark.parametrize("side,high,low,want", [("long", 115, 94, 95), ("short", 106, 85, 105)])
def test_intrabar_stop_wins_before_indicator_warmup(side, high, low, want):
    async def run():
        cls, _ = factory()
        s = cls()
        await s.on_init()
        await s.on_start()
        await s._enter("BTC", side, 100)
        await s.on_bar(bar(high, low))
        assert s.exits == [(side, pytest.approx(want))]
        assert s._state["BTC"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("side,high,low,want", [("long", 111, 99, 110), ("short", 101, 89, 90)])
def test_intrabar_take_profit_works_for_both_sides(side, high, low, want):
    async def run():
        cls, _ = factory()
        s = cls()
        await s.on_init()
        await s.on_start()
        await s._enter("BTC", side, 100)
        await s.on_bar(bar(high, low))
        assert s.exits == [(side, pytest.approx(want))]

    asyncio.run(run())


def test_restart_restores_protection_clock_and_warmup_never_trades():
    async def run():
        cls, _ = factory(parameter_bounds={"max_holding_bars": {"min": 10, "max": 10}})
        old = cls()
        await old.on_init()
        await old.on_start()
        await old._enter("BTC", "long", 100)
        await old.on_bar(bar(101, 99))
        old.checkpoint_runtime_state()
        saved = json.loads(json.dumps(old.state.positions))
        new = cls(saved=saved, positions=old.positions)
        await new.on_init()
        await new.on_start()
        assert new._bars_held["BTC"] == 1
        await new.on_warmup_bar(bar(120, 80, timestamp=0))
        assert not new.exits
        assert new._bars_held["BTC"] == 1
        await new.on_bar(bar(111, 99, timestamp=120000))
        assert new.exits == [("long", pytest.approx(110))]
        new.checkpoint_runtime_state()
        assert new.state.positions["_arc_generated_runtime"]["positions"] == {}

    asyncio.run(run())


@pytest.mark.parametrize("saved", [None, {"_arc_generated_runtime": {"version": "bad"}}])
def test_open_position_without_valid_state_fails_closed(saved):
    async def run():
        cls, _ = factory()
        s = cls(
            saved=saved, positions={"BTC": {"entry_price": 100.0, "side": "long", "contracts": 1}}
        )
        with pytest.raises(ValueError):
            await s.on_init()
            await s.on_start()

    asyncio.run(run())


def test_zero_exit_search_bound_is_rejected_before_generation():
    with pytest.raises(StrategyCodegenError):
        factory(parameter_bounds={"stop_loss": {"min": 0, "max": 0}})


@pytest.mark.parametrize(
    "side,opening,high,low,want", [("long", 90, 101, 88, 90), ("short", 110, 112, 99, 110)]
)
def test_gap_stop_uses_worse_open_price(side, opening, high, low, want):
    async def run():
        cls, _ = factory()
        s = cls()
        await s.on_init()
        await s.on_start()
        await s._enter("BTC", side, 100)
        await s.on_bar(bar(high, low, opening=opening))
        assert s.exits == [(side, pytest.approx(want))]

    asyncio.run(run())


@pytest.mark.parametrize("tamper", ["instance_id", "parameters", "protection", "size"])
def test_restart_rejects_wrong_identity_or_corrupted_protection(tamper):
    async def run():
        cls, _ = factory()
        old = cls()
        await old.on_init()
        await old.on_start()
        await old._enter("BTC", "long", 100)
        saved = json.loads(json.dumps(old.state.positions))
        data = saved["_arc_generated_runtime"]
        if tamper == "instance_id":
            data["instance_id"] = "other-session"
        elif tamper == "parameters":
            data["parameters"]["stop_loss"] = 0.2
        elif tamper == "size":
            data["positions"]["BTC"]["size"] = 2
        else:
            data["positions"]["BTC"]["stop_price"] = 0
        s = cls(saved=saved, positions=old.positions)
        with pytest.raises(ValueError):
            await s.on_init()
            await s.on_start()

    asyncio.run(run())


def test_restart_holding_limit_includes_time_elapsed_while_offline():
    async def run():
        cls, _ = factory(parameter_bounds={"max_holding_bars": {"min": 10, "max": 10}})
        old = cls(config={"timeframe": "1h"})
        await old.on_init()
        await old.on_start()
        await old._enter("BTC", "long", 100)
        old.checkpoint_runtime_state()
        new = cls(
            saved=json.loads(json.dumps(old.state.positions)),
            positions=old.positions,
            config={"timeframe": "1h"},
        )
        await new.on_init()
        await new.on_start()
        await new.on_bar(bar(101, 99, timestamp=20 * 3600000))
        assert new.exits == [("long", None)]

    asyncio.run(run())
