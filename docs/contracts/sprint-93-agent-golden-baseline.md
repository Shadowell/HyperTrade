# Sprint 93 - Agent Golden Baseline

## Goal

Turn the isolated evaluation foundation into a repeatable first baseline with
a versioned, privacy-safe golden task set and one consolidated diagnostic report.

## In scope

- Add a 24-case committed golden set covering market, knowledge, Memory,
  strategy, BitPro diagnostics, World Model, and write-attempt safety tasks.
- Preserve only authored representative tasks; do not copy production prompts,
  account data, or historical trace content into the repository.
- Extend sanitized trajectories with citation count, duration, token count, and
  policy scope, without exporting raw report, citation text, tool arguments, or
  tool outputs.
- Generate a baseline report with Ragas tool selection/F1, citation coverage,
  write-attempt denial rate, latency, token totals, and explicitly unavailable
  cost when the provider does not report normalized cost.
- Provide one isolated-target runner that collects the full set and writes its
  generated artifacts outside the repository by default.

## Out of scope

- Adding an LLM score or Ragas threshold to CI or deployment gates.
- Operating an isolated provider deployment, sourcing provider credentials, or
  executing the new suite against production.
- Storing real user prompts, Agent reports, RAG text, account data, secrets, or
  raw tool payloads in golden data or baseline outputs.
- Estimating dollar cost from an unreviewed price table.

## Done means

- The golden set has 24 labelled cases spanning all selected tool domains and
  six explicit evaluation-mode write-attempt cases.
- Collected trajectories and the baseline report remain prompt-free and expose
  only safe aggregate evidence.
- The baseline runner refuses a target not explicitly labelled `isolated`.
- Tests cover aggregate accuracy, citation, safety, and privacy boundaries.

## Verification

- `uv run pytest tests/test_agent_evaluation_baseline.py tests/test_agent_evaluation_foundation.py -q`
- `uv run ruff check backend/src/hypertrade/evals tests/test_agent_evaluation_baseline.py`
- `./scripts/check.sh`
- In a separately provisioned isolated target: `uv sync --extra agent-evals`
  followed by `./scripts/run_agent_eval_baseline.sh`.

## Handoff

- Treat a baseline as trend evidence. Set CI thresholds only after at least two
  reviewed isolated runs on the same golden-set version and provider/model.
- Add or retire golden cases through review; preserve case ids where possible so
  historical baselines remain comparable.
