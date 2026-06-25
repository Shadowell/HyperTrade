# Sprint 72 - World Model Scenario Decision

## Goal

Add a scenario decision layer on top of the read-only `WorldState`. The Agent
should compare bounded candidate actions by estimated consequence, downside,
confidence, policy status, and required human confirmation before making any
operator recommendation.

## In Scope

- Add `ScenarioSimulator` that accepts `WorldState` and candidate actions.
- Add `ActionScorer` with deterministic scoring fields:
  - expected benefit
  - downside risk
  - confidence
  - data-gap penalty
  - reversibility
  - execution complexity
  - policy result
  - human-confirmation requirement
- Add structured `ActionScenario` and `DecisionRecord` schema.
- Compare at least these actions:
  - `observe_more`
  - `hold`
  - `run_monitor`
  - `inspect_trace`
  - `request_human_confirmation`
  - `pause_strategy_request`
  - `reduce_risk_request`
- Persist decision records if a snapshot recommendation is rendered to an
  operator.
- Include `review_after` and expected follow-up evidence for every chosen
  recommendation.
- Extend report blocks and CLI/API output to show scenario comparisons.
- Add evals that fail if a recommendation omits scenario evidence or policy
  status.

## Out of Scope

- Executing candidate actions automatically.
- Calling paper, BitPro, Testnet, or live write tools from scenario simulation.
- Using LLM-generated hidden reasoning as a source of score values.
- Training a learned transition model.
- Portfolio-level allocation changes.

## Deliverables

- `world_model/scenarios.py` for consequence templates and state transitions.
- `world_model/scoring.py` for deterministic scoring.
- Optional `world_model/records.py` or database persistence for decision
  records.
- API and Agent payload fields for `action_scenarios` and `decision`.
- Tests proving scenario scoring is deterministic and source-bound.
- Documentation update explaining score semantics.

## Done Means

- `world_model_snapshot` returns scenario comparisons for all configured
  candidate actions.
- Each scenario includes:
  - action id and action level
  - expected benefit
  - downside
  - affected state domains
  - confidence
  - risk/policy status
  - human-confirmation flag
  - review window
- If critical data is missing, the highest-ranked action is not an
  risk-increasing action.
- Reports can explain why the selected recommendation outranks alternatives.
- Decision records can be reviewed later with the original `WorldState` id or
  payload hash.

## Verification

```bash
uv run pytest tests/test_world_model_scenarios.py tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Ask the Agent `现在应该继续持有还是降低风险` and confirm it compares actions
  instead of giving one unscored answer.
- Confirm a missing-data-heavy snapshot prefers `observe_more` or
  `request_human_confirmation`.
- Confirm no write tools appear in trace for scenario evaluation.

## Risks / Notes

- Scoring must remain interpretable. A weighted score is acceptable only if each
  component is still visible.
- The first simulator can be rule-based. Later phases may replace parts with
  statistics or learned transition models after review data exists.

## Handoff

- Next likely step: Sprint 73 allows selected defensive automation only after
  scenario records and review evidence are stable.
