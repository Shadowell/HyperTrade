# Sprint 85 - BitPro Paper Snapshot Integration

## Goal

Use BitPro's read-only `paper_snapshot(strategy_id|instance_id)` as the single strategy-scoped paper-evidence source for HyperTrade observation and review.

## Scope

- Add the BitPro MCP adapter, API, and Agent read-tool surface for `paper_snapshot`.
- Replace promotion observation's dashboard/event/equity/performance aggregation with the immutable snapshot.
- Preserve the returned identity, versions, metrics, coverage, and source payload in the promotion evidence ledger.
- Keep all paper and live lifecycle writes blocked from Agent/portfolio review paths.

## Verification

```bash
uv run pytest tests/test_paper_promotion.py tests/test_bitpro_mcp_adapter.py -q
uv run pytest tests/test_agent_acceptance.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```
