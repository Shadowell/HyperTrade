# 20 Connector Framework

## Purpose

The connector framework generalizes external data/tool providers without
turning HyperTrade into a dynamic plugin loader. Connectors are trusted Python
classes shipped in this repository. They describe provider capabilities,
redacted authentication state, health, scopes, tools, and safe read execution.

Agent planning still goes through `AgentPlanner`, `ToolRegistry`, tool policy,
and `AgentKernel` trace. A connector never bypasses those trusted runtime
boundaries.

## Contract Shape

Connector capability output uses a stable JSON shape:

- `connector_id`: stable id such as `bitpro`.
- `display_name`: operator-facing name.
- `health`: status payload. Capability discovery may return `not_checked`
  instead of calling the provider.
- `auth`: token/header/source metadata with `secret_redacted=true`; plaintext
  token values are never returned.
- `supported_scopes`: provider scope names.
- `tools`: descriptors with name, scope, safe-read flag, idempotency flag,
  source of truth, connector id, approval marker, and parameter metadata.
- `idempotency_required_tools`: derived list for operator and policy checks.
- `source_of_truth`: provider evidence source.
- `notes`: short operational boundaries.

The first concrete connector is BitPro:

- `BitProConnector` wraps the existing `BitProToolAdapter`.
- Capability discovery reads local `bitpro_capabilities()` metadata and does
  not require a live upstream request.
- Safe read execution delegates back to the current adapter for tools such as
  `market_klines`, `backtest_get_result`, `paper_dashboard`, and
  `trading_positions`.
- Research/paper mutation tools are advertised with scope and idempotency
  metadata but are not exposed through `execute_read_tool`.

`FixtureConnector` exists for deterministic tests and future eval fixtures.

## Surfaces

- `ConnectorRegistry.default(settings=...)` registers trusted connectors.
- `GET /api/connectors/capabilities` returns redacted connector capabilities.
- `/api/harness/overview.connectors` includes the same capability metadata.
- CLI `/connectors` renders connector health, auth status, scopes, and a sample
  of tool descriptors.
- `ToolDefinition.connector_origin` marks BitPro-backed ToolRegistry rows, for
  example `{"connector_id": "bitpro", "tool": "market_klines"}`.

## Boundaries

- Do not load connector code from untrusted directories or user uploads.
- Do not return tokens, provider keys, cookies, or account credentials.
- Do not copy BitPro business logic or read BitPro databases directly.
- Do not add live execution systems through the connector framework. Live-write
  tools need separate risk, approval, idempotency, and audit contracts.
- Missing upstream data remains a missing-data note, not model-generated prose.

## Verification

Focused coverage lives in `tests/test_connector_framework.py`,
`tests/test_tool_registry.py`, `tests/test_api.py`, and `tests/test_cli.py`.
The important checks are:

- capability output does not include plaintext secret values
- fixture connector can execute a safe read deterministically
- BitPro connector safe reads delegate to the existing adapter
- ToolRegistry metadata includes connector origin for BitPro tools
- API and CLI surfaces expose the redacted connector shape
