# Paper inventory timeframe and benchmark sampling

## Scope

BitPro's running strategy inventory may omit a top-level timeframe even when the strategy config and its identity-checked Paper dashboard provide one. Preserve the actual strategy timeframe in the read-only performance row. Use a separately declared hourly buy-and-hold sampling period for 1m, 5m, 15m, and 1h strategies across the same completed 14-day window.

## Requirements

- Resolve timeframe only from explicit inventory/config and identity-checked dashboard fields. Missing, invalid, or conflicting fields remain unknown; never infer from a title or silently default to 1h.
- Keep the existing strategy identity gate and return-based ranking intact. Make no per-strategy reads beyond the existing dashboard reads.
- Interpret each hourly OHLCV timestamp as its bar opening. At each start, seven-day split, and end boundary, use the close of the bar that ended at that boundary. Do not consume later bars.
- Request a bounded historical hour grid using BitPro's start/end contract. Reject incomplete, duplicated, misaligned, conflicting, or out-of-window bars with an explicit benchmark fallback. Multi-symbol members must share the complete grid.
- Keep strategy timeframe separate from benchmark sampling timeframe in evidence. Do not change evolution admission, budget, Paper state, or BitPro.

## Acceptance

- HTTP mock adapter tests pass for 1m, 5m, 15m, and 1h sources and verify bounded 1h requests, identity, sorting, missing/conflicting fields, and no extra strategy detail calls.
- Benchmark tests prove exact close-boundary semantics, including a price jump after a boundary that cannot affect that boundary's comparison.
- Missing bars and invalid evidence visibly fall back to the absolute basis. Project check passes.
