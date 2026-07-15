# CLI Operator Console Professionalization Audit

Date: 2026-07-16
Verdict: **Needs redesign before it can be called a professional trading-Agent CLI.**

## Scope and evidence

This is a read-only UX and reliability audit of the terminal surface, not a
claim about the wider Agent runtime or trading strategy quality.

- `./scripts/check.sh` completed successfully on the audited working tree.
- `backend/src/hypertrade/cli.py` contains 7,243 lines; `tests/test_cli.py`
  contains 3,223 lines and 80 CLI-focused tests.
- `/help` exposes 64 entries across 38 root slash commands.
- The CLI architecture explicitly describes the surface as a developer
  harness, while Sprint 116 requires one recoverable Mission projection across
  REST, SSE, CLI, and Web.

## What is already strong

- Provider, tool policy, approval, audit trace, Memory, strategy evidence, and
  Testnet gates exist behind the terminal surface.
- Agent runs and tasks are persisted; task event endpoints support a cursor and
  `Last-Event-ID` replay.
- The terminal has useful building blocks: Rich/plain output, command
  completion, compact or full trace modes, and a persisted `/run <id>` view.
- Mainnet remains blocked and write-capable execution has approval gates.

## Findings

| Priority | Finding | Why it is not professional-grade | Required direction |
|---|---|---|---|
| P0 | The advertised stream is progress-only (`run_started`, tool events, `final`), not a public answer stream. | Operators see generic “running/completed” status while the substantive conclusion arrives only as one final batch; it feels silent and offers no useful interruption point. | Add a public, resumable event contract: `answer_delta`, `evidence_ready`, `action_required`, `warning`, and `final`. Do not stream private chain-of-thought. |
| P0 | Default chat uses an ephemeral `POST /api/agent/runs/stream` queue, while durable task replay is a separate path. | A disconnect can leave an operator with a run id but no automatic reattach or delivery guarantee. | Start/return one Mission or task id first, then attach the CLI to its durable cursor stream and resume automatically. |
| P0 | Remote `/model` changes process-wide `app.state.active_chat_provider` and model. | One CLI operator can affect subsequent runs for other operators; it is not a session preference. | Make provider selection immutable per Mission/session, or restrict server-default changes to an audited administrator operation outside normal chat. |
| P1 | Rendering selects among Markdown, structured tool outputs, paper summaries, WorldState, and Rich paths through scattered precedence rules. | The MUUSDT `found=false` report was silently hidden because an empty structured renderer won over the final answer. | Define one `OperatorResponseV1` projection with summary, evidence, warnings, actions, and artifacts; every renderer must render that same projection. |
| P1 | Final-answer quality has no product-level acceptance gate. | A syntactically successful model response can still be vague, lack a decision, omit freshness/provenance, or provide no next safe action. | Validate every operator answer against a task-specific response contract before it is rendered; recover with a deterministic evidence summary when the model answer is incomplete. |
| P1 | 64 commands are exposed in a flat help catalog. | Operators must know internal domains and lifecycle nouns before they can work; safe and dangerous controls are adjacent. | Organize around five workflows: Market, Research, Portfolio, Execution Review, and Operations. Keep expert/debug commands behind `/ops` or a command palette. |
| P1 | The prompt is chat-first, not task-first. | It does not make run ownership, recovery, budget, freshness, required approval, or next safe action visible. | Make the primary interaction `new task → durable run → answer/evidence → next action`, with a compact persistent status line. |
| P1 | Failure behavior is piecemeal. | History-path failures and no-data rendering both reached users before regression coverage; errors lack a standard recovery contract. | Every failure must show a stable error class, run/task id, whether work continues remotely, and one precise recovery action. |
| P2 | Current tests are mostly unit-level render/parser coverage. | They do not prove a real terminal transcript survives reconnects, ANSI redraws, deployment interruption, provider timeout, or `found=false` evidence. | Add PTY golden-transcript and remote fault-injection suites with recovery assertions. |

## Recommended delivery sequence

1. **P0 — public answer streaming and durable delivery.** Route default CLI
   chat through the Sprint 116 Mission Runtime. Return the Mission id before
   streaming; emit public answer deltas and evidence-ready events from the
   durable cursor stream; reattach after network loss or deployment. Private
   reasoning never enters the event stream.
2. **P0 — provider isolation.** Remove provider switching from normal chat.
   Bind provider/model to the created Mission and record the choice in its
   immutable context. A server-default change requires an operator-only,
   audited control path.
3. **P1 — one answer contract and quality gate.** Introduce `OperatorResponseV1`: `summary`,
   `market_freshness`, `evidence`, `risk_state`, `recommended_actions`,
   `artifact_refs`, and `recovery`. Validate the contract before delivery;
   Rich, plain, and Web renderers consume this projection rather than choosing
   independently among raw tool payloads.
4. **P1 — workflow information architecture.** Make the home surface offer
   Market Diagnosis, Strategy Research, Portfolio Review, Execution Review,
   and Operations. Keep natural language as the main entry; make command
   palette and expert commands secondary.
5. **P2 — terminal acceptance gate.** Add PTY-based transcripts for first
   launch, no-data result, streaming reconnect, provider timeout, paused task,
   pending approval, and deployment interruption. A blank final answer is a
   release-blocking failure.

## Exit criteria for a professional CLI

- Every submitted task has a durable id shown immediately and can be reopened
  or resumed without resubmission.
- Every task begins streaming public answer/evidence progress promptly and
  renders exactly one complete operator answer, with a safe evidence drill-down
  and an explicit next action.
- Provider, permission, risk, freshness, budget, and approval state are bound
  to the task and visible without enabling global side effects.
- Normal users need at most five workflow entry points; expert operations are
  discoverable but isolated.
- PTY and remote fault-injection acceptance tests prove no blank answers, no
  duplicate dispatch, and no unsafe execution escalation.

## Next action

Treat the Sprint 116 Mission Runtime cutover as the prerequisite, then execute
the P0 CLI delivery and provider-isolation slice before investing in additional
visual polish or more slash commands.
