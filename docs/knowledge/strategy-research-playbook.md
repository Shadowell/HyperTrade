# Strategy Research Playbook

Strategy experiments should move through the same basic loop:

1. State the hypothesis.
2. Select data source, symbol, bar, and sample size.
3. Run a deterministic backtest.
4. Critique result quality and risk.
5. Suggest the next experiment.
6. Save Markdown and JSON outputs.

Current implementation:

- CLI: `/experiment <prompt>`
- API: `POST /api/strategy/experiments`
- Frontend: `/harness` Strategy Lab

Reports are research artifacts only and must not be treated as investment advice.

