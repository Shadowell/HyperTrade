# Sprint 73 - World Model Defensive Automation

## Goal

Allow a narrow set of configured defensive actions to execute automatically
when the world model detects degraded conditions and deterministic policy/risk
checks approve the action. This phase keeps risk-increasing and offensive
trading actions blocked.

## In Scope

- Define L2 defensive action contract and operator configuration.
- Support a small allowlist of defensive actions, for example:
  - request or trigger paper strategy pause
  - lower paper risk budget where an existing safe control exists
  - cancel clearly stale paper/testnet intents where the current runtime already
    exposes a safe path
  - run an urgent monitor capture
  - raise alert and require human confirmation when execution state is
    ambiguous
- Require idempotency keys for every mutation.
- Evaluate `RiskGovernancePolicy` and action-specific risk checks before any
  execution.
- Persist action attempts, policy decisions, execution result, and rollback or
  follow-up instructions.
- Surface failures and partial execution in alerts and reports.
- Add tests proving blocked actions do not call adapters or exchange paths.

## Out of Scope

- Mainnet live order execution.
- Opening positions, increasing size, adding leverage, switching to higher-risk
  parameters, or moving funds.
- Automatically changing BitPro live strategy allocation.
- Any action without an operator-configured allowlist entry.
- Executing when source evidence is stale, missing, or contradictory.

## Deliverables

- `world_model/defensive_actions.py` with allowlisted action handlers.
- Policy and risk precheck integration.
- `WorldModelActionAttempt` persistence or equivalent trace-backed audit
  record.
- API/admin surfaces to inspect configured defensive actions and action
  attempts.
- Agent report and alert rendering for executed, skipped, rejected, and failed
  defensive actions.
- Tests for idempotency, policy denial, stale-data denial, failure reporting,
  and no-offensive-action behavior.

## Done Means

- Defensive action execution is disabled by default and can be enabled only by
  explicit operator configuration.
- Every executed action has:
  - source `WorldState`
  - selected scenario
  - policy decision
  - idempotency key
  - execution result
  - audit trace
  - review window
- If system health is degraded or evidence is stale, the system refuses to
  execute and requests human confirmation.
- Offensive actions remain blocked even if the LLM requests them.

## Verification

```bash
uv run pytest tests/test_world_model_defensive_actions.py tests/test_risk_governance_policy.py -q
./scripts/check.sh
```

Current focused verification:

- `uv run pytest tests/test_world_model_defensive_actions.py tests/test_risk_governance_policy.py -q`
  passed with 7 tests after adding the defensive-action gate.
- `uv run pytest tests/test_world_model_snapshot.py tests/test_world_model_scenarios.py tests/test_report_blocks.py tests/test_api.py::test_api_exposes_health_harness_and_agent_run -q`
  passed with 10 tests.
- `./scripts/check.sh` passed with frontend lint/test/build, ruff, mypy, and
  full Python pytest (`250 passed`).

Manual or QA checks:

- Enable one fixture defensive action and confirm it executes once with an
  idempotency key.
- Re-run the same action and confirm duplicate execution is prevented.
- Ask for an automatic add-risk action and confirm policy denial appears in
  trace and report.

## Risks / Notes

- This phase changes operational risk. Implementation should prefer fewer
  actions with stronger audit over broad automation.
- BitPro live-write tools remain out of scope unless a later contract adds
  explicit live-risk confirmation and server-side approval gates.

## Handoff

- Sprint 73 implementation entrypoints:
  - `backend/src/hypertrade/world_model/defensive_actions.py`
  - `WORLD_MODEL_DEFENSIVE_ACTIONS_ENABLED`
  - `WORLD_MODEL_DEFENSIVE_ACTION_ALLOWLIST`
  - `GET /api/world-model/defensive-actions`
  - `GET /api/world-model/defensive-action-attempts`
  - `POST /api/world-model/defensive-actions/execute`
- Next likely step: Sprint 74 uses world-model state and defensive-action
  history for portfolio-level strategy scheduling.
