# 16 Strategy Agent Workflow

## Purpose

Strategy Workflow v2 packages research and backtesting into an Agent-style experiment path.

## Workflow

1. `hypothesis`: create strategy research from the prompt.
2. `data_selection`: record data source, symbol, bar, and candle count.
3. `backtest`: run Backtrader through the Strategy SDK.
4. `critique`: summarize risk and sample-size limitations.
5. `revision_suggestion`: propose the next experiment.
6. `report`: persist Markdown and structured JSON.

## Persistence

`strategy_experiments` stores:

- prompt
- status
- research id
- backtest id
- Markdown report
- structured JSON workflow output

## Surfaces

- API: `POST /api/strategy/experiments`
- API: `GET /api/strategy/experiments`
- CLI: `/experiment <prompt>`
- Frontend: latest experiment card in `/harness`

All reports include a research-only disclaimer.

