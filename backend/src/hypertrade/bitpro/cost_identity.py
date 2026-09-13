"""Read the frozen cost identity; BitPro alone selects fee and slippage values."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


def source_cost_policy_hash(
    payload: dict[str, Any], strategy_id: int, strategy_code: str
) -> str | None:
    """Unknown source/cost evidence must not become a comparable development result."""
    try:
        source = payload.get("strategy", payload)
        if (
            str(source["id"]) != str(strategy_id)
            or source["script_content"] != strategy_code
            or source["exchange"] != "okx"
        ):
            return None
        config = source["config"]
        policy = config["_research_cost_policy"]
        values = policy["values"]
        if (
            config.get("_freeze_research_costs") is not True
            or policy.get("version") != "research_costs.v1"
            or policy.get("source") != "bitpro_backtest_cost_resolver"
            or policy.get("exchange") != "okx"
            or policy.get("market_type") != "swap"
            or not isinstance(values, dict)
            or set(values) != {"taker_fee_bps", "maker_fee_bps", "slippage_bps", "funding_mode"}
        ):
            return None
        for key in ("taker_fee_bps", "maker_fee_bps", "slippage_bps"):
            value = values[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or isinstance(config[key], bool)
                or config[key] != value
            ):
                return None
        if (
            values["funding_mode"] not in ("not_modeled", "strategy_defined_or_not_modeled")
            or config["funding_mode"] != values["funding_mode"]
        ):
            return None
        digest = hashlib.sha256(
            json.dumps(
                {k: v for k, v in policy.items() if k != "hash"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        return digest if policy.get("hash") == digest else None
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        return None
