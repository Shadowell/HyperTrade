# Sprint 11 Contract: Market Relative Strength Compare

## Goal

Let the Agent compare multiple OKX SWAP symbols, such as "比较 ETH 和 SOL 哪个更强", using the
candle trend features from Sprint 10.

## Motivation

Single-symbol trend research answers "how is this symbol doing". Trading research often needs the
next step: "which symbol is stronger under the same timeframe". Sprint 11 adds a lightweight,
transparent relative-strength layer without creating trading signals or order advice.

## In Scope

- Add planner tool schema `market_compare`.
- Add ToolRegistry entry `market.compare`.
- Add AgentKernel execution for comparing 2-6 symbols.
- Reuse `market_candles` summaries for each symbol.
- Rank symbols by a deterministic strength score:
  - interval return contribution
  - close position contribution
  - simple trend bias bonus/penalty
- Add a stable "多标的强弱比较" report block.
- Add tests for payload ranking, report rendering, and planner tool calls.

## Out of Scope

- Cross-exchange comparison.
- Portfolio allocation.
- Pair trading or spread modeling.
- Live/testnet order execution.
- Frontend charting.

## Done Means

- `market_compare` can rank non-BTC symbols such as ETH and SOL.
- CLI/API output includes ranking, leader, score, return, close position, and trend bias.
- `./scripts/check.sh` passes.
- Server CLI smoke verifies a comparison prompt uses `market_compare`.

## Verification

```bash
uv run pytest tests/test_market_compare_tool.py tests/test_agent_planner.py -q
./scripts/check.sh
ssh root@47.79.36.92 'hypertrade ask "比较 ETH 和 SOL 哪个更强"'
```
