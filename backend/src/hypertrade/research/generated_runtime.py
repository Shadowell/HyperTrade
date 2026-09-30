"""Emitted runtime contract; no platform imports in the generated strategy body."""

RUNTIME_INIT = """
        self._last_bar = {symbol: -1 for symbol in self.symbols()}
        self._entry_time = {symbol: 0 for symbol in self.symbols()}
        self._position_size = {symbol: 0.0 for symbol in self.symbols()}
        self._ready = False
        self._pending = {}
        saved = self.state.positions.get("_arc_generated_runtime")
        if saved is not None:
            if not isinstance(saved, dict) or saved.get("version") != "arc_generated.v1":
                raise ValueError("arc_runtime_invalid_version")
            if saved.get("instance_id") != str(self.config.get("paper_instance_id") or ""):
                raise ValueError("arc_runtime_instance_mismatch")
            if saved.get("parameters") != self._runtime_parameters:
                raise ValueError("arc_runtime_parameters_mismatch")
            if (not isinstance(saved.get("positions"), dict)
                    or not isinstance(saved.get("last_bars"), dict)):
                raise ValueError("arc_runtime_missing_fields")
            if set(saved["last_bars"]) != set(self.symbols()):
                raise ValueError("arc_runtime_scope_mismatch")
            if saved.get("pending") != {}:
                raise ValueError("arc_runtime_pending_order_requires_reconciliation")
            for symbol, timestamp in saved["last_bars"].items():
                if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < -1:
                    raise ValueError("arc_runtime_invalid_clock")
                self._last_bar[symbol] = timestamp
            for symbol, position in saved["positions"].items():
                if symbol not in self._state or not isinstance(position, dict):
                    raise ValueError("arc_runtime_scope_mismatch")
                if position.get("side") not in ("long", "short"):
                    raise ValueError("arc_runtime_invalid_side")
                for field in ("entry_price", "size", "stop_price", "take_profit_price"):
                    value = position.get(field)
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not 0.0 < value < float("inf")):
                        raise ValueError("arc_runtime_invalid_protection")
                for field in ("bars_held", "entry_time"):
                    value = position.get(field)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError("arc_runtime_invalid_clock")
                direction = 1 if position["side"] == "long" else -1
                price = position["entry_price"]
                if (abs(position["stop_price"] - price * (1 - direction * self.p_stop_loss))
                        > price * 1e-9):
                    raise ValueError("arc_runtime_stop_mismatch")
                if (abs(position["take_profit_price"]
                        - price * (1 + direction * self.p_take_profit))
                        > price * 1e-9):
                    raise ValueError("arc_runtime_target_mismatch")
                self._state[symbol] = direction
                self._entry_price[symbol] = price
                self._bars_held[symbol] = position["bars_held"]
                self._entry_time[symbol] = position["entry_time"]
                self._position_size[symbol] = position["size"]
""".strip("\n").splitlines()

RUNTIME_METHODS = """
    async def on_start(self):
        await self._reconcile_existing_positions(0)

    async def _reconcile_existing_positions(self, timestamp):
        for symbol in self.symbols():
            await self._sync_position(symbol, restarting=True)
        self._ready = True
        self._persist_runtime()

    def _persist_runtime(self):
        self.checkpoint_runtime_state()
        if hasattr(self, "runtime_checkpoint"):
            self.runtime_checkpoint()

    def checkpoint_runtime_state(self):
        positions = {}
        for symbol, direction in self._state.items():
            if direction:
                price = self._entry_price[symbol]
                positions[symbol] = {
                    "side": "long" if direction > 0 else "short", "entry_price": price,
                    "stop_price": price * (1 - direction * self.p_stop_loss),
                    "take_profit_price": price * (1 + direction * self.p_take_profit),
                    "size": self._position_size[symbol], "entry_time": self._entry_time[symbol],
                    "bars_held": self._bars_held[symbol],
                }
        self.state.positions["_arc_generated_runtime"] = {
            "version": "arc_generated.v1",
            "instance_id": str(self.config.get("paper_instance_id") or ""),
            "parameters": dict(self._runtime_parameters), "positions": positions,
            "last_bars": dict(self._last_bar), "pending": dict(self._pending),
        }

    async def _sync_position(self, symbol, allow_new=False, restarting=False):
        long_position = await self.get_contract_position(symbol, "long")
        short_position = await self.get_contract_position(symbol, "short")
        if long_position and short_position:
            raise ValueError("arc_runtime_two_sided_position")
        position = long_position or short_position
        direction = 1 if long_position else -1
        if not position:
            if restarting and self._state[symbol] != 0:
                raise ValueError("arc_runtime_position_missing")
            self._state[symbol] = 0
            self._entry_price[symbol] = 0.0
            self._bars_held[symbol] = 0
            self._position_size[symbol] = 0.0
            self._entry_time[symbol] = 0
            return None
        price = float(position["entry_price"])
        size = float(position.get("contracts", position.get("notional_usdt", 0)))
        if not 0.0 < price < float("inf") or not 0.0 < size < float("inf"):
            raise ValueError("arc_runtime_position_invalid")
        if not allow_new and (self._state[symbol] != direction
                              or abs(self._entry_price[symbol] - price) > price * 1e-9
                              or abs(self._position_size[symbol] - size) > size * 1e-9):
            raise ValueError("arc_runtime_position_unbound")
        self._state[symbol] = direction
        self._entry_price[symbol] = price
        self._position_size[symbol] = size

    async def _enter(self, symbol, side, close):
        equity = float(self.broker.equity)
        if not 0.0 < equity < float("inf") or self.trade_notional_usdt < 0.0:
            return None
        cap = equity * self.margin_fraction * self.leverage
        notional = min(cap, self.trade_notional_usdt) if self.trade_notional_usdt > 0 else cap
        if notional <= 0.0:
            return None
        self._pending[symbol] = {"action": "open", "side": side, "bar": self._last_bar[symbol]}
        self._persist_runtime()
        receipt = await self.open_contract(symbol, side, notional, leverage=self.leverage)
        if receipt.get("status") in ("submitted", "partially_filled"):
            raise ValueError("arc_runtime_pending_order_requires_reconciliation")
        if receipt.get("status") not in ("filled", "closed"):
            self._pending.pop(symbol, None)
            self._persist_runtime()
            return None
        await self._sync_position(symbol, allow_new=True)
        if self._state[symbol] == 0:
            raise ValueError("arc_runtime_filled_position_missing")
        self._entry_time[symbol] = max(0, self._last_bar[symbol])
        self._bars_held[symbol] = 0
        self._pending.pop(symbol, None)
        self._persist_runtime()

    async def _exit(self, symbol, side, price=None):
        self._pending[symbol] = {"action": "close", "side": side, "bar": self._last_bar[symbol]}
        self._persist_runtime()
        receipt = await self.close_contract(symbol, side, price=price)
        if receipt.get("status") in ("submitted", "partially_filled"):
            raise ValueError("arc_runtime_pending_order_requires_reconciliation")
        if receipt.get("status") not in ("filled", "closed", "no_position"):
            self._pending.pop(symbol, None)
            self._persist_runtime()
            return None
        await self._sync_position(symbol)
        if self._state[symbol] != 0:
            raise ValueError("arc_runtime_close_not_confirmed")
        self._pending.pop(symbol, None)
        self._persist_runtime()
""".strip("\n").splitlines()
