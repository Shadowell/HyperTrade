# Sprint 102 TUI Research Workbench QA

## Verdict

PASS. Optional dependency isolation, REST/SSE client contracts, cursor recovery,
responsive Textual UI, reason-required controls, CLI compatibility, Docker deployment
and a real production terminal smoke passed.

## Scope Checked

- Session/Task index, graph/timeline, Evidence, experiments, validations and approvals.
- Multiline task creation and pause/resume/retry/cancel confirmation boundaries.
- SSE cursor replay, duplicate suppression, gap detection, reconnect and final snapshot.
- 160/120/80-column layouts and keyboard-only operation.
- Base CLI/API/Worker dependency isolation and host wrapper routing.

## Evidence

- Focused TUI/CLI/API/deploy suite: 91 passed.
- Final `./scripts/check.sh`: frontend lint, 8 frontend tests and build; Ruff; strict
  mypy over 134 source files; 435 Python tests.
- Deployment workflow `29359569036` succeeded for commit `c288254`.
- Production API health returned OK and deployed SHA matched `c288254`.
- `hypertrade-tui:latest` imported Textual 8.2.8; `hypertrade-api` reported no
  installed Textual module.
- Real SSH TTY rendered the 80-column compact workbench with four production tasks,
  a completed 13-node Research Graph task, checkpoint, Token capacity and tabs; `q`
  restored the alternate screen and closed the SSH session normally.

## Incidents Found And Fixed

- Textual reserves `Ctrl+P` for its command palette. HyperTrade task controls now use
  priority bindings, and a headless regression proves the reason modal opens instead.
- The production API image intentionally omits optional Textual, so the existing host
  wrapper could not launch a TUI. A separate Docker `tui` target and Compose `cli`
  profile now provide a short-lived client without bloating API/Worker.
- The store treats an SSE connection ending as a reconciliation point even for
  terminal tasks; nonterminal tasks reconnect from the high-water cursor.

## Boundaries

- TUI has no database, ToolRegistry, BitPro or trading-service access.
- TUI does not decide legal transitions or generate idempotency outcomes.
- Approval data is read-only in this Sprint; no single-key paper/live action exists.
- TUI visibility does not resolve Sprint 101's measured Research Graph quality gap.

## Next

Activate Sprint 103 Background Research Triggers using the same Task/Event/TUI contracts.
