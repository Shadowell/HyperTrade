# Connector Framework Guide

Use connectors when HyperTrade needs a new trusted external research or
execution-state source. Connectors are not dynamic plugins; they are reviewed
server-side code in `backend/src/hypertrade/connectors/`.

## Add A Connector

1. Create a connector class implementing the protocol from
   `hypertrade.connectors.base`.
2. Return a `ConnectorCapability` with:
   `connector_id`, `display_name`, `health`, redacted `auth`,
   `supported_scopes`, `tools`, `source_of_truth`, and operational notes.
3. Keep capability discovery cheap and secret-safe. It may report
   `health.status=not_checked` instead of calling the provider.
4. Add only safe read execution to `execute_read_tool`. Write, paper, testnet,
   or live mutation tools must stay behind explicit Agent tool registration,
   policy, idempotency, risk, and approval gates.
5. Register the connector in `ConnectorRegistry.default` only after tests prove
   redaction, safe-read behavior, and source-of-truth metadata.
6. If the connector backs Agent tools, add `ToolRegistry` rows with
   `connector_origin`, policy metadata, and focused planner/kernel tests.

## Secret Rules

- Store provider tokens only in server-side settings or environment variables.
- Return `configured`, `header`, `token_env`, and `secret_redacted`; never return
  plaintext tokens or provider keys.
- Do not place secrets in fixtures, docs, screenshots, trace payloads, or
  sample reports.

## BitPro Compatibility Path

`BitProConnector` is the reference implementation. It wraps the existing
`BitProToolAdapter`, so current BitPro behavior remains intact while connector
capabilities become provider-neutral. Safe read tools can be queried through
the connector, but strategy/backtest/paper mutation tools still flow through
their existing Agent tools and policy checks.

## Operator Checks

- `GET /api/connectors/capabilities`
- CLI `/connectors`
- `/api/harness/overview` field `connectors`
- `uv run pytest tests/test_connector_framework.py tests/test_tool_registry.py -q`

When output is correct, operators should see connector ids, health/auth status,
scopes, tool descriptors, idempotency requirements, and source-of-truth notes,
with no plaintext secret values.
