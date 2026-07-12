# Sprint 84 - Regime-Aware Strategy Portfolio Review

## Goal

Extend the existing read-only WorldState portfolio view with strategy lifecycle evidence from Sprints 81–83. The result is an operator-facing review of which research candidates are suited to the observed market state, which need more evidence, and where concentration or drift requires human review.

## In Scope

- Add a `StrategyCard` read model that joins mandate scope, validation evidence, BitPro paper observation, and lifecycle status without copying BitPro source data.
- Define explicit strategy-state metadata: strategy category, allowed symbols/timeframes, declared regime fit, evidence freshness, paper status, drawdown/coverage flags, and retirement reason.
- Extend the WorldState portfolio service to compare StrategyCards with existing market-state, strategy-evidence, paper-monitor, and connector-health inputs.
- Return deterministic, source-bound review actions: `observe`, `run_targeted_research`, `request_paper_review`, `request_pause_review`, and `retire_candidate_review`.
- Include concentration and shared-exposure warnings using transparent, bounded proxies; return `unknown` rather than inferred correlation when inputs are unavailable.
- Add API/CLI/Agent report blocks that distinguish research, backtest, paper, and live diagnostic state.
- Add deterministic evals requiring portfolio answers to cite StrategyCard and WorldState evidence, and forbidding live/paper write calls.

## Out of Scope

- Automatic paper pause/stop, automatic risk-budget changes, or any allocation mutation.
- A full mean-variance optimizer, machine-learned regime predictor, or profitability forecast.
- New market-data providers or live trading capabilities.
- Replacing the existing WorldState or BitPro paper monitor services.

## Deliverables

- StrategyCard read model/service and report schema.
- WorldState portfolio-review extension with explicit missing-data behavior.
- API/CLI/Agent tool/report integration.
- Focused lifecycle/world-model/report/eval tests.
- Architecture and operator documentation for strategy-state interpretation.

## Done Means

- Portfolio review names the evidence source and lifecycle state for every included strategy card.
- A paper-observing strategy with stale evidence or monitor alerts produces a review request, not an allocation-increase recommendation.
- A candidate without a passed validation report or approved paper promotion cannot be presented as a qualified paper strategy.
- Missing correlation or regime inputs render an explicit unknown/data-gap state.
- No paper or live write tool is called during a portfolio review.

## Verification

```bash
uv run pytest tests/test_strategy_cards.py tests/test_world_model_portfolio.py -q
uv run pytest tests/test_agent_eval_suite.py tests/test_agent_acceptance.py -q
uv run pytest tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- Review a mix of rejected, pending-approval, paper-observing, and stale strategies; confirm each has the correct lifecycle label and recommended action.
- Remove one paper metric or WorldState source and confirm the report surfaces a data gap instead of inventing an allocation conclusion.
- Confirm the Trace contains only read tools for a portfolio-review prompt.

## Risks / Notes

- Regime fit and correlation begin as declared or transparent proxy fields. They must not be presented as precise portfolio optimization without sufficient data.
- This sprint supplies review evidence for an operator; it does not authorize risk-increasing automation.

## Handoff

Later work may add operator-configured defensive actions only after enough paper observation history exists and under a new explicit approval/risk contract. Live trading remains outside this roadmap.
