"""Frozen development-window observations, not causal labels or trading approval."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from hypertrade.arc.contracts import ResearchWindowsV1
from hypertrade.arc.universe import declared_symbols
from hypertrade.backtest.remote import RemoteKlineProvider
from hypertrade.strategy.sdk import Candle


def regime_metrics(rows: list[Candle]) -> dict[str, float]:
    if len(rows) < 60:
        raise ValueError("insufficient_regime_history")
    values = [(float(r.high), float(r.low), float(r.close), float(r.volume)) for r in rows]
    if any(
        not all(math.isfinite(v) for v in row) or not 0 < row[1] <= row[2] <= row[0] or row[3] < 0
        for row in values
    ):
        raise ValueError("invalid_regime_candle")
    tr, plus, minus = [], [], []
    for a, b in zip(values, values[1:], strict=False):
        tr.append(max(b[0] - b[1], abs(b[0] - a[2]), abs(b[1] - a[2])))
        up, down = b[0] - a[0], a[1] - b[1]
        plus.append(max(up, 0) if up > down else 0)
        minus.append(max(down, 0) if down > up else 0)
    atr, pdm, mdm = sum(tr[:14]) / 14, sum(plus[:14]) / 14, sum(minus[:14]) / 14
    dx = []
    for i in range(14, len(tr)):
        atr = (atr * 13 + tr[i]) / 14
        pdm = (pdm * 13 + plus[i]) / 14
        mdm = (mdm * 13 + minus[i]) / 14
        dx.append(100 * abs(pdm - mdm) / (pdm + mdm) if pdm + mdm else 0)
    adx = sum(dx[:14]) / 14
    for value in dx[14:]:
        adx = (adx * 13 + value) / 14
    park = [math.log(high / low) ** 2 / (4 * math.log(2)) for high, low, _, _ in values]
    rolling = [math.sqrt(sum(park[i - 13 : i + 1]) / 14) for i in range(13, len(park))]
    volume = sum(v[3] for v in values[-21:-1]) / 20
    short = sum(v[2] for v in values[-10:]) / 10
    long = sum(v[2] for v in values[-30:]) / 30
    old_atr = sum(tr[-42:-28]) / 14
    return {
        "atr_pct": atr / values[-1][2] * 100,
        "atr_expansion_ratio": atr / old_atr if old_atr else 0,
        "parkinson_volatility": rolling[-1],
        "parkinson_percentile": sum(v <= rolling[-1] for v in rolling) / len(rolling) * 100,
        "adx_14": adx,
        "ma_spread_pct": (short / long - 1) * 100,
        "volume_ratio": values[-1][3] / volume if volume else 0,
    }


def collect_regime(client: Any, context: dict[str, Any]) -> dict[str, Any]:
    spec = context["baseline"]["strategy_spec"]
    window = ResearchWindowsV1.model_validate(context["research_windows"])
    start, end = window.window("development")
    cutoff = datetime.combine(end, datetime.min.time(), tzinfo=UTC).timestamp()
    provider = RemoteKlineProvider(client, now=lambda: cutoff)
    universe = declared_symbols(spec)
    sampled = sorted(universe)[:8]
    rows_by_symbol: dict[str, Any] = {}
    for symbol in sampled:
        try:
            rows = provider.read_candles(symbol=symbol, bar=spec["timeframe"], limit=120)
            rows = [r for r in rows if start <= datetime.fromisoformat(r.timestamp).date() < end]
            metrics = regime_metrics(rows)
            source_hash = hashlib.sha256(
                json.dumps(
                    [
                        [
                            r.timestamp,
                            str(r.open),
                            str(r.high),
                            str(r.low),
                            str(r.close),
                            str(r.volume),
                        ]
                        for r in rows
                    ]
                ).encode()
            ).hexdigest()
            rows_by_symbol[symbol] = {
                "state": "observed",
                "metrics": metrics,
                "source_sha256": source_hash,
                "bars": len(rows),
                "start": rows[0].timestamp,
                "end": rows[-1].timestamp,
            }
        except Exception:
            rows_by_symbol[symbol] = {
                "state": "unknown",
                "reason": "verified_development_history_unavailable",
                "metrics": {},
            }
    report = {
        "version": "development_regime.v1",
        "window": [str(start), str(end)],
        "symbols": rows_by_symbol,
        "sampled_symbols": sampled,
        "universe_size": len(universe),
        "coverage": len(sampled) / len(universe) if universe else 0,
        "funding_cost": {"state": "unknown", "reason": "no_development_funding_receipt"},
        "slippage_cost": {"state": "unknown", "reason": "no_development_execution_receipt"},
        "rule": "Observed development-only sample; not a whole-universe or causal conclusion.",
    }
    report["report_id"] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    return report


def validate_structural_changes(changes: Any, policy: dict[str, Any]) -> None:
    if not isinstance(changes, dict) or not 1 <= len(changes) <= 5:
        raise ValueError("structural_changes requires 1-5 authorized operators")
    for name, params in changes.items():
        if name not in policy or not isinstance(params, dict) or set(params) != set(policy[name]):
            raise ValueError("unsupported structural operator or fields")
        for field, rule in policy[name].items():
            value = params[field]
            if "enum" in rule:
                if value not in rule["enum"]:
                    raise ValueError("invalid structural enum")
            elif (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not rule["min"] <= value <= rule["max"]
                or (rule["type"] == "integer" and int(value) != value)
            ):
                raise ValueError("structural parameter outside policy")
        if name == "profit_lock" and params["pullback_pct"] >= params["start_pct"]:
            raise ValueError("profit lock must retain profit")
