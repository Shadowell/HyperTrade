# Sprint 09 Contract: Specific Market Ticker Tool

## Goal

Make the Agent support exact ticker lookup for any listed OKX USDT perpetual swap symbol, not only
full-market summaries or BTC examples.

## Motivation

When a user asks "看下比特币行情", the LLM may currently choose the all-market summary path and return
top movers that do not include BTC. HyperTrade needs a dedicated tool path for prompts about a
specific symbol, while still keeping all-market summaries available.

## In Scope

- Add a `market_ticker` planner tool schema for any listed OKX SWAP symbol or instrument id.
- Normalize common user inputs such as `eth`, `SOL-USDT`, `doge_usdt`, and `PEPE-USDT-SWAP` to OKX
  `*-USDT-SWAP` instrument ids.
- Add repository support for exact `market_tickers.inst_id` reads.
- Add `market.ticker` to the ToolRegistry catalog so `/tools` and `/harness` show the capability.
- Keep REST refresh + PostgreSQL fallback behavior consistent with the existing market summary tool.
- Add tests proving the behavior is not BTC-specific.
- Update project docs and progress.

## Out of Scope

- Historical candle lookup for a symbol.
- Multi-symbol comparison reports.
- Mainnet account balance or live order execution.
- New frontend panels for ticker detail.

## Done Means

- AgentPlanner can call `market_ticker` for a non-BTC symbol.
- AgentKernel can return an exact ticker payload for any normalized OKX USDT SWAP instrument in
  PostgreSQL.
- `./scripts/check.sh` passes.
- Server CLI smoke verifies a non-BTC prompt uses `market_ticker`.

## Verification

```bash
uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q
./scripts/check.sh
ssh root@47.79.36.92 'hypertrade ask "看下ETH行情"'
```
