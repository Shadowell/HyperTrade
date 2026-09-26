from __future__ import annotations

import copy
import hashlib
import json

import pytest
from hypertrade.agent.compaction import ContextBlocked, compact_request
from hypertrade.arc.avo import _SYSTEM, TOOLS, _evolution_view, _json


def production_sized_context() -> dict:
    # Shapes and sizes measured on the 2026-09-25 production scan (#333/#443).
    fills = [
        {
            "id": f"fill_{index:04d}",
            "timestamp": 1_758_000_000_000 + index * 60_000,
            "symbol": "KAITO/USDT:USDT" if index % 3 else "BTC/USDT:USDT",
            "side": "buy" if index % 2 else "sell",
            "type": "market",
            "price": "1.23456789",
            "quantity": "81.00000000",
            "fee": "0.05000000",
            "pnl": "0" if index % 2 else ("1.5" if index % 4 else "-2.25"),
        }
        for index in range(200)
    ]
    return {
        "target_id": "bitpro",
        "trigger_source": "degradation",
        "source_strategy_id": 443,
        "source_instance_id": "paper_9a8109e0ff804fe387d1a20a22a49b79",
        "source_code_sha256": "0" * 64,
        "baseline": {
            "attempt_id": "baseline_443",
            "strategy_code": "# native strategy source\n" + "x = 1\n" * 8500,
            "strategy_spec": {"symbol": "KAITO/USDT:USDT", "timeframe": "1h"},
        },
        "paper_feedback": {
            "triggered": True,
            "reasons": ["return_drop"],
            "receipts": [{"id": f"r{index}", "hash": "f" * 64} for index in range(170)],
        },
        "attribution_report": {"report_id": "attr_1", "dimensions": {"fees": "unknown"}},
        "orders": {
            "sample_limit": 200,
            "sample_count": len(fills),
            "coverage": "recent_session_sample",
            "fills": fills,
        },
        "memory": [{"memory_id": f"m{index}", "hypothesis": "h"} for index in range(25)],
    }


def first_request(evolution: dict) -> list[dict]:
    runtime_context = {"objective": "evolve", "autonomous_evolution": evolution}
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _json(runtime_context)},
    ]


def test_full_context_reproduces_first_turn_block() -> None:
    with pytest.raises(ContextBlocked) as blocked:
        compact_request(first_request(production_sized_context()), tools=TOOLS, model="m")
    assert blocked.value.record["manifest"]["reason"] == "required_context_exceeds_budget"


def test_bounded_view_fits_first_turn_without_mutating_goal_context() -> None:
    context = production_sized_context()
    frozen = copy.deepcopy(context)
    view = _evolution_view(context)
    assert context == frozen

    result = compact_request(first_request(view), tools=TOOLS, model="m")
    assert result.manifest["status"] == "ready"
    assert result.manifest["final_tokens_upper_bound"] < 40_000


def test_view_keeps_recent_fills_with_digest_and_whole_session_summary() -> None:
    context = production_sized_context()
    fills = context["orders"]["fills"]
    orders = _evolution_view(context)["orders"]

    assert [f["id"] for f in orders["fills"]] == [f["id"] for f in fills[-30:]]
    assert orders["sample_count"] == 200
    assert orders["not_full_evidence"] is True
    assert orders["full_fills_sha256"] == hashlib.sha256(_json(fills).encode()).hexdigest()
    summary = orders["summary"]["by_symbol"]
    assert sum(row["fills"] for row in summary.values()) == 200
    btc = summary["BTC/USDT:USDT"]
    expected = [f for f in fills if f["symbol"] == "BTC/USDT:USDT"]
    assert btc["wins"] == sum(f["pnl"] == "1.5" for f in expected)
    assert btc["losses"] == sum(f["pnl"] == "-2.25" for f in expected)
    assert orders["summary"]["first_timestamp"] == fills[0]["timestamp"]


def test_view_digests_receipts_large_source_and_caps_memory() -> None:
    context = production_sized_context()
    view = _evolution_view(context)
    code = context["baseline"]["strategy_code"]

    assert view["paper_feedback"]["receipts"]["items"] == 170
    assert view["paper_feedback"]["triggered"] is True
    assert hashlib.sha256(code.encode()).hexdigest() in view["baseline"]["strategy_code"]
    assert len(view["baseline"]["strategy_code"]) < 400
    assert view["memory_in_view"] == {"shown": 20, "total": 25}
    assert [m["memory_id"] for m in view["memory"]] == [f"m{i}" for i in range(20)]


def test_small_context_passes_through_unchanged_except_summary() -> None:
    context = production_sized_context()
    context["orders"]["fills"] = context["orders"]["fills"][:5]
    context["baseline"]["strategy_code"] = "class S: pass\n"
    context["paper_feedback"].pop("receipts")
    context["memory"] = context["memory"][:3]
    view = _evolution_view(context)

    assert view["orders"]["fills"] == context["orders"]["fills"]
    assert "not_full_evidence" not in view["orders"]
    assert view["baseline"] == context["baseline"]
    assert view["memory"] == context["memory"]
    assert json.loads(_json(view["orders"]["summary"]))["by_symbol"]
