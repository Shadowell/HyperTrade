# Sprint 48 Contract: Multi-Source Market Intelligence

## Goal

Extend HyperTrade market research beyond basic ticker/candle tools by adding a
safe multi-source intelligence layer for funding, open interest, volume
structure, news, onchain, and sentiment evidence.

## In Scope

- Define a connector-neutral market intelligence result schema.
- Add read-only tools for at least two initial intelligence sources. Suggested
  first sources:
  - OKX funding rate/open interest when available through public APIs.
  - RAG/news-like curated document source or static fixture for deterministic
    tests.
- Add source provenance and freshness fields to every result.
- Add Agent planner guidance for when to use intelligence tools.
- Render compact report sections for market intelligence evidence.
- Keep deterministic fixture fallback for tests and offline development.

## Out of Scope

- Paid data subscriptions unless already configured in environment.
- Trading signal automation.
- Live/paper write actions.
- Full news crawler infrastructure.
- Large data warehouse design.

## Deliverables

- Market intelligence schema and repository/service layer.
- ToolRegistry entries and planner schemas for initial read-only tools.
- AgentKernel executor paths.
- API/CLI surfaces if useful for deterministic validation.
- Report rendering tests.
- Docs in `docs/architecture/07-okx-market-data.md` and
  `docs/knowledge/tool-usage-guide.md`.

## Design Notes

Every intelligence result should include:

- `source`
- `source_path` or API route
- `symbol` or universe
- `as_of`
- `freshness_seconds`
- `metrics`
- `missing_fields`
- `sample`

The report should treat intelligence as context, not as buy/sell advice.

## Done Means

- Agent can answer prompts like `看 ETH 资金费率和持仓变化` by calling the new
  intelligence tools.
- Reports show source, timestamp, metrics, and missing fields.
- Tests can run without network by using fixtures or mocked clients.

## Verification

```bash
uv run pytest tests/test_market_candles_tool.py tests/test_agent_planner.py -q
uv run pytest tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Ask for funding/open-interest context for ETH or BTC.
- Confirm tool trace includes source-backed intelligence tools.

## Risks / Notes

- External data endpoints can change. Keep client failures structured and
  report missing data instead of silently falling back to model text.

## Handoff

- Next likely step: Sprint 50 can standardize market-intelligence report blocks.

