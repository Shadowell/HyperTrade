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
7. AUTOMATIC GIT COMMIT: every meaningful code, documentation, or configuration change MUST be committed and pushed to `origin/main` immediately after the change is made. Do not batch multiple unrelated changes into one commit. Each logical change gets its own commit with a descriptive message. After pushing, verify the deployment succeeds before reporting completion. Never push secrets or unfinished work.
8. Before pushing, ensure `./scripts/check.sh` passes for implementation work. If check.sh fails, fix issues before committing.

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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **HyperTrade** (17018 symbols, 38186 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/HyperTrade/context` | Codebase overview, check index freshness |
| `gitnexus://repo/HyperTrade/clusters` | All functional areas |
| `gitnexus://repo/HyperTrade/processes` | All execution flows |
| `gitnexus://repo/HyperTrade/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
