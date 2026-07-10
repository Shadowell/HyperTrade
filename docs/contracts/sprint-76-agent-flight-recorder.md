# Sprint 76 - Agent Flight Recorder

## Goal

Make one HyperTrade Agent run operationally explainable from a single API and
UI surface. Operators must be able to see the graph path, provider/model calls,
tool execution, Memory reads and writes, latency, and provider-reported token
usage without exposing secrets or private model reasoning.

## In Scope

- Normalize provider-reported input, output, cached-input, reasoning, and total
  token counts across OpenAI-compatible Chat Completions and Codex Responses.
- Record each planner model call as a trace-safe graph event with iteration,
  provider, model, latency, tool-call count, and token usage.
- Aggregate run-level observability into `run_state_json`, including total
  duration, model request count, token totals, tool latency, and Memory activity.
- Add a run observability projection API that returns one ordered timeline with
  graph, model, tool, Memory, policy, and evidence categories.
- Add overview-level recent run telemetry for the operator console.
- Review the five existing optimization proposals and record their corrected
  dependency order, production caveats, and implementation status in the
  optimization documentation index.
- Add a componentized frontend Agent Flight Recorder with:
  - run status, provider/model, elapsed time, and token summary;
  - Graph / Model / Tool / Memory timeline lanes;
  - provider token composition and per-call latency;
  - Memory hit/write identifiers and trace evidence drilldown;
  - responsive and keyboard-accessible behavior.
- Preserve existing API, CLI, SSE, report, governance, and Memory behavior.

## Out of Scope

- Persisting or displaying private chain-of-thought or raw reasoning content.
- Model pricing tables or inferred cost when a provider does not report cost.
- A production OpenTelemetry collector, Prometheus deployment, or external APM.
- Full async conversion of SQLAlchemy, provider, market, or BitPro paths.
- Tool handler strategy refactor.
- Database foreign-key/index migration.
- New autonomous live-trading permissions or automatic portfolio mutations.
- Multi-Agent analyst/debate roles; those require a separate evidence and eval
  contract after the single-Agent runtime is observable.

## Done Means

- Provider responses with usage metadata produce exact normalized token totals;
  missing usage remains explicitly unavailable/zero and is not estimated.
- Every provider-backed run records one model event per planner iteration and a
  run-level usage summary.
- `GET /api/agent/runs/{run_id}/observability` returns an ordered, redacted
  timeline plus model, tool, Memory, and token summaries.
- `/api/harness/overview` exposes aggregate recent-run observability without
  leaking prompts, tool secrets, credentials, or reasoning text.
- `/harness` displays a professional Flight Recorder for a new or loaded run,
  including Token usage and Memory trace information.
- Existing CLI/API consumers continue to work with additive fields only.
- Focused tests and `./scripts/check.sh` pass.

## Verification

```bash
uv run pytest tests/test_agent_observability.py tests/test_codex_provider.py \
  tests/test_provider_runtime.py tests/test_api.py -q
npm exec --yes pnpm@10 -- -C frontend test
npm exec --yes pnpm@10 -- -C frontend build
./scripts/check.sh
```

Manual browser checks:

- Start one Agent run and confirm Model, Tool, and Memory events appear in order.
- Open a historical run and confirm its Token totals and Memory links reload.
- Confirm missing provider usage renders as unavailable rather than a fabricated
  estimate.
- Check desktop and narrow viewport layouts and visible keyboard focus.

## Handoff

- Follow with structured logging/OpenTelemetry once the event vocabulary is
  stable, then expose the same fields to the collector.
- Refactor the tool dispatch table behind registered handlers without changing
  the Flight Recorder event contract.
- Split remaining large frontend domains into feature components.
- Convert blocking provider/market/BitPro boundaries to async under a dedicated
  concurrency and cancellation contract.
- Add reviewed foreign keys and query indexes in an isolated migration sprint.
- Add specialist financial analyst/risk/portfolio Agents only after each role
  has a source contract, permission budget, evaluation set, and visible trace.
