# Memory Policy

HyperTrade Memory is automatic but audited.

Supported memory kinds:

- `market_observation`
- `user_preference`
- `strategy_lesson`
- `strategy_knowledge`
- `risk_warning`
- `agent_note`

Write policy:

- Keep content short and factual.
- Avoid storing secrets, API keys, passwords, or account balances.
- Deduplicate exact repeated active memories by kind and content.
- Store source run and source tool for audit.
- Prefer tags that describe usage, such as `risk`, `strategy`, `market_summary`, or `preference`.
- For strategy experiments, use `strategy_knowledge` with tags such as
  `strategy`, `strategy_experiment`, `evidence`, strategy key, and
  `winner:<variant>`.

Strategy knowledge policy:

- A strategy knowledge item is an evidence card from a completed experiment.
- It should include source experiment/research/backtest ids, winning variant,
  variant count, parameters, metrics, gate results, failure reasons, data
  selection, and next experiment.
- It must preserve the research-only boundary and must not imply paper/live
  promotion approval.
- It must not replace BitPro result tools for page-parity questions; BitPro
  ranking/detail questions still use BitPro MCP result rows and artifacts.
- Strategy library summaries are read models over `strategy_knowledge` cards.
  They may aggregate and rank evidence, but they must keep source memory ids and
  must not invent missing metrics.

Search paths:

- CLI: `/memory search <query>`
- API: `GET /api/memory?query=<query>&tag=<tag>&kind=<kind>`
- Frontend: `/harness` Memory Manager
- Strategy knowledge: `GET /api/memory?kind=strategy_knowledge&tag=strategy`
- Strategy library: `/strategy library [query]` or `GET /api/strategy/library`
