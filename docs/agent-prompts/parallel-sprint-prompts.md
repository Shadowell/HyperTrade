# Parallel Sprint Agent Prompts

Use these prompts to launch separate Agents for the post-Sprint-44 HyperTrade
roadmap. Each prompt is intentionally self-contained. Give one prompt to one
Agent, preferably in a fresh thread or worktree.

Common rule for every Agent:

- Work in `/Users/jie.feng/Dev/Github/Private/HyperTrade`.
- Read `AGENTS.md`, `README.md`, `docs/spec.md`, `docs/progress.md`,
  `docs/architecture/18-hypertrade-capability-roadmap.md`, and your assigned
  sprint contract before editing.
- Run `git status --short` before editing.
- Do not overwrite unrelated user or Agent changes.
- Stay inside the assigned sprint boundary.
- Do not copy BitPro business logic or connect directly to BitPro databases.
- Do not commit secrets, tokens, provider keys, OKX credentials, database files,
  or production `.env`.
- Add focused tests before or alongside implementation.
- Update `docs/progress.md` and any relevant architecture/knowledge docs.
- Run targeted tests, then `./scripts/check.sh`.
- If checks pass on `main`, commit and push to `origin/main` so deployment runs.
- Final report must include changed files, tests, deployment/run status if
  pushed, and any skipped or blocked items.

## Agent 45 Prompt: Agent Runtime Reliability

```text
You are Agent 45 for HyperTrade.

Goal:
Implement Sprint 45: Agent Runtime Reliability.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-45-agent-runtime-reliability.md
- docs/architecture/04-tool-calling.md
- docs/architecture/12-agent-graph-langgraph-runtime.md
- backend/src/hypertrade/tools/registry.py
- backend/src/hypertrade/agent/kernel.py
- backend/src/hypertrade/cli.py

Scope:
- Add explicit tool policy metadata: scope, approval, idempotency, source of
  truth, timeout class, safe sample limit.
- Expose policy metadata through /api/harness/tools and CLI /tools.
- Add structured timeout/error handling around AgentKernel tool execution.
- Preserve compact default reports; detailed policy belongs in trace/debug
  surfaces.

Do not:
- Add new BitPro capabilities.
- Loosen live-write restrictions.
- Rewrite the planner.
- Touch frontend unless required for metadata visibility.

Implementation guidance:
- Keep policy strings stable and testable.
- Trusted Python code enforces policy; planner descriptions only guide model
  tool choice.
- Timeout failures should become structured tool outputs where possible, not
  unhandled stack traces.

Verification:
- uv run pytest tests/test_tool_registry.py tests/test_agent_planner.py tests/test_cli.py -q
- uv run pytest tests/test_agent_acceptance.py -q
- ./scripts/check.sh

Final handoff:
- Report the policy fields added, tools covered, tests run, and any tool that
  still lacks complete policy metadata.
```

## Agent 46 Prompt: Strategy Evidence Schema

```text
You are Agent 46 for HyperTrade.

Goal:
Implement Sprint 46: Strategy Evidence Schema.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-46-strategy-evidence-schema.md
- docs/architecture/06-memory.md
- docs/architecture/16-strategy-agent-workflow.md
- backend/src/hypertrade/strategy/experiment.py
- backend/src/hypertrade/strategy/library.py
- backend/src/hypertrade/memory/service.py
- tests/test_strategy_library.py
- tests/test_strategy_backtest_api.py

Scope:
- Define a versioned StrategyEvidence JSON schema.
- Make new strategy_knowledge Memory cards schema-backed.
- Keep legacy semi-structured text cards readable.
- Update StrategyLibraryService to prefer structured payloads and fall back to
  legacy parsing.
- Preserve existing public /api/strategy/library response shape.

Do not:
- Add optimizer infrastructure.
- Auto-promote to paper/testnet/live.
- Read BitPro databases directly.
- Remove support for existing production memory cards.

Implementation guidance:
- Store decimal-like metrics as strings when exactness matters.
- Missing fields must become n/a or empty lists, never invented values.
- Add tests with new-only, old-only, and mixed evidence.

Verification:
- uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py -q
- uv run pytest tests/test_cli.py tests/test_agent_planner.py -q
- ./scripts/check.sh

Final handoff:
- Report schema fields, migration/backward-compat behavior, tests run, and any
  legacy field that remains best-effort.
```

