"""Does HyperTrade's engine also lose money on the 90 days BitPro tested?

HyperTrade's evidence gate judges the last 30% of up to 20000 1H bars (~250 days) and
scored these candidates well; BitPro's self-test replays the last 90 days of that same
span and reports them negative. Two explanations fit: the edge decayed inside the recent
third of the held-out window, or the two runtimes disagree about the same trades. Replay
each candidate with HyperTrade's own engine over exactly BitPro's 90 days to tell them
apart.
"""

from __future__ import annotations

import json
import sys

from hypertrade.arc.evidence import IN_SAMPLE_FRACTION, MAX_WINDOW_BARS, build_default_window
from hypertrade.arc.store import configure_store, get_controller
from hypertrade.config import get_settings
from hypertrade.db import Database
from hypertrade.backtest.candidate import bars_from_candles, replay_candidate

BARS_PER_DAY = 24
BITPRO_SELF_TEST_DAYS = 90
TARGETS = ("att_blue_3b8501", "att_blue_7c40c0", "att_mut1_3b8501", "att_mut1_7c40c0")


def main(mission_id: str) -> None:
    configure_store(Database(get_settings().database_url))
    controller = get_controller(mission_id)
    if controller is None:
        raise SystemExit(f"mission {mission_id} not found")
    attempts = {a.attempt_id: a for a in controller.projection.attempts}
    window = build_default_window()

    for attempt_id in TARGETS:
        attempt = attempts.get(attempt_id)
        if attempt is None:
            print(f"{attempt_id}: not in mission")
            continue
        symbol = str(attempt.strategy_spec.get("symbol") or "BTC-USDT-SWAP")
        timeframe = str(attempt.strategy_spec.get("timeframe") or "1H")
        candles = window.read(symbol=symbol, timeframe=timeframe, limit=MAX_WINDOW_BARS)
        bars = bars_from_candles(symbol, candles)
        held_out = bars[int(len(bars) * IN_SAMPLE_FRACTION) :]
        recent = bars[-(BARS_PER_DAY * BITPRO_SELF_TEST_DAYS) :]

        row: dict[str, object] = {
            "attempt": attempt_id,
            "family": attempt.strategy_spec.get("family"),
            "window_bars": len(bars),
        }
        for label, slice_ in (("ht_held_out", held_out), ("ht_recent_90d", recent)):
            result = replay_candidate(attempt.strategy_code, list(slice_), timeframe=timeframe)
            row[label] = {
                "bars": len(slice_),
                "sharpe": round(result.sharpe, 4),
                "total_return": round(result.total_return, 5),
                "trades": len(result.trades),
            }
        print(json.dumps(row))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "arc_0ea821136f54")
