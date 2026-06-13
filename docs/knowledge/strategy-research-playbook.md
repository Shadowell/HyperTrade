# Strategy Research Playbook

Strategy experiments should move through the same evidence loop:

1. State the hypothesis.
2. Select data source, symbol, bar, and sample size.
3. Run deterministic candidate backtests.
4. Compare candidates with explicit evidence gates.
5. Select a winner, then critique result quality and risk.
6. Suggest the next adjacent experiment.
7. Save Markdown and JSON outputs.
8. Write one audited `strategy_knowledge` Memory item.

Current implementation:

- CLI: `/experiment <prompt>`
- API: `POST /api/strategy/experiments`
- Search memory: `/memory search momentum_breakout_v1`
- Search API: `GET /api/memory?kind=strategy_knowledge&tag=strategy`

Expected evidence:

- `exp_*` experiment id
- linked `srch_*` research id
- winning `bt_*` backtest id
- candidate variants with params, return, drawdown, trade count, score, and gates
- data source, instrument, bar, and candle count
- critique notes and next-experiment suggestion
- source-bound `strategy_knowledge` memory item

Boundaries:

- Reports are research artifacts only and must not be treated as investment advice.
- Local strategy experiments do not mutate BitPro strategy code, start paper
  simulation, or generate Testnet/live orders.
- BitPro strategy creation/backtest/paper workflows must go through BitPro MCP
  tools and their own gates.
