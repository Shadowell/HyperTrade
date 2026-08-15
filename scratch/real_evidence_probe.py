"""Run every strategy family against the real configured history window.

Answers what the synthetic tests cannot: does anything the blue team proposes survive
held-out real market data? Intended to be run where a window actually exists - a host
with the BitPro archive mounted, or with ARC_EVIDENCE_LIVE_FALLBACK_ENABLED=true.

    uv run python scratch/real_evidence_probe.py [SYMBOL] [TIMEFRAME]
"""

from __future__ import annotations

import sys

from hypertrade.arc.adversarial import BlueTeamQuant, RedTeamQuant
from hypertrade.arc.evidence import (
    HistoricalEvidenceGate,
    build_default_window,
    preflight_window,
)
from hypertrade.research.codegen import FAMILIES


class _CachedWindow:
    """Fetch once, serve every family the identical window so results are comparable."""

    def __init__(self, symbol: str, timeframe: str, limit: int) -> None:
        self._candles = build_default_window().read(
            symbol=symbol, timeframe=timeframe, limit=limit
        )

    def read(self, *, symbol: str, timeframe: str, limit: int):
        return self._candles


# The direction is keyword-matched off the objective text and defaults to long_only, so
# the probe has to say the words to get the other two compiled at all.
DIRECTIONS = {
    "long_only": "仅做多",
    "short_only": "仅做空",
    "long_short": "多空双向",
}


def main(argv: list[str]) -> int:
    symbols = (argv[1] if len(argv) > 1 else "BTC-USDT-SWAP").split(",")
    timeframe = argv[2] if len(argv) > 2 else "1H"
    bars = int(argv[3]) if len(argv) > 3 else 1_500
    all_survivors: list[str] = []
    for symbol in symbols:
        all_survivors += run_symbol(symbol.strip(), timeframe, bars)
    print(f"\n==== {len(all_survivors)} survivors across {len(symbols)} symbols ====")
    for name in all_survivors:
        print(f"  {name}")
    return 0


def run_symbol(symbol: str, timeframe: str, bars: int) -> list[str]:
    report = preflight_window(symbol=symbol, timeframe=timeframe, bars=bars)
    print(f"\n######## {symbol} ######## {report['bars_available']} bars, "
          f"{report['walk_forward_folds']} folds")
    if not report["evidence_possible"]:
        print("No window available, so no candidate can be judged on evidence here.")
        return []

    window = _CachedWindow(symbol, timeframe, report["bars_available"])
    red = RedTeamQuant(evidence_gate=HistoricalEvidenceGate(window, bars=bars))
    blue = BlueTeamQuant()

    survivors: list[str] = []
    for family in FAMILIES:
        print(f"\n=== {family.key} ===")
        for direction, phrase in DIRECTIONS.items():
            attempt = blue.propose_initial_strategy(
                objective=f"{phrase} probe {family.key}",
                symbol=symbol,
                timeframe=timeframe,
                family_key=family.key,
            )
            compiled = attempt.strategy_spec.get("direction")
            passed, metrics, findings = red.evaluate_adversarial_attack(attempt)
            if passed:
                survivors.append(f"{symbol} {family.key}/{compiled} oos={metrics.get('out_of_sample_sharpe')}")
            oos = metrics.get("out_of_sample_sharpe")
            win = metrics.get("win_rate")
            print(
                f"  {compiled:11s} pass={passed!s:5s} "
                f"oos_sharpe={'n/a' if oos is None else round(oos, 2):>7} "
                f"is_sharpe={round(metrics.get('in_sample_sharpe', 0.0), 2):>7} "
                f"trades={metrics.get('out_of_sample_trades'):>4} "
                f"win={'n/a' if win is None else f'{win:.0%}':>4} "
                f"dd={metrics.get('out_of_sample_max_drawdown', 0.0):.1%}"
            )
            if direction != compiled:
                print(f"      note: asked for {direction}, compiled {compiled}")
            for finding in findings:
                print(f"      [{finding.severity}] {finding.code}")

    total = len(FAMILIES) * len(DIRECTIONS)
    print(f"\n{symbol}: {len(survivors)}/{total} survived real held-out evidence")
    return survivors


if __name__ == "__main__":
    sys.exit(main(sys.argv))
