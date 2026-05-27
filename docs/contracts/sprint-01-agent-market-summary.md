# Sprint 01 Contract: Agent Market Summary

## Goal

Build the first usable end-to-end HyperTrade loop: ingest OKX perpetual swap market data, let a user trigger a market-summary agent run, and expose Provider, Tool Call, RAG, Memory, and trace state in `/harness`.

## In Scope

- Apply the Codex project harness.
- Implement FastAPI admin auth, health, harness, market, memory, and agent run APIs.
- Implement ToolRegistry and AgentKernel with market, RAG, and memory tools.
- Implement PostgreSQL/pgvector schema and worker process.
- Implement OKX SWAP ticker parser, WS stream, REST fallback path.
- Implement React `/harness` and market summary page.
- Implement Docker Compose, Nginx, and main-only self-hosted deployment.
- Write architecture docs for all Sprint 01 modules and later-sprint boundaries.

## Out of Scope

- Mainnet order execution.
- Paper trading runtime.
- Backtrader strategy execution.
- Milvus/Qdrant deployment.
- Automatic PostgreSQL backups.

## Deliverables

- Backend and frontend code.
- Tests and `scripts/check.sh`.
- Docker/deploy files.
- Architecture documents.
- Updated spec and progress log.

## Done Means

- Backend tests pass.
- Frontend tests pass and build succeeds.
- `/api/health` can be served locally.
- `/harness` renders operational state.
- Deployment path is documented and does not commit secrets.

## Verification

```bash
./scripts/check.sh
```

Manual checks:

- Open `http://localhost:3333`.
- Log in with local `.env` admin credentials.
- Trigger an Agent market summary.
- Inspect trace events in `/harness`.

## Risks / Notes

- OKX access is expected to be reliable only from `47.79.36.92`.
- V1 secrets stay in server `.env`; the public repository must not include keys.

## Handoff

- Next likely step: Sprint 02 automatic paper trading.

