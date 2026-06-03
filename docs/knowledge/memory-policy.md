# Memory Policy

HyperTrade Memory is automatic but audited.

Supported memory kinds:

- `market_observation`
- `user_preference`
- `strategy_lesson`
- `risk_warning`
- `agent_note`

Write policy:

- Keep content short and factual.
- Avoid storing secrets, API keys, passwords, or account balances.
- Deduplicate exact repeated active memories by kind and content.
- Store source run and source tool for audit.
- Prefer tags that describe usage, such as `risk`, `strategy`, `market_summary`, or `preference`.

Search paths:

- CLI: `/memory search <query>`
- API: `GET /api/memory?query=<query>&tag=<tag>&kind=<kind>`
- Frontend: `/harness` Memory Manager

