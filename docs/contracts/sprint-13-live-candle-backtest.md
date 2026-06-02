# Sprint 13 Contract: Live Candle Backtest Input

## Goal

Allow Backtrader backtests to use recent OKX REST candles instead of only deterministic sample
candles or caller-supplied candle payloads.

## Motivation

Sprint 10 introduced OKX candle retrieval for market research. Sprint 13 connects that market data
path to the strategy/backtest workflow, closing the loop from live market research to executable
strategy validation.

## In Scope

- Add `BacktestService.run(... use_live_candles, symbol, bar, candle_limit)`.
- Fetch OKX candles through the existing REST client.
- Convert OKX candles into Strategy SDK `Candle` objects for Backtrader.
- Preserve existing behavior:
  - explicit `candles` payload still works
  - default fallback still uses deterministic `sample_candles`
- Add API fields to `POST /api/backtests`.
- Add CLI options:
  - `/backtest --live --symbol ETH --bar 1H --limit 100`
  - works with `latest`, `run`, `srch_*`, and strategy-key targets.
- Persist data-source metadata in `backtest_runs.report_json` and Markdown.
- Add tests for service, API, and CLI option propagation.

## Out of Scope

- Persisting historical candles to PostgreSQL.
- Multi-symbol portfolio backtests.
- Parameter optimization sweeps.
- Strategy code generation.
- Live/Testnet order execution.

## Done Means

- Service tests prove OKX candles are converted into Backtrader candles.
- API tests prove live candle options are accepted and passed through.
- CLI tests prove `/backtest --live --symbol ETH --bar 1H --limit 24` reaches the client.
- `./scripts/check.sh` passes.
- Server smoke verifies a live-candle backtest runs through the host CLI.

## Verification

```bash
uv run pytest tests/test_live_candle_backtest.py tests/test_strategy_backtest_api.py tests/test_cli.py -q
./scripts/check.sh
ssh root@47.79.36.92 'printf "/backtest --live --symbol ETH --bar 1H --limit 100\n:q\n" | hypertrade'
```
