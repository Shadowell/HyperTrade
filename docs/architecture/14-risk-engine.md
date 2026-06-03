# 14 Risk Engine

## Purpose

RiskEngine is the shared pre-trade validation gate for live/testnet order intents.

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

