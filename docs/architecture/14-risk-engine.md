# 14 Risk Engine

## Purpose

RiskEngine is the shared pre-trade validation gate for live/testnet order intents.
RiskGovernancePolicy is the shared Agent tool-governance gate for permission,
approval, scope, and idempotency decisions before any Agent-selected tool reaches
an internal service or external connector.

These layers have different jobs:

- `RiskGovernancePolicy` answers whether an Agent tool call is allowed,
  approval-gated, blocked, or missing required audit fields.
- `RiskEngine` checks order-specific market and account-risk constraints after
  a live/testnet order intent is created or approved.
- The Agent planner may request a tool, but trusted Python policy decides
  whether the request can execute.

## Governance Policy

Tool policy metadata lives in `ToolRegistry` and is enforced by
`AgentKernel` through `RiskGovernancePolicy`.

Scope classes:

- `read`: market, RAG, Memory search, strategy-library search, and BitPro read
  tools.
- `research_write`: internal research writes and external BitPro strategy or
  backtest mutations.
- `paper_write`: paper/simulation lifecycle changes.
- `testnet_write`: live-order intent creation for human approval and later
  Testnet execution paths.
- `live_diagnostic_read`: live account diagnostics that do not mutate state.
- `live_write`: future real-account mutations; these remain blocked unless a
  later sprint adds explicit confirmation and risk approval.

Policy outputs are deterministic and stored in graph trace payloads as
`policy_decision`. Write-like external actions with
`idempotency=required` must include `idempotency_key`; missing keys produce a
structured denial before the BitPro adapter, live service, or exchange path is
called.

Approval semantics:

- `approval=none`: execution may continue after policy validation.
- `approval=required`: execution may create an approval-gated record, but must
  not imply exchange execution.
- `approval=blocked`: execution is denied with a reason.

## Rules

- Environment must be `testnet`; Mainnet execution is blocked.
- Instrument must be `SWAP`.
- Open pending/approved intents must remain under `RISK_MAX_OPEN_INTENTS`.
- Estimated order notional must remain under `RISK_MAX_ORDER_NOTIONAL_USDT`.

For market orders, RiskEngine estimates notional from the latest `market_tickers` mark price when available. If no price is available, it records `unknown` and does not approve Mainnet execution.

## Persistence

`live_order_intents` stores:

- `risk_status`: `allowed`, `blocked`, or `pending`
- `risk_json`: violations and check details
- `execution_json`: redacted execution request/response
- `exchange_order_id`
- `executed_at`

## Flow

1. Create intent.
2. Run pre-check.
3. Mark `pending_approval` or `risk_blocked`.
4. On approval, run risk check again.
5. On execution, run risk check again before signed REST call.
