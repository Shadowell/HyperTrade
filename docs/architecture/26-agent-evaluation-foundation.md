# 26 Agent Evaluation Foundation / Agent 评测基础设施

## Purpose

HyperTrade keeps deterministic checks as its release gate and adds optional
frameworks for three different questions:

| Layer | Tooling | Answers | Default |
| --- | --- | --- | --- |
| Regression gate | `AgentEvalSuite`, pytest, `/evals` | Did a known safety/source/report contract regress? | Required in CI |
| Trace observability | Self-hosted Langfuse | Which provider/model/tool path ran, at what latency and token cost? | Disabled |
| Adversarial safety | Promptfoo | Does a hostile prompt reach a write-like tool dispatch? | Isolated target only |
| Offline trajectory score | Ragas | Did a run choose the expected tools in the expected order? | Manual, isolated artifacts only |

These layers complement one another. They do not replace governance, tool
policies, approval gates, or human review.

## Evaluation Mode Boundary

`POST /api/agent/runs` and its streaming variant accept
`evaluation_mode=true`. The value is recorded in `run_state_json.execution_mode`
and the report metadata. At the trusted `AgentKernel` boundary, evaluation mode
allows only tool policies with `scope=read` or `scope=live_diagnostic_read`.

All other attempted tools are recorded as `execution_status=denied` before their
tool dispatch function executes. This makes adversarial selection observable
without allowing the evaluator to create Memory, research, BitPro, paper,
Testnet, or live artifacts.

Evaluation mode is an additional safeguard, not permission to point a test at
production. Isolated runs still persist their prompt and trace in their target
database, so Promptfoo/Ragas targets must use a throwaway deployment and
database.

## Server Evaluation Target

The canonical server target is the `hypertrade-eval` Compose project under
`/opt/hypertrade-eval`. It exposes only `127.0.0.1:4334`, uses a dedicated
PostgreSQL volume and environment file, and does not share production
containers, network, database, BitPro mount, Nginx route, or worker process.
Its default deployment disables paper trading and monitor scheduling, leaves
the worker profile stopped, and points BitPro at an unreachable container
loopback endpoint. This is logical isolation on the production host; use a
separate VM/server when the evaluation boundary requires physical isolation.

Run evaluation commands from a trusted operator session with:

```bash
export HYPERTRADE_EVAL_TARGET=isolated
export HYPERTRADE_EVAL_BASE_URL=http://127.0.0.1:4334
./scripts/run_agent_eval_baseline.sh
```

The baseline launcher is a Docker orchestrator, not a Python environment
bootstrapper. Run `deploy/deploy-eval.sh` first so the version-matched
`hypertrade-agent-eval:latest` image exists. That image is built from the
`agent-eval` target with the locked `agent-evals` extra; the production image
does not carry those optional packages.

The server-side environment may mount a Codex authentication file only as a
read-only Compose secret. Do not copy OAuth contents into `.env`, trajectory
artifacts, or the repository; prefer a dedicated expiring Codex access token
before widening evaluation automation.

## Langfuse

Langfuse is an opt-in, optional dependency installed with:

```bash
uv sync --extra agent-evals
```

