# Sprint 101 Agent Research Evaluation QA

## Verdict

PASS WITH QUALITY GAP. Required deterministic safety/recovery contracts, isolated
runtime, Promptfoo attacks, two provider baselines, privacy boundary, deployment and
repeatability passed. The real baseline also proves that the generic chat Agent does
not yet execute the Research OS graph with professional research quality.

## Scope Checked

- Task/Node/cursor state machines, replay, budgets and fault injection.
- Evidence, experiment fingerprint, validation and dangerous-tool contracts.
- Promptfoo injection safety, Ragas trajectory scoring and safe comparison.
- Langfuse metadata-only spans and exporter failure isolation.
- Production/isolated Docker boundaries and artifact privacy.

## Verification Evidence

- Final `./scripts/check.sh`: frontend lint, 8 frontend tests and build; Ruff;
  strict mypy over 131 source files; 426 Python tests.
- Production `/api/evals/status`: passed 38/38, including
  `research_os_golden_v1` 24/24 with exact category counts.
- Promptfoo `0.121.19`: 6/6 attacks passed; `evaluation_mode=evaluation`, zero
  tool calls and zero write dispatches.
- Corrected isolated Ragas run: two complete 24-case baselines. Both reported tool
  accuracy 0.0833, node sequence accuracy 0 and task-status match 0.5833; F1 moved
  from 0.0208 to 0.0278. Comparison reported `stable_or_improved`, zero regression
  and one improvement.
- Both runs observed one unsafe-tool attempt, denied it before dispatch, and recorded
  `unsafe_dispatches=[]`.
- Recursive scan of all final trajectory, baseline and comparison JSON found no
  prompt, report, argument, input/output, credential or private-reasoning key.
- Deploy workflows `29356068416`, `29356648230`, `29357192814` and `29357931595`
  succeeded; isolated API and version-matched evaluation runner passed health.

## Incidents Found And Fixed

- Promptfoo initially marked safe outputs failed because its Python assertion adapter
  omitted required `score` and `reason`; the adapter now returns the pinned grading
  contract and regression tests cover it.
- The first baseline script assumed `uv` existed on the production host. A separate
  `agent-eval` Docker target now owns all optional dependencies and scripts.
- Privacy review found allowlisted `args` in trajectory artifacts despite a declared
  no-argument boundary. Arguments were removed entirely and the final artifacts were
  regenerated in a fresh directory.
- The first comparison ignored F1, citation and task-status changes and could falsely
  report stability. Those dimensions are now compared; diagnostic regressions do not
  automatically become a paper/live gate.

## Quality Gap

The authored Research OS reference expects durable Research Task nodes, but the
provider collector currently enters through generic `/api/agent/runs`. Consequently,
the provider can be policy-safe while producing no Research Graph node sequence and
poor expected-tool alignment. Sprint 102 may visualize this honestly, but must not
claim the TUI fixes it; a later research-native evaluation entrypoint should run actual
Task/Graph cases rather than generic chat prompts.

## Boundaries

- No evaluation score, including PASS, authorizes paper/live or capital allocation.
- No profitability metric contributes to the Agent quality score.
- BitPro, production DB/data and production write paths remain disconnected from the
  isolated evaluation project.

## Next

Activate Sprint 102 TUI Research Workbench while preserving the measured quality gap.
