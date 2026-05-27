# AGENTS.md

## Purpose

This repository uses Codex as a delivery partner for HyperTrade, an independent agent-first trading research system. Codex should keep project state in files, work inside the active sprint contract, and never rely on chat history as the only source of truth.

## Files To Read First

Before substantial work, read:

1. `README.md`
2. `docs/spec.md`
3. `docs/progress.md`
4. the active contract under `docs/contracts/`
5. relevant architecture docs under `docs/architecture/`

## Operating Rules

1. Work only within the current sprint contract unless explicitly told to expand scope.
2. HyperTrade is independent from BitPro; do not copy BitPro business logic.
3. BitPro may only be used as a deployment and environment-shape reference.
4. Never commit secrets, OKX credentials, provider keys, database files, or production `.env`.
5. Update `docs/progress.md` after meaningful implementation steps.
6. If requirements, architecture, or API contracts change, update `docs/spec.md` and the active contract in the same change.

## Standard Loop

1. Read current project state.
2. Select or create a sprint contract.
3. Implement only that slice.
4. Run verification.
5. Record QA findings if needed.
6. Update progress and next step.

## Verification

Preferred entrypoint:

```bash
./scripts/check.sh
```

## Safety Boundaries

- Mainnet live trading is not enabled in Sprint 01.
- Live order tools require approval gates.
- Reports must remain research outputs and must not claim to be investment advice.
- Server-only secrets live in `/opt/hypertrade/.env`.

