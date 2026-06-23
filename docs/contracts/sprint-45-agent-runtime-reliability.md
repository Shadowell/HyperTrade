# Sprint 45 Contract: Agent Runtime Reliability

## Goal

Make the HyperTrade Agent runtime more production-stable by adding explicit
tool policy metadata, durable run controls, timeout/cancellation handling, and
clearer retry/error behavior without changing trading business logic.

## In Scope

- Add a first-class tool policy model for every Agent tool:
  read/write/live-write scope, approval requirement, idempotency requirement,
  source of truth, timeout class, and safe sample limit.
- Expose policy metadata through `/api/harness/tools`, CLI `/tools`, and trace
  output.
- Add run-level cancellation/status semantics for long-running Agent runs.
- Add configurable per-tool timeout handling in `AgentKernel` executor paths.
- Persist structured execution errors so reports and trace do not collapse into
  opaque exception strings.
- Keep BitPro live write tools blocked unless explicit live-risk confirmation
  is later implemented in a separate sprint.

## Out of Scope

- Rewriting the Agent planner.
- Adding new market or BitPro capabilities.
- Executing mainnet live orders.
- Building a scheduler or alert system.
- Changing frontend layout beyond metadata display needed for verification.

## Deliverables

- Tool policy dataclass or schema near `hypertrade.tools.registry`.
- ToolRegistry entries enriched with policy metadata.
- AgentKernel executor timeout/error wrapper.
- API/CLI rendering for policy fields.
- Tests for policy metadata, timeout behavior, error persistence, and CLI/API
  display.
- Documentation updates in `docs/architecture/04-tool-calling.md` and
  `docs/knowledge/tool-usage-guide.md`.

## Design Notes

- Planner tool schemas guide model choice, but trusted Python code must enforce
  policy.
- Policy fields should be stable strings, not prose:
  `scope=read|write|paper_write|testnet_write|live_write`,
  `approval=none|required|blocked`,
  `idempotency=not_required|required`.
- Long-running tools should return a structured timeout payload where possible
  rather than losing the run.
- Trace should show both the requested tool and enforced policy outcome.

## Done Means

- `/api/harness/tools` returns policy metadata for every registered tool.
- `/tools` shows scope/approval/idempotency in a compact form.
- A simulated timeout produces a completed trace/error payload and a report
  missing-data note instead of an unhandled stack trace.
- Existing BitPro and live/testnet safety behavior remains unchanged or safer.

## Verification

```bash
uv run pytest tests/test_tool_registry.py tests/test_agent_planner.py tests/test_cli.py -q
uv run pytest tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run `/tools` and confirm every tool has a purpose plus scope/approval policy.
- Run an Agent prompt that triggers a read tool and inspect trace policy fields.
- Force or mock one tool timeout and confirm the report says data is unavailable.

## Risks / Notes

- Do not expand live-write capability while adding policy metadata.
- Avoid making reports noisy by default; keep full policy details in trace or
  explicit debug mode.

## Handoff

- Next likely step: Sprint 49 can consume the policy metadata for broader risk
  governance.

