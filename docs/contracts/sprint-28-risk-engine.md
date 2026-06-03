# Sprint 28 Contract: Risk Engine

## Goal

Create a shared pre-trade risk gate before any Testnet execution path.

## Scope

- Add `RiskEngine` for live/testnet intent validation.
- Enforce max order notional, max open intents, allowed environment, and SWAP-only instruments.
- Mark blocked intents with `risk_blocked`.
- Store risk status and structured risk result on `live_order_intents`.
- Show risk status through API, CLI, and frontend.

## Acceptance

- Mainnet execution is always blocked.
- Oversized intents are blocked or marked `risk_blocked`.
- Approval re-runs risk validation.
- Risk status is visible in `/api/live/order-intents`, CLI `/live intents`, and `/harness`.

## Verification

```bash
uv run pytest tests/test_live_order_intents.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

