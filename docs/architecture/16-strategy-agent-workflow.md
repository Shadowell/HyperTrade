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
8. `knowledge_memory`: persist one compact, audited `strategy_knowledge` memory item for future retrieval.

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

The existing Memory service stores the reusable strategy knowledge card rather
than adding a separate strategy-library table. Each completed experiment writes
one `strategy_knowledge` item with experiment/research/backtest ids, winning
variant, variant count, parameters, return, drawdown, trade count, gate results,
failure reasons, data selection, and next-experiment guidance. Tags include
`strategy`, `strategy_experiment`, `evidence`, the strategy key, and the winning
variant so Agent runs can retrieve prior evidence through normal Memory search.

Sprint 44 adds `StrategyLibraryService` as a read model over those Memory cards.
It groups evidence by strategy key and returns best/latest evidence, pass/fail
counts, variant summaries, failure reasons, next experiments, and source memory
ids. This makes the local strategy library an auditable view over Memory, not a
second persistence path.

## Surfaces

- API: `POST /api/strategy/experiments`
- API: `GET /api/strategy/experiments`
- API: `GET /api/memory?kind=strategy_knowledge`
- API: `GET /api/strategy/library?query=<text>&strategy_key=<key>`
- CLI: `/experiment <prompt>`
- CLI: `/memory search <strategy or variant>`
- CLI: `/strategy library [query]`
- Agent tool: `strategy_library_search`
- Frontend: latest experiment card in `/harness`

All reports include a research-only disclaimer. The workflow remains local
research only: it does not mutate BitPro strategy code, start paper simulation,
or generate live/Testnet orders from a winning local backtest. Strategy
knowledge memory keeps the same boundary and is evidence indexing, not
promotion approval.
