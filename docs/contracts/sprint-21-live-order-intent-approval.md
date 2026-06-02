# Sprint 21 Contract: Live Order Intent Approval Gate

## Goal

Add the first live/testnet trading control surface without allowing unattended exchange execution. The Agent, API, and CLI can create order intents, but every intent must remain pending until a human approves or rejects it.

## Scope

- Add `live_order_intents` storage with Alembic migration.
- Add `LiveOrderIntentService` for create/list/approve/reject.
- Add API endpoints under `/api/live/order-intents`.
- Add CLI commands:
  - `/live intents`
  - `/live intent ETH buy 0.01 [--type limit --price 3500 --reason text]`
  - `/live approve loi_* [--reason text]`
  - `/live reject loi_* [--reason text]`
- Add Agent planner tool `live_order_intent`.
- Keep exchange execution out of this sprint.

## Safety Rules

- Created intents start as `pending_approval`.
- Approval changes status only; it does not place an OKX order.
- Rejected or approved intents cannot be decided again.
- Invalid order shape is rejected before persistence.
- UI/API/CLI responses expose environment and status so the operator can see whether the system is in testnet or mainnet mode.

## Out Of Scope

- OKX signed REST order placement.
- Mainnet account balances.
- Mainnet auto-trading.
- Position sizing recommendations by the Agent.

## Acceptance

- API can create, list, approve, and reject order intents.
- CLI can create, list, approve, and reject order intents.
- Agent planner can call `live_order_intent`, resulting only in a pending approval record.
- `live_order_intents` appear in `/api/harness/overview`.
- `uv run pytest tests/test_live_order_intents.py tests/test_api.py tests/test_cli.py -q` passes.
- Full `./scripts/check.sh` passes.