## Agent 47 Prompt: Evidence-Driven Strategy Loop

```text
You are Agent 47 for HyperTrade.

Goal:
Implement Sprint 47: Evidence-Driven Strategy Loop.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-47-evidence-driven-strategy-loop.md
- docs/architecture/16-strategy-agent-workflow.md
- docs/knowledge/strategy-research-playbook.md
- backend/src/hypertrade/strategy/library.py
- backend/src/hypertrade/strategy/experiment.py
- backend/src/hypertrade/agent/planner.py
- backend/src/hypertrade/agent/kernel.py

Scope:
- Add an evidence-based strategy iteration workflow.
- Before iterating, read strategy-library evidence.
- Generate bounded variants with explicit reasons from prior pass/fail evidence.
- Run local backtests or existing BitPro MCP backtests only through safe tools.
- Compare new results against prior evidence and write new strategy evidence.

Do not:
- Build large parameter sweeps.
- Promote to paper/live automatically.
- Claim improvement when sample size or metrics are insufficient.
- Use model memory instead of strategy_library_search evidence.

Implementation guidance:
- If no prior evidence exists, say this is a first baseline.
- Failed evidence should constrain new variants.
- Every variant must include a reason and source evidence ids.

Verification:
- uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py -q
- uv run pytest tests/test_agent_planner.py tests/test_agent_acceptance.py -q
- ./scripts/check.sh

Final handoff:
- Report the new iteration entrypoint, how prior evidence is used, tests run,
  and remaining limitations around sample size or BitPro result coverage.
```

## Agent 48 Prompt: Multi-Source Market Intelligence

```text
You are Agent 48 for HyperTrade.

Goal:
Implement Sprint 48: Multi-Source Market Intelligence.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-48-multi-source-market-intelligence.md
- docs/architecture/07-okx-market-data.md
- docs/knowledge/tool-usage-guide.md
- backend/src/hypertrade/market/
- backend/src/hypertrade/agent/planner.py
- backend/src/hypertrade/agent/kernel.py
- backend/src/hypertrade/tools/registry.py

Scope:
- Add read-only market intelligence beyond ticker/candles.
- Start with at least two source types, such as funding/open interest and a
  deterministic fixture or curated RAG/news-like source.
- Include source, timestamp, freshness, metrics, missing fields, and samples.
- Add planner schema, ToolRegistry entry, AgentKernel execution, and compact
  report rendering.

Do not:
- Add trading automation.
- Add paid provider dependency unless already configured.
- Hide endpoint failures behind model prose.
- Trigger paper/live writes.

Implementation guidance:
- Tests must not require live network.
- Use fixture or mocked clients for deterministic cases.
- Treat intelligence as context, not advice.

Verification:
- uv run pytest tests/test_market_candles_tool.py tests/test_agent_planner.py -q
- uv run pytest tests/test_agent_acceptance.py -q
- ./scripts/check.sh

Final handoff:
- Report source types added, tool names, data provenance fields, tests run, and
  known external endpoint limitations.
```

## Agent 49 Prompt: Risk Governance Policy

```text
You are Agent 49 for HyperTrade.

Goal:
Implement Sprint 49: Risk Governance Policy.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-49-risk-governance-policy.md
- docs/architecture/14-risk-engine.md
- backend/src/hypertrade/risk/
- backend/src/hypertrade/live/service.py
- backend/src/hypertrade/agent/kernel.py
- backend/src/hypertrade/tools/registry.py

Scope:
- Add or extend a deterministic governance policy service.
- Classify tools/actions as read, research write, paper write, testnet write,
  live diagnostic read, or live write.
- Enforce approval/idempotency/confirmation requirements before executing
  write-like or live-like actions.
- Surface policy decisions in trace and report error payloads.

Do not:
- Enable mainnet live execution.
- Add new BitPro write tools.
- Replace existing live order approval flow.
- Depend on LLM wording for policy enforcement.

Implementation guidance:
- Policy should answer: allowed, approval required, idempotency required,
  required fields, denial reason.
- Keep output deterministic and testable.

Verification:
- uv run pytest tests/test_live_order_intents.py tests/test_tool_registry.py -q
- uv run pytest tests/test_agent_acceptance.py tests/test_cli.py -q
- ./scripts/check.sh

Final handoff:
- Report policy categories, enforcement points, blocked actions tested, and any
  actions still using legacy checks.
```

