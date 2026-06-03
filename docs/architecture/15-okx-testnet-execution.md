# 15 OKX Testnet Execution

## Purpose

OKX signed execution is limited to Testnet and runs only after human approval and RiskEngine validation.

## Endpoint

```http
POST /api/live/order-intents/{id}/execute
```

CLI:

```bash
hypertrade
/live execute loi_...
```

## Signed Client

`OkxSignedRestClient` signs `POST /api/v5/trade/order` with:

- `OK-ACCESS-KEY`
- `OK-ACCESS-SIGN`
- `OK-ACCESS-TIMESTAMP`
- `OK-ACCESS-PASSPHRASE`
- `x-simulated-trading: 1` when `OKX_TESTNET=true`

## State Machine

- `pending_approval`
- `approved`
- `risk_blocked`
- `executed_testnet`
- `execution_failed`
- `rejected`

## Audit

Execution stores:

- redacted request payload
- response payload
- exchange order id
- executed timestamp
- error when execution fails

Secrets are never stored in PostgreSQL or returned by API.

