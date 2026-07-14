# Sprint 92 - Agent Evaluation Foundation

## Goal

Add a production-safe evaluation foundation around the existing deterministic
Agent eval suite: optional self-hosted Langfuse trace export, isolated
Promptfoo adversarial regression checks, and Ragas tool-trajectory scoring.

## In scope

- Keep the existing deterministic `/evals` suite as the required CI regression
  gate; it remains independent of external LLM evaluators.
- Add an explicit Agent evaluation mode that permits only `read` and
  `live_diagnostic_read` tool scopes.
- Export metadata-only run spans to an opt-in Langfuse instance without prompts,
  credentials, private reasoning, report text, or raw tool payloads.
- Provide repeatable Promptfoo adversarial checks that require an explicitly
  marked isolated target and disable Promptfoo remote generation and telemetry.
- Provide a Ragas runner and a small golden tool-trajectory reference set for
  offline scoring after trajectories are collected from the isolated target.

## Out of scope

- Deploying or operating the Langfuse infrastructure itself.
- Enabling Langfuse, Promptfoo, or Ragas in production by default.
- Sending production prompts, trading data, secrets, or report content to any
  third-party service.
- Adding a public production red-team endpoint, automatic live trading, paper
  lifecycle actions, or changes to existing governance policies.
- Replacing the deterministic eval suite with an LLM judge.

## Done means

- `evaluation_mode=true` is auditable and blocks all write-like Agent tools
  before their dispatch functions run.
- Langfuse export is disabled by default, optional at install time, and cannot
  affect the outcome of an Agent run.
- Promptfoo requires `HYPERTRADE_EVAL_TARGET=isolated`, runs static adversarial
  cases, and has remote generation, telemetry, updates, and sharing disabled
  by its runner.
- Ragas consumes only locally produced sanitized trajectories and reports tool
  accuracy and tool-call F1 against committed references.
- Focused tests and `./scripts/check.sh` pass.

## Verification

- `uv run pytest tests/test_agent_evaluation_foundation.py -q`
- `uv run pytest tests/test_agent_eval_suite.py tests/test_agent_observability.py -q`
- `./scripts/check.sh`
- `uv sync --extra agent-evals` followed by the documented isolated-target
  Promptfoo and Ragas commands when the optional dependencies are provisioned.

## Handoff

- Keep Langfuse metadata-only unless a reviewed data-retention decision changes
  the boundary. Do not add prompt, completion, tool-argument, or credential
  fields to its exporter.
- Run Promptfoo only against a throwaway database/isolated target. The runner
  is intentionally not a production smoke-test command.