## Agent 50 Prompt: Report Provenance System

```text
You are Agent 50 for HyperTrade.

Goal:
Implement Sprint 50: Report Provenance System.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-50-report-provenance-system.md
- docs/architecture/04-tool-calling.md
- docs/architecture/11-cli-conversation-harness.md
- backend/src/hypertrade/agent/kernel.py
- backend/src/hypertrade/cli.py

Scope:
- Define reusable report block schema/helpers.
- Convert at least two existing report paths to use report blocks; recommended:
  strategy library and BitPro paper monitoring.
- Preserve compact default rendering and audit/detail rendering.
- Include source refs, metrics, missing data, risk boundary, and next actions.

Do not:
- Rewrite all report rendering in one pass.
- Add frontend report redesign.
- Add external data connectors.
- Show raw tool JSON by default.

Implementation guidance:
- Maintain existing Markdown compatibility.
- Missing data must appear explicitly.
- Report JSON should be frontend-friendly.

Verification:
- uv run pytest tests/test_market_candles_tool.py tests/test_cli.py -q
- uv run pytest tests/test_agent_acceptance.py -q
- ./scripts/check.sh

Final handoff:
- Report the block schema, converted report paths, audit-mode behavior, tests
  run, and paths still using legacy Markdown rendering.
```

## Agent 51 Prompt: Monitoring And Alerts

```text
You are Agent 51 for HyperTrade.

Goal:
Implement Sprint 51: Monitoring And Alerts.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-51-monitoring-alerts.md
- backend/src/hypertrade/bitpro/paper_monitor.py
- backend/src/hypertrade/agent/kernel.py
- backend/src/hypertrade/cli.py
- docs/runbooks/deployment-smoke.md

Scope:
- Add monitor definitions and monitor run persistence.
- Support read-only monitor types for BitPro paper dashboard/events/equity,
  strategy-library evidence freshness, and connector health.
- Add alert events for drawdown, stale data, error count, missing artifacts, and
  drift thresholds.
- Add CLI/API surfaces to list monitors, run one manually, and inspect alerts.

Do not:
- Auto-pause/start/stop paper strategies.
- Trigger live or paper write tools.
- Build full incident-management UI.
- Infer missing per-strategy metrics.

Implementation guidance:
- Start manual-run first if scheduler scope is too broad.
- Persist source tools and source ids.
- Alerts should include threshold and observed value.

Verification:
- uv run pytest tests/test_bitpro_paper_monitor.py tests/test_cli.py -q
- uv run pytest tests/test_agent_acceptance.py -q
- ./scripts/check.sh

Final handoff:
- Report monitor types, alert thresholds, persistence shape, tests run, and
  scheduler limitations if manual-only.
```

## Agent 52 Prompt: Frontend Operator Console

```text
You are Agent 52 for HyperTrade.

Goal:
Implement Sprint 52: Frontend Operator Console.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-52-frontend-operator-console.md
- docs/architecture/09-frontend-harness.md
- frontend/src/
- backend/src/hypertrade/main.py

Scope:
- Add Strategy Library view backed by /api/strategy/library.
- Add monitor/alert panels if Sprint 51 APIs exist; otherwise implement clear
  empty states and API-client seams.
- Add evidence drilldowns for memory id, experiment id, backtest id, BitPro
  result id, and tool trace where data exists.
- Preserve Chinese-first professional operator style.

Do not:
- Build a marketing page.
- Reintroduce login wall for observability views.
- Add live execution UI expansion.
- Hide source ids behind decorative UI.

Implementation guidance:
- Use existing frontend patterns and lucide icons.
- Keep layouts dense, scannable, and responsive.
- Verify text does not overlap on mobile/desktop.
- Cards are for repeated items only; avoid nested cards.

Verification:
- npm exec --yes pnpm@10 -- -C frontend lint
- npm exec --yes pnpm@10 -- -C frontend test
- npm exec --yes pnpm@10 -- -C frontend build
- ./scripts/check.sh

Manual QA:
- Open /harness, inspect Strategy Library, resize desktop/mobile, and confirm
  source ids are visible.

Final handoff:
- Report UI sections added, API endpoints consumed, screenshots/browser checks,
  tests run, and any APIs stubbed because dependent sprints are not landed.
```

## Agent 53 Prompt: Agent Evaluation Suite