For a reviewed self-hosted Langfuse project, set server-side values in
`/opt/hypertrade/.env`:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://langfuse.internal
```

The exporter creates one root run span and one child span per persisted trace
event. It sends only run id, status, execution mode, provider/model, duration,
token counts, tool/graph event name, status, policy scope/outcome, source class,
and event duration. It never sends prompts, completions, report text, private
reasoning, tool arguments, raw tool outputs, or credentials. Failures are
recorded as local export status and never fail an Agent run.

Langfuse self-hosting is deployed separately from HyperTrade. Do not add its
multi-service storage stack to the trading runtime Compose file without an
operations, retention, backup, and access-control review.

## Promptfoo

The committed Promptfoo suite uses six static adversarial prompts. It does not
call `promptfoo redteam run`, so it does not generate or grade prompts remotely.
The runner disables remote generation, telemetry, update checks, and sharing.

```bash
export HYPERTRADE_EVAL_TARGET=isolated
export HYPERTRADE_EVAL_BASE_URL=http://127.0.0.1:4334
./scripts/run_promptfoo_isolated.sh
```

The provider sends `evaluation_mode=true` and returns a compact policy-safe
projection to Promptfoo. It rejects runs unless
`HYPERTRADE_EVAL_TARGET=isolated` is explicit. Keep the target loopback or an
isolated network deployment; a non-loopback target also requires
`HYPERTRADE_EVAL_ALLOW_REMOTE=true`. Never set these variables for the
production API.

## Ragas

Ragas receives locally generated argument-free trajectory JSON, not Langfuse
data and not production traces. The Research OS reference scores tool, role/node
sequence and terminal task status. Tool arguments are never exported or scored.

```bash
export HYPERTRADE_EVAL_TARGET=isolated
export HYPERTRADE_EVAL_BASE_URL=http://127.0.0.1:4334
./scripts/run_agent_eval_baseline.sh
```

The collection script defaults to loopback and requires `--allow-remote` for a
non-loopback target. That acknowledgement and the explicit environment label do
not weaken the isolated-target requirement. Each provider case uses a configurable
`HYPERTRADE_EVAL_CASE_TIMEOUT_SECONDS` (default 300, clamped to 30–600) so the client
timeout remains outside the reviewed provider timeout without allowing an unbounded wait.

## Golden Baseline

`research_os_golden_v2.json` is the active versioned baseline set: 26 authored
tasks split into fixed `chat_answer`, `tool_required`, `research_graph` and `safety`
cohorts. V1 remains historical evidence and is not directly comparable because its
aggregate denominators mixed route and graph applicability. V2 keeps system-fault
expectations separate from provider terminal/node expectations. It is not a
production-prompt export. Six safety cases ask for write-like work so the trusted
evaluation boundary can prove denial evidence and zero dispatch.

Run the complete baseline only against a separately provisioned isolated Agent
API and its throwaway database:

```bash
export HYPERTRADE_EVAL_TARGET=isolated
export HYPERTRADE_EVAL_BASE_URL=http://127.0.0.1:4334
./scripts/run_agent_eval_baseline.sh
```

The runner writes two Research OS trajectories, two baselines, and one safe
comparison under `/tmp/hypertrade-agent-evals` by default; set
`HYPERTRADE_EVAL_OUTPUT_DIR` to retain a reviewed baseline elsewhere. The report
contains case ids, aggregate Ragas tool accuracy/F1, citation-count coverage,
unsafe-tool denial evidence, duration, and total tokens. It excludes prompts,
report text, citation text, tool arguments, raw outputs, and credentials.
Tool scoring uses only `tool_required`; graph sequence uses only `research_graph`;
source coverage, terminal status and safety each retain their authored denominator.
The comparison records accuracy/F1, citation, node and task-status changes. A final
quality gate requires both runs to preserve the same case count and pass all V2
thresholds; it exits non-zero on a missing/failed run.

The report never estimates dollar cost from a transient provider price table.
It marks cost as `not_reported` unless a future reviewed cost-normalization
contract adds an auditable provider-reported value. A baseline is diagnostic
evidence only: compare at least two reviewed isolated runs on the same
golden-set version and provider/model before proposing any CI threshold.

Sprint 106 production acceptance completed two fixed 26-case Codex runs. Both passed all
`agent_research_quality.v2` thresholds at 1.0 with zero unsafe dispatch. The second run was
slower and two Research Graph cases had lower legacy Ragas tool accuracy; these diagnostics
remain visible but do not change the fixed tool-required/source/safety denominators.

## Operating Rules

- Keep `/evals` deterministic and runnable without optional packages, keys, or
  network access.
- Keep `LANGFUSE_ENABLED=false` unless an operator has configured a self-hosted
  instance and approved its data-retention boundary.
- Never add raw prompt, completion, tool-argument, report, or credential fields
  to the Langfuse exporter or committed trajectories.
- Treat Promptfoo remote-generation flags as defense in depth, not network
  isolation; use egress controls for strict air-gapped testing.
- Review a Ragas score alongside the trajectory and the deterministic safety
  gate. A score is diagnostic evidence, not an authorization to trade.
- Keep generated baseline artifacts outside the repository unless a reviewed,
  prompt-free aggregate is intentionally retained for historical comparison.
