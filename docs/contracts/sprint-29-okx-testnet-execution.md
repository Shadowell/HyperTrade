# Sprint 29 Contract: OKX Testnet Signed Order Execution

## Goal

Execute OKX Testnet signed orders only after approval and risk validation.

## Scope

- Add OKX signed REST client.
- Add `POST /api/live/order-intents/{id}/execute`.
- Add CLI `/live execute <intent_id>`.
- Support market and limit buy/sell SWAP orders.
- Store exchange order id, redacted request, response payload, and execution timestamp.
- Keep Mainnet execution unimplemented and blocked.

## Acceptance

- Approved Testnet intent can execute when credentials are configured.
- Missing credentials produce auditable `execution_failed` status.
- Mainnet execution cannot happen.
- Secrets are never recorded in the database or API response.

## Verification

```bash
uv run pytest tests/test_live_order_intents.py -q
./scripts/check.sh
```

