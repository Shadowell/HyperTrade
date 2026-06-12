# 16 Strategy Agent Workflow

## Purpose

Strategy Workflow v2 packages research and backtesting into an Agent-style experiment path.
Sprint 35 upgrades it from a single backtest into a small evidence loop that
compares multiple deterministic candidate variants before recommending the next
experiment.

## Workflow

1. `hypothesis`: create strategy research from the prompt.
2. `data_selection`: record data source, symbol, bar, and candle count.
3. `variant_backtests`: run Backtrader through the Strategy SDK for baseline, fast, and conservative variants.
4. `variant_comparison`: score candidates using pass/fail evidence gates and metrics.
5. `critique`: summarize risk, sample-size limitations, and winning-variant caveats.
6. `revision_suggestion`: propose the next adjacent parameter experiment.
7. `report`: persist Markdown and structured JSON.

## Persistence

`strategy_experiments` stores:

- prompt
- status
- research id
- winning backtest id
- candidate `variants`
- `winner`
- `evidence_gates`
- Markdown report
- structured JSON workflow output

## Surfaces

- API: `POST /api/strategy/experiments`
- API: `GET /api/strategy/experiments`
- CLI: `/experiment <prompt>`
- Frontend: latest experiment card in `/harness`

All reports include a research-only disclaimer. The workflow remains local
research only: it does not mutate BitPro strategy code, start paper simulation,
or generate live/Testnet orders from a winning local backtest.
