# Sprint 49 Contract: Risk Governance Policy

## Goal

Unify HyperTrade permission, approval, scope, and idempotency behavior across
Agent tools so research, paper, testnet, and future live actions have one
auditable governance model.

## In Scope

- Define a `RiskGovernancePolicy` or equivalent policy service.
- Consume tool policy metadata from Sprint 45 when available, or add compatible
  metadata if Sprint 45 has not landed.
- Classify actions into read, research write, paper write, testnet write,
  live diagnostic read, and live write.
- Require idempotency keys for write-like external actions.
- Add policy checks before AgentKernel executes tools with write or live-like
  scope.
- Expose denial reasons in trace and reports.
- Keep existing live-order approval behavior intact.

## Out of Scope

- Mainnet live order execution.
- New BitPro write capabilities.
- UI-heavy approval workflow redesign.
- Exchange account risk modeling beyond existing checks.

## Deliverables

- Policy service/module and tests.
- AgentKernel enforcement hook.
- Trace/report fields for policy result.
- CLI/API display for denied or approval-required actions.
- Docs in `docs/architecture/14-risk-engine.md` and
  `docs/knowledge/tool-usage-guide.md`.

## Design Notes

Policy should answer:

- Is this tool allowed?
- Does it require approval?
- Does it require idempotency?
- What fields must be present?
- What source evidence or confirmation is required?
- What error should the operator see?

Policy decisions should be deterministic and testable without an LLM.

## Done Means

- Read tools continue to run without approval.
- Research/paper writes are explicitly classified and traced.
- Live-write actions remain blocked or approval-gated.
- Missing idempotency or required confirmation fields produce clear denials.

## Verification

```bash
uv run pytest tests/test_live_order_intents.py tests/test_tool_registry.py -q
uv run pytest tests/test_agent_acceptance.py tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- Trigger a permitted read tool and inspect policy trace.
- Trigger a blocked or approval-required action and inspect denial text.

## Risks / Notes

- Do not loosen any live-risk boundary while consolidating policy.
- Keep policy logic independent from model wording.

## Handoff

- Next likely step: Sprint 51 can use governance policy for scheduled monitors
  and notification actions.

