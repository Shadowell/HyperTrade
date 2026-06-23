# Sprint 54 Contract: Connector Framework

## Goal

Generalize external data/tool integration so HyperTrade can add new read-only
research sources and future execution-state providers without hardcoding every
provider into the Agent runtime.

## In Scope

- Define a connector interface for capability discovery, health, tool
  descriptors, authentication metadata, and safe read execution.
- Keep secrets server-side and never expose plaintext token values.
- Add connector registry configuration with BitPro represented as the first
  concrete connector or compatibility adapter.
- Add a fixture connector for deterministic tests.
- Expose connector capabilities through API/CLI/ToolRegistry in a stable shape.
- Document how to add a new connector.

## Out of Scope

- Replacing existing BitPro adapter behavior in one large rewrite.
- New live execution systems.
- Dynamic plugin installation from untrusted code.
- Frontend marketplace UI.

## Deliverables

- Connector protocol/interface.
- Connector registry/service.
- Compatibility path for current BitPro adapter.
- Fixture connector tests.
- Docs in a new `docs/architecture/19-connector-framework.md` or similar.
- Runbook or knowledge doc for adding a connector.

## Design Notes

Connector capabilities should include:

- connector id
- display name
- health status
- auth status without secret values
- supported scopes
- tools
- idempotency requirements
- source-of-truth notes

Connector tools should still flow through AgentKernel policy and trace rather
than bypassing the trusted execution layer.

## Done Means

- Existing BitPro behavior still works.
- A fixture connector can be registered and queried in tests.
- Tool metadata can include connector origin.
- Adding a new read-only source no longer requires editing unrelated Agent
  planner/report code beyond explicit tool registration.

## Verification

```bash
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_tool_registry.py -q
uv run pytest tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Inspect connector capability output and verify no secret plaintext appears.
- Confirm BitPro MCP health/capabilities still work after registry routing.

## Risks / Notes

- Do not over-abstract before the first compatibility path works.
- Keep connector execution inside trusted server code.

## Handoff

- Next likely step: Sprint 48 or future data-source sprints can add connectors
  through this registry.

