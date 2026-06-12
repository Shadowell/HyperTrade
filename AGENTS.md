# AGENTS.md

## Purpose

This repository uses Codex as a delivery partner for HyperTrade, an independent production-oriented agent-first trading research and execution system. Codex should keep project state in files, work inside the active sprint contract, and never rely on chat history as the only source of truth.

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
3. BitPro may provide external APIs and data surfaces through stable contracts; never copy BitPro business logic into HyperTrade.
4. Never commit secrets, OKX credentials, provider keys, database files, or production `.env`.
5. Update `docs/progress.md` after meaningful implementation steps.
6. If requirements, architecture, or API contracts change, update `docs/spec.md` and the active contract in the same change.
7. MANDATORY: after `./scripts/check.sh` passes for implementation work on `main`, you MUST commit and push to `origin/main` so GitHub Actions deploys to production (`47.79.36.92`). Never push secrets or unfinished work.
8. MANDATORY: every completed code/documentation change must be merged/pushed and deployed. If work is already on `main`, commit and push directly to `origin/main`; if work is on another branch, merge it before deployment. After pushing, watch the deployment and verify production health before reporting completion.

## Production-Oriented Comments

When adding or changing core Agent code, prefer concise comments that explain production boundaries: tool permissions, provider isolation, RAG/Memory auditability, risk gates, execution idempotency, and failure modes. Do not comment every line; comment orchestration points where future operators need to understand why the boundary exists.

## Standard Loop

1. Read current project state.
2. Select or create a sprint contract.
3. Implement only that slice.
4. Run verification.
5. Record QA findings if needed.
6. Update progress and next step.
7. MANDATORY: commit and push to `origin/main` when verification passes.

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
