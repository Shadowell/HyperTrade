# Sprint 18 Contract: Paper Trading CLI Controls

## Goal

Expose the existing paper-trading runtime through CLI slash commands so the operator can inspect, pause, and resume simulated trading without opening the web harness.

## Scope

- Add `/paper status`.
- Add `/paper pause`.
- Add `/paper resume`.
- Support local and remote CLI runtimes.
- Render session, positions, recent fills, and recent events in script-friendly plain text.
- Keep live/mainnet order execution out of scope.

## Out Of Scope

- Mainnet live order controls.
- Creating new paper strategies.
- Position close/edit commands.
- Rich rendering for paper tables.

## Acceptance

- `/paper status` prints session state, positions, fills, and events.
- `/paper pause` calls the paper control API/service and reports paused state.
- `/paper resume` calls the paper control API/service and reports running state.
- Slash commands do not start an Agent run.
- `uv run pytest tests/test_cli.py -q` passes.
- Full `./scripts/check.sh` passes.
- Server smoke verifies `/paper status`, `/paper pause`, and `/paper resume`.
