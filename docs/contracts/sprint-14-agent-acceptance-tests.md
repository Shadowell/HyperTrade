# Sprint 14 Contract: Agent Acceptance Tests

## Goal

Add automated acceptance tests and a reusable test document for HyperTrade Agent behavior. The tests should check whether tool selection, trace output, RAG, Memory, strategy research, backtesting, and report quality are reasonable without depending on real LLM or OKX network calls.

## Scope

- Add pytest cases that replay deterministic LLM tool-call responses.
- Cover specific-symbol行情, K-line trend, relative-strength compare, RAG + Memory, and strategy research + backtest.
- Assert output quality with structural checks instead of brittle full-text snapshots.
- Add a Markdown test guide that explains automated and server smoke cases.

## Out Of Scope

- Real-money trading tests.
- Live OKX network tests in CI.
- LLM answer grading with another model.
- BitPro historical K-line import.

## Acceptance

- New acceptance tests pass locally.
- Full `./scripts/check.sh` passes.
- `docs/testing/agent-acceptance-test-plan.md` documents test cases, commands, expected outputs, and risk phrases to avoid.
- `docs/progress.md` records verification evidence and the next step.
