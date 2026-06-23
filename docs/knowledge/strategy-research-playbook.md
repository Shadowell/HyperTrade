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
- CLI: `/strategy library [query]`
- API: `POST /api/strategy/experiments`
- API: `GET /api/strategy/library?query=<text>&strategy_key=<key>`
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
- strategy library summary with source memory ids, best/latest evidence,
  pass/fail counts, failure reasons, and next experiment suggestions

Recommended research loop:

1. Search `/strategy library <strategy or symbol>` before creating a new idea.
2. Treat failed evidence as useful constraints, especially `failure_reasons`.
3. Only run `/experiment` when the next test is grounded in prior evidence or
   clearly explores a new hypothesis.
4. After the experiment completes, re-run `/strategy library` to confirm the
   new memory card is visible in the grouped strategy view.

Boundaries:

- Reports are research artifacts only and must not be treated as investment advice.
- Local strategy experiments do not mutate BitPro strategy code, start paper
  simulation, or generate Testnet/live orders.
- BitPro strategy creation/backtest/paper workflows must go through BitPro MCP
  tools and their own gates.