```text
You are Agent 53 for HyperTrade.

Goal:
Implement Sprint 53: Agent Evaluation Suite.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-53-agent-evaluation-suite.md
- docs/testing/agent-acceptance-test-plan.md
- docs/testing/agent-eval-suite.md
- tests/test_agent_acceptance.py
- backend/src/hypertrade/evals/

Scope:
- Add deterministic eval cases for strategy-library prompts, BitPro
  page-parity prompts, missing artifact prompts, paper monitor prompts, and
  compact report rendering.
- Assert required tools, forbidden tools, required source ids, and forbidden
  unsupported claims.
- Expose new cases in /evals status.

Do not:
- Add paid eval service dependency.
- Test exact prose snapshots.
- Evaluate profitability.
- Require live external network.

Implementation guidance:
- Check behavior contracts, not model style.
- Add reusable helpers for fake tool outputs and memory evidence.
- Eval should fail if a source-required answer does not call the required tool.

Verification:
- uv run pytest tests/test_agent_acceptance.py -q
- uv run pytest tests/test_agent_eval_suite.py -q
- ./scripts/check.sh

Final handoff:
- Report cases added, guardrails covered, tests run, and how future Agents add
  evals for new tools.
```

## Agent 54 Prompt: Connector Framework

```text
You are Agent 54 for HyperTrade.

Goal:
Implement Sprint 54: Connector Framework.

Read first:
- AGENTS.md
- README.md
- docs/spec.md
- docs/progress.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/contracts/sprint-54-connector-framework.md
- docs/architecture/17-bitpro-tool-adapter.md
- backend/src/hypertrade/bitpro/
- backend/src/hypertrade/config.py
- backend/src/hypertrade/tools/registry.py

Scope:
- Define connector interface for capability discovery, health, auth metadata,
  safe read execution, tool descriptors, and scopes.
- Add connector registry/service.
- Represent current BitPro adapter through compatibility path.
- Add fixture connector for deterministic tests.
- Expose connector capabilities without secret plaintext.

Do not:
- Rewrite the entire BitPro adapter in one pass.
- Add live execution systems.
- Load untrusted plugin code dynamically.
- Expose tokens or secret values.

Implementation guidance:
- Keep connector execution inside trusted server code.
- Capability output should include connector id, display name, health, auth
  status, supported scopes, tools, idempotency, and source-of-truth notes.
- Tool metadata can include connector origin, but AgentKernel still enforces
  policy and trace.

Verification:
- uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_tool_registry.py -q
- uv run pytest tests/test_agent_acceptance.py -q
- ./scripts/check.sh

Final handoff:
- Report connector interface shape, BitPro compatibility behavior, fixture
  tests, secret-safety checks, and future connector instructions.
```

## Coordination Prompt For A Lead Agent

Use this prompt for a coordination-only Agent that tracks parallel work without
editing feature code:

```text
You are the HyperTrade roadmap coordinator.

Goal:
Track parallel Sprint 45-54 implementation progress and prevent merge conflicts
or boundary drift.

Read first:
- AGENTS.md
- docs/architecture/18-hypertrade-capability-roadmap.md
- docs/progress.md
- docs/contracts/sprint-45-agent-runtime-reliability.md
- docs/contracts/sprint-46-strategy-evidence-schema.md
- docs/contracts/sprint-47-evidence-driven-strategy-loop.md
- docs/contracts/sprint-48-multi-source-market-intelligence.md
- docs/contracts/sprint-49-risk-governance-policy.md
- docs/contracts/sprint-50-report-provenance-system.md
- docs/contracts/sprint-51-monitoring-alerts.md
- docs/contracts/sprint-52-frontend-operator-console.md
- docs/contracts/sprint-53-agent-evaluation-suite.md
- docs/contracts/sprint-54-connector-framework.md

Scope:
- Maintain a status table of which sprint owns which files/interfaces.
- Identify dependency conflicts and propose sequencing.
- Review PRs or commits for boundary violations.
- Do not implement feature code unless explicitly reassigned.

Checks:
- No sprint should copy BitPro business logic.
- No sprint should bypass tool policy/risk gates.
- Reports must remain source-backed.
- Missing data must be explicit.
- Live write behavior must stay blocked or approval-gated.

Final handoff:
- Provide a concise status board: sprint, owner/thread, branch/commit, tests,
  deployment, blockers, next integration step.
```

