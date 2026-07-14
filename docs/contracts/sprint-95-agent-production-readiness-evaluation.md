# Sprint 95 - Agent Production-Readiness Evaluation

## Goal

Produce a reproducible, evidence-backed assessment of HyperTrade's Agent
quality and production readiness, including a bounded comparison with public
professional trading-Agent systems.

## In scope

- Attempt two provider-backed copies of the committed 24-case golden baseline
  only through the loopback tunnel to the isolated `hypertrade-eval`
  deployment; if a run cannot complete, preserve its failure category and
  coverage boundary rather than substituting a synthetic success.
- Run the committed Promptfoo adversarial checks against that same isolated
  target and retain only prompt-free aggregate results.
- Verify the deterministic `/api/evals` regression gate remains available.
- Assess architecture, tool coverage, safety controls, operational isolation,
  observability, and evaluation maturity against the repository's documented
  design and runtime evidence.
- Compare HyperTrade with public, primary-source evidence from representative
  professional/open trading-Agent and production-quant systems. State clearly
  where no shared or independently audited benchmark exists.
- Publish one durable Chinese evaluation and QA report under `docs/qa/`, then
  update the project specification and progress record with the reviewed
  conclusion.

## Out of scope

- Connecting the evaluation target to production services, production data,
  BitPro, exchange credentials, Feishu, Nginx, or a worker.
- Changing trading strategy logic, enabling live trading, or claiming
  investment performance.
- Treating vendor marketing claims or incomparable backtests as an audited
  head-to-head performance result.
- Setting CI score thresholds before repeatability, task coverage, and failure
  taxonomy have been reviewed.

## Done means

- Baseline and adversarial attempts, including any incomplete run, are recorded
  with their target, failure category, coverage boundary, and safe aggregate
  evidence. If two full same-model reports complete, compare them; otherwise
  identify repeatability as not achieved rather than inventing a threshold.
- The final report gives an explicit architecture verdict, tool/function
  coverage verdict, production-readiness level, key gaps ranked by priority,
  and a concrete path to a professional production-grade standard.
- Comparisons cite primary public sources and distinguish capabilities from
  comparable measured results.
- `docs/qa/` contains a pass/fail/not-checked QA assessment; `docs/spec.md`
  and `docs/progress.md` reflect the final evaluated state.

## Verification

- `HYPERTRADE_EVAL_TARGET=isolated` is explicit for every provider-backed run;
  the target is a local SSH forward to `127.0.0.1:4334` on the isolated host
  deployment.
- Two `./scripts/run_agent_eval_baseline.sh` attempts either complete and are
  compared, or their first non-completing case and error category are recorded.
- `./scripts/run_promptfoo_isolated.sh` either passes both committed adversarial
  cases or is explicitly marked not run/failed with the observed cause.
- `curl -fsS /api/evals` reports the deterministic gate summary.
- `./scripts/check.sh` passes before committing the documentation changes.
- The required push to `origin/main` succeeds; its deployment workflow and the
  production health endpoint are verified after publication.

## Handoff

- This sprint reports diagnostic readiness, not trade profitability or a live
  trading authorization. Keep the isolated deployment and artifact-retention
  boundary intact for future regressions.
- Before assigning a CI threshold, add a larger versioned holdout set, repeat
  across at least three runs and relevant providers, and label every failure as
  planner, tool, data, policy, or infrastructure.
