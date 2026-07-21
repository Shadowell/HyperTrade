from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def return_series_payload() -> dict[str, Any]:
    points = [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "equity": "100",
            "gross_return": None,
            "net_return": "0",
        },
        {
            "timestamp": "2026-01-01T01:00:00+00:00",
            "equity": "102",
            "gross_return": None,
            "net_return": "0.02",
        },
    ]
    cost_model = {
        "fees": {"taker_fee_bps": 5.0},
        "slippage": {"slippage_bps": 2.0},
        "funding": {"mode": "included", "total_fee": 0.1},
    }
    stable = {
        "source_layer": "backtest",
        "source_id": "7",
        "strategy_id": 11,
        "strategy_version": "sha256:" + "a" * 64,
        "config_version": "sha256:" + "b" * 64,
        "timeframe": "1h",
        "currency": "USDT",
        "cost_model": cost_model,
        "points": points,
    }
    payload = {
        "schema_version": "strategy_return_series.v1",
        "contract_version": "bitpro-mcp-v1",
        "producer": "bitpro-strategy-evidence-v1",
        **{key: stable[key] for key in ("source_layer", "source_id", "strategy_id")},
        "strategy_version": stable["strategy_version"],
        "config_version": stable["config_version"],
        "symbols": ["BTC/USDT:USDT"],
        "timeframe": "1h",
        "bucket_seconds": 3600,
        "timezone": "UTC",
        "currency": "USDT",
        "precision": {"equity": 8, "return": 12},
        "window": {
            "start_at": points[0]["timestamp"],
            "end_at": points[-1]["timestamp"],
        },
        "gross_return": None,
        "net_return": "0.02",
        "cost_model": cost_model,
        "points": points,
        "data_gaps": ["gross_return_unavailable"],
        "pagination": {"limit": 500, "cursor": "", "next_cursor": "", "total_points": 2},
        "as_of": points[-1]["timestamp"],
        "freshness": "historical",
        "source_hash": canonical_hash(stable),
        "recorded_at": "2026-01-03T00:00:00+00:00",
    }
    payload["content_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key not in {"freshness", "recorded_at"}}
    )
    return payload


def matrix_payload() -> dict[str, Any]:
    payload = {
        "schema_version": "aligned_strategy_return_matrix.v1",
        "contract_version": "bitpro-mcp-v1",
        "producer": "bitpro-strategy-evidence-v1",
        "members": ["backtest:7", "backtest:missing"],
        "denominator": 2,
        "available_count": 1,
        "missing_members": [{"member": "backtest:missing", "reason": "source_not_found"}],
        "alignment_method": "utc_bucket_intersection",
        "bucket_seconds": 3600,
        "sample_count": 2,
        "timestamps": ["2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00"],
        "rows": [
            {
                "member": "backtest:7",
                "source_hash": "sha256:" + "c" * 64,
                "returns": ["0", "0.02"],
            }
        ],
        "comparable": False,
        "reason_codes": ["missing_member"],
        "source_hashes": ["sha256:" + "c" * 64],
        "as_of": "2026-01-01T01:00:00+00:00",
        "recorded_at": "2026-01-03T00:00:00+00:00",
    }
    payload["content_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "recorded_at"}
    )
    return payload


def execution_quality_payload() -> dict[str, Any]:
    payload = {
        "schema_version": "strategy_execution_quality.v1",
        "contract_version": "bitpro-mcp-v1",
        "producer": "bitpro-strategy-evidence-v1",
        "source_layer": "backtest",
        "source_id": "7",
        "strategy_id": 11,
        "strategy_version": "sha256:" + "a" * 64,
        "signal_count": None,
        "order_count": None,
        "fill_count": 3,
        "fill_ratio": None,
        "reject_count": None,
        "cancel_count": None,
        "latency_ms": None,
        "slippage": {"slippage_bps": 2.0},
        "exposure": None,
        "turnover": None,
        "data_gaps": ["signal_count_unavailable", "order_count_unavailable"],
        "errors": [],
        "as_of": "2026-01-01T01:00:00+00:00",
        "source_hash": "sha256:" + "d" * 64,
        "recorded_at": "2026-01-03T00:00:00+00:00",
    }
    payload["content_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "recorded_at"}
    )
    return payload


def rehash(payload: dict[str, Any], *, volatile: set[str]) -> dict[str, Any]:
    value = deepcopy(payload)
    value["content_hash"] = canonical_hash(
        {key: item for key, item in value.items() if key not in volatile | {"content_hash"}}
    )
    return value
