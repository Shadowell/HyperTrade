# Sprint 05 Contract: Standalone Hybrid CLI Runtime

## Goal

Upgrade the CLI from an API-only client into a Claude/Codex/Hermes-style terminal entrypoint. Running `hypertrade` should start an interactive Agent session directly, while `--remote` keeps the option to connect to a deployed HyperTrade API.

## In Scope

- Make bare `hypertrade` start the interactive chat loop.
- Add local standalone runtime mode backed by `AgentKernel`, `Database`, `Settings`, `ToolRegistry`, RAG, Memory, and Trace persistence.
- Keep remote API mode with `hypertrade --remote <url>`.
- Keep one-shot mode with `hypertrade ask <prompt>`.
- Add `--local` to force local standalone runtime even when `HYPERTRADE_API_URL` is configured.
- Preserve environment-driven remote auth:
  - `HYPERTRADE_API_URL`
  - `HYPERTRADE_USERNAME`
  - `HYPERTRADE_PASSWORD`
  - `HYPERTRADE_TIMEOUT_SECONDS`
- Add tests for bare chat, remote selection, local AgentKernel execution, and API client behavior.
- Update CLI architecture and usage docs.

## Out of Scope

- Streaming token output.
- Slash commands such as `/tools`, `/runs`, `/memory`, or `/backtest`.
- Terminal rich UI.
- Live/Testnet trading commands.
- New trading strategy logic.

## Done Means

- `uv run hypertrade` starts an interactive terminal Agent.
- `uv run hypertrade --remote http://47.79.36.92:3333` starts remote interactive mode.
- `uv run hypertrade ask "请做行情归纳"` works in local standalone mode by default.
- `uv run hypertrade --remote http://47.79.36.92:3333 ask "请做行情归纳"` works in remote API mode.
- `./scripts/check.sh` passes.
- Server smoke verifies both local container mode and remote API mode.

## Verification

```bash
uv run pytest tests/test_cli.py -q
./scripts/check.sh
```

Server smoke:

```bash
cd /opt/hypertrade
docker compose exec -T api hypertrade ask "请做行情归纳"
docker compose exec -T \
  -e HYPERTRADE_API_URL=http://127.0.0.1:3334 \
  api hypertrade --remote http://127.0.0.1:3334 ask "请做行情归纳"
```

## Handoff

Next sprint should add Agent workflow slash commands: `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtest`.
