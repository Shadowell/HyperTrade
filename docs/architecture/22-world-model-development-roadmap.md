# 22 World Model Development Roadmap / 世界模型开发路线

## Purpose

This roadmap turns `docs/architecture/21-world-model-agent-action-plan.md`
into phased HyperTrade development work. The design follows a LeCun-style
world-model split, but maps it onto HyperTrade's existing production Agent
boundary: deterministic Python services own state, evidence, policy, and audit;
the LLM planner explains and compares choices but does not bypass tool policy,
risk gates, BitPro contracts, or operator approval.

The market layer is global. It should represent cross-asset conditions rather
than only OKX or crypto conditions. Crypto remains a target market for
HyperTrade, but the Agent's market sense should include risk assets, rates,
FX, volatility, commodities, and regional equity pressure when those sources
are available.

## Architecture Mapping

| LeCun-style module | HyperTrade module | Responsibility |
| --- | --- | --- |
| Perception | `world_model.collectors` | Read market, strategy, execution, system, deployment, and memory evidence. |
| Abstract state | `WorldState` schema | Compress raw observations into auditable state labels and metrics. |
| World model | `ScenarioSimulator` | Estimate candidate-action consequences from current state. |
| Actor | `CandidateActionService` | Produce bounded operator actions such as observe, run monitor, inspect trace, request pause, or reduce risk. |
| Cost / Critic | `ActionScorer` plus `RiskGovernancePolicy` | Score downside, confidence, reversibility, data gaps, permissions, and human-confirmation requirements. |
| Short-term memory | `WorldModelSnapshot` and trace | Store the state, action scenarios, chosen recommendation, and follow-up review window. |
| Long-term memory | audited `MemoryItem` review cards | Persist lessons only after actual outcomes are compared with predictions. |

## Global Market State

The world model should not treat market state as `BTC up/down`. It should first
estimate a global regime:

- `risk_regime`: `risk_on`, `risk_off`, `mixed`, `stress`, or `unknown`
- `liquidity_regime`: `loose`, `neutral`, `tight`, or `unknown`
- `volatility_regime`: `calm`, `elevated`, `stressed`, or `unknown`
- `dollar_pressure`: `weak`, `neutral`, `strong`, or `unknown`
- `rates_pressure`: `falling`, `neutral`, `rising`, or `unknown`
- `cross_asset_signal`: `supportive`, `conflicting`, `hostile`, or `unknown`

Phase 1 may use adapters and fixtures where live sources are not ready. Missing
global inputs must be visible in `missing_data`; the Agent must not replace
unavailable cross-asset evidence with model recall.

Recommended source groups:

- US equities: S&P 500, Nasdaq, Russell 2000
- Volatility: VIX or equivalent implied-volatility proxy
- Rates: US 2Y and 10Y yields
- FX: DXY or USD pressure proxy
- Commodities: gold and crude oil
- Asia risk assets: Hong Kong / China equity proxies where available
- Crypto: BTC, ETH, broad OKX SWAP breadth, funding, open interest, liquidity

## Phase Plan

### Phase 1: Read-Only Global WorldState

Contract: `docs/contracts/sprint-71-world-model-readonly-snapshot.md`

Deliver a read-only `world_model_snapshot` tool and API endpoint. The snapshot
aggregates global market, crypto market, strategy evidence, execution state,
tool health, deployment state, data gaps, and source references. It produces
candidate actions only as L0/L1 recommendations and does not execute any
paper, BitPro, Testnet, or live mutation.

### Phase 2: Scenario Decision Layer

Contract: `docs/contracts/sprint-72-world-model-scenario-decision.md`

Add scenario simulation and action scoring. The Agent compares possible futures
for actions such as observe, hold, run monitor, inspect trace, request pause,
or request risk reduction. Every recommendation includes expected benefit,
downside, confidence, required confirmation, policy result, and review window.

### Phase 3: Defensive Automation

Contract: `docs/contracts/sprint-73-world-model-defensive-automation.md`

Open a small set of low-risk defensive actions only after Phase 1 and Phase 2
produce auditable state and review records. Defensive actions require explicit
operator configuration, idempotency keys, policy checks, risk checks, and
failure reporting. Offensive actions remain blocked.

### Phase 4: Portfolio Strategy Scheduler

Contract: `docs/contracts/sprint-74-world-model-portfolio-scheduler.md`

Extend the world model from single-strategy decisions to portfolio-level
strategy allocation. The scheduler observes regime fit, strategy correlation,
evidence freshness, drift, drawdown, and operator-defined limits before
recommending or requesting allocation changes.

## Cross-Phase Contracts

### Evidence Contract

Every state field must identify:

- source type: tool, connector, monitor, memory, RAG, deployment, or fixture
- source id: tool name, monitor run id, memory id, API path, or document path
- `as_of`: when the evidence was read or produced
- freshness or age when available
- missing fields
- confidence in the state label, not in market outcome

### Permission Contract

World-model outputs use action levels:

- L0: read-only observation and report
- L1: recommendation requiring human review
- L2: configured defensive automation after policy/risk approval
- L3: offensive trading or risk-increasing actions

Phase 1 and Phase 2 allow only L0/L1. Phase 3 may allow selected L2 actions.
L3 remains out of scope for this roadmap.

### Review Contract

Any recommendation that claims a likely consequence must have a review window.
The later review compares the predicted state change with observed evidence and
stores a structured lesson only when source evidence exists.

## Verification Expectations

Each phase should add:

- focused unit tests for schema, collectors, state labels, and scoring
- Agent planner/eval cases requiring the world-model tool for global operator
  prompts
- report rendering tests for source references and missing-data notes
- regression tests proving write tools are not called before the target phase
- docs and progress updates that state what remains blocked

Do not mark a phase complete if the Agent can answer a global operator prompt
from generic market summary, model memory, or unreferenced prose.
