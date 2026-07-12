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

- Sprint 82 control plane: `/research-program list|create|pause|resume|draft|jobs|queue|run|report|cancel`
- API: `POST/GET /api/research/mandates`, `POST /api/research/mandates/{id}/strategy-specs/draft`,
  and `POST/GET /api/research/.../jobs`
- Agent tools: `research_mandate_read`, `research_strategy_spec_draft`
- CLI: `/experiment <prompt>`
- CLI: `/experiment iterate <prompt>`
- CLI: `/strategy library [query]`
- API: `POST /api/strategy/experiments`
- API: `POST /api/strategy/experiments/iterate`
- API: `GET /api/strategy/library?query=<text>&strategy_key=<key>`
- Agent tool: `strategy_library_search`
- Agent tool: `strategy_experiment_plan`
- Search memory: `/memory search momentum_breakout_v1`
- Search API: `GET /api/memory?kind=strategy_knowledge&tag=strategy`

Expected evidence:

- `exp_*` experiment id
- linked `srch_*` research id
- winning `bt_*` backtest id
- candidate variants with params, return, drawdown, trade count, score, and gates
- for iteration runs: prior source memory ids, prior experiment/backtest ids,
  planned variant reasons, and result comparison against prior best evidence
- data source, instrument, bar, and candle count
- critique notes and next-experiment suggestion
- source-bound `strategy_knowledge` memory item
- strategy library summary with source memory ids, best/latest evidence,
  pass/fail counts, failure reasons, and next experiment suggestions

Recommended research loop:

1. Create an operator-reviewed research mandate before any autonomous work.
   It must retain `paper_promotion_mode=manual_approval` and `live_mode=disabled`.
2. Use `/research-program draft <rman_id> <prompt>` to create a bounded
   StrategySpec; it is not a backtest or execution request.
3. Queue a validated draft with a stable idempotency key, then explicitly run
   `/research-program run <rjob_id>`. The worker performs BitPro preflight,
   code validation, one dynamic DB strategy creation, and a bounded matrix.
4. The matrix uses real BitPro OHLCV and fixed chronological in-sample,
   validation, and locked out-of-sample windows. Any insufficient coverage,
   unavailable result, or missing trade/drawdown/return metric is a rejection.
5. `evidence_recorded` means only that deterministic research gates passed; it
   never configures or starts a BitPro paper instance and never implies stable
   profitability. Use `/research-program report <rjob_id>` to inspect result ids,
   windows, metrics, and rejection reasons.
6. Search `/strategy library <strategy or symbol>` before creating a new idea.
7. Treat failed evidence as useful constraints, especially `failure_reasons`.
8. Use `/experiment iterate <prompt>` when continuing or optimizing an existing
   strategy. The workflow reads strategy-library evidence first, plans at most a
   bounded set of adjacent variants, and records why each variant exists.
9. Only run `/experiment` when the next test is grounded in prior evidence or
   clearly explores a new hypothesis.
10. After the experiment completes, re-run `/strategy library` to confirm the
   new memory card is visible in the grouped strategy view.

Improvement claims:

- If no prior evidence exists, the iteration report must say it is creating a
  first baseline.
- If prior or new metrics are missing, the report must refuse to claim
  improvement.
- If the new winner does not beat prior return without worse drawdown, the
  report must mark the result as `not_improved`.

Boundaries:

- Reports are research artifacts only and must not be treated as investment advice.
- Local strategy experiments do not mutate BitPro strategy code, start paper
  simulation, or generate Testnet/live orders.
- Sprint 82 research work can only perform the bounded BitPro backtest handoff.
  It never configures/starts paper, changes a portfolio, or invokes a live tool.
- BitPro strategy creation/backtest/paper workflows must go through BitPro MCP
  tools and their own gates.
