# Sprint 10 Contract: Market Candles Research

## Goal

Upgrade single-symbol market research from latest ticker snapshots to recent OKX candlestick trend
features, so the Agent can answer prompts such as "看下 ETH 这两天走势" or "SOL 4H 是突破还是回调".

## Motivation

Sprint 09 made exact ticker lookup work for any listed OKX SWAP symbol, but ticker data is only a
point-in-time snapshot. Trend research needs recent OHLCV candles and deterministic feature
extraction before the LLM writes a report.

## In Scope

- Add OKX candle parsing for `/api/v5/market/candles` array payloads.
- Add `OkxRestClient.fetch_candles(inst_id, bar, limit)`.
- Add deterministic candle feature extraction:
  - candle count and time range
  - open, close, high, low
  - interval return percentage
  - interval range percentage
  - close position within the range
  - volume totals
  - MA20 and MA60
  - simple trend bias: `up`, `down`, or `range`
- Add planner tool schema `market_candles`.
- Add ToolRegistry entry `market.candles`.
- Add AgentKernel execution and stable report block for K-line trend features.
- Add tests for parser, feature extraction, AgentKernel payload, planner call, and report rendering.

## Out of Scope

- Persisting historical candles to PostgreSQL.
- Multi-symbol comparison.
- Backtest data replacement.
- Trading signals, order intent, or live execution.
- Frontend charting.

## Done Means

- Unit tests prove non-BTC symbols can fetch and summarize candles.
- Trend prompts can route to `market_candles` through the LLM planner.
- CLI/API answers include a stable "K线趋势特征" block when candle data is available.
- `./scripts/check.sh` passes.
- Server CLI smoke verifies a non-BTC trend prompt uses `market_candles`.

## Verification

```bash
uv run pytest tests/test_market_candles_tool.py tests/test_agent_planner.py -q
./scripts/check.sh
ssh root@47.79.36.92 'hypertrade ask "看下ETH这两天走势"'
```
