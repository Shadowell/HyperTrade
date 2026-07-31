"""
Unit & Integration Tests for Industrial Agent Harness 2.0
"""

from typing import Any

from hypertrade.agent.harness_v2 import (
    AsyncParallelToolDispatcher,
    HarnessContextWaterCooler,
    SmartToolExecutionHealer,
    ToolIdempotencyLockGuard,
)


def test_tool_idempotency_lock_guard():
    guard = ToolIdempotencyLockGuard()
    key = "order_intent_btc_001"

    # First acquire succeeds
    assert guard.acquire(key) is True
    # Second acquire with same key fails
    assert guard.acquire(key) is False

    # Release key
    guard.release(key)
    # Acquire again succeeds
    assert guard.acquire(key) is True


def test_harness_context_water_cooler():
    cooler = HarnessContextWaterCooler(max_payload_chars=200)

    small_payload = {"status": "ok", "symbol": "BTC-USDT-SWAP"}
    assert cooler.water_cool_payload("test_tool", small_payload) == small_payload

    large_payload = {
        "status": "ok",
        "candles": [{"time": i, "price": 50000 + i} for i in range(50)],
        "description": "A" * 600,
    }

    cooled = cooler.water_cool_payload("market_candles", large_payload)
    assert cooled.get("_water_cooler", {}).get("truncated") is True
    assert len(cooled["candles"]) < 50
    assert cooled["description"].endswith("... [truncated] ...")


def test_smart_tool_execution_healer_retry():
    attempts = 0

    def flaky_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("502 Bad Gateway: OKX upstream timeout")
        return {"status": "ok", "data": "recovered"}

    healer = SmartToolExecutionHealer(flaky_executor, max_retries=3, base_backoff_ms=5.0)
    res = healer.execute("market_ticker", {"symbol": "ETH-USDT-SWAP"})

    assert res["status"] == "ok"
    assert attempts == 3


def test_async_parallel_tool_dispatcher():
    call_log: list[str] = []

    def mock_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        call_log.append(name)
        return {"status": "ok", "tool": name, "val": args.get("val", 0)}

    healer = SmartToolExecutionHealer(mock_executor)
    dispatcher = AsyncParallelToolDispatcher(healer, max_workers=4)

    read_requests = [
        ("market_ticker", {"val": 1}),
        ("market_summary", {"val": 2}),
        ("market_candles", {"val": 3}),
    ]

    results = dispatcher.dispatch_batch(read_requests)
    assert len(results) == 3
    assert len(call_log) == 3
    assert results[0]["val"] == 1
    assert results[1]["val"] == 2
    assert results[2]["val"] == 3
