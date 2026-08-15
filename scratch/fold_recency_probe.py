"""Do the surviving folds sit in the past?

HyperTrade's engine and BitPro's agree closely on the same 90 days, so the candidates
that cleared the evidence gate and then failed BitPro's self-test were not measured
differently -- they were measured over different periods. The gate requires 2 of 4
rolling folds to survive, which a candidate whose edge died recently can satisfy on its
two oldest folds. Print each fold in order to see whether that is what happened.
"""

from __future__ import annotations

import json
import sys

from hypertrade.arc.evidence import MAX_WINDOW_BARS, build_default_window, walk_forward_slices
from hypertrade.arc.store import configure_store, get_controller
from hypertrade.backtest.candidate import bars_from_candles, replay_candidate
from hypertrade.config import get_settings
from hypertrade.db import Database

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
            continue
        symbol = str(attempt.strategy_spec.get("symbol") or "BTC-USDT-SWAP")
        timeframe = str(attempt.strategy_spec.get("timeframe") or "1H")
        bars = bars_from_candles(
            symbol, window.read(symbol=symbol, timeframe=timeframe, limit=MAX_WINDOW_BARS)
        )
        folds = []
        for index, (start, end) in enumerate(walk_forward_slices(len(bars))):
            result = replay_candidate(attempt.strategy_code, list(bars[start:end]), timeframe=timeframe)
            folds.append(
                {
                    "fold": index,
                    "sharpe": round(result.sharpe, 3),
                    "return": round(result.total_return, 4),
                    "trades": len(result.trades),
                }
            )
        print(json.dumps({"attempt": attempt_id, "folds": folds}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "arc_0ea821136f54")
