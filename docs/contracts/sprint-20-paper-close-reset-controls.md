# Sprint 20 Contract: Paper Close and Reset Controls

## Goal

Complete the paper-trading lifecycle controls so the operator can close simulated positions and reset the paper session from API or CLI while keeping historical sessions auditable.

## Scope

- Add API support for `POST /api/paper/control` actions `close` and `reset`.
- Add CLI support for `/paper close [symbol]`.
- Add CLI support for `/paper reset`.
- Close positions using the latest ticker price when available, falling back to the current position mark price.
- Record close orders, close fills, realized PnL, and paper events.
- Reset by marking the current session as `reset` and creating a fresh running session.

## Out Of Scope

- Mainnet live order execution.
- Testnet exchange order placement.
- Automatic stop loss / take profit logic.
- Deleting old paper session history.

## Acceptance

- `/paper close ETH` closes only `ETH-USDT-SWAP` open paper positions.
- `/paper close` closes all open paper positions.
- `/paper reset` creates a new running paper session and leaves prior session history visible in storage.
- Slash commands do not start an Agent run.
- `uv run pytest tests/test_paper_service.py tests/test_api.py tests/test_cli.py -q` passes.
- Full `./scripts/check.sh` passes.
