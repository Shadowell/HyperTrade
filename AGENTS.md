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
7. AUTOMATIC GIT COMMIT: every meaningful code, documentation, or configuration change MUST be committed immediately on the task branch — each logical change as its own commit with a descriptive message; never batch unrelated changes. Landing on `origin/main` always goes through a GitHub Pull Request per the "Worktrees And Landing" procedure below; never push feature work directly to `main` unless the user explicitly asks for an emergency direct push. Never push secrets or unfinished work, and never force-push shared branches.
8. Before landing, ensure `./scripts/check.sh` passes for implementation work. If check.sh fails, fix issues before committing.

## Worktrees And Landing

Parallel tasks run in per-task git worktrees (for example `~/.codex/worktrees/<id>/HyperTrade` on branch `codex/<topic>`), often with several sessions active at once. `origin/main` keeps moving, so never assume a task branch is current.

- A fresh worktree has no GitNexus index — `.gitnexus/` is gitignored, one index per worktree. Run `gitnexus analyze` once (~10s) before using GitNexus tools; re-run it whenever the staleness hook reports the index is behind HEAD. `gitnexus list` shows the worktree's registered alias; with several indexes registered, CLI queries take `--repo <alias>`.
- Default delivery always includes a GitHub Pull Request node, even when Codex may merge it itself. Once `./scripts/check.sh` passes:
  1. Work on a `codex/<task-name>` branch created from the latest `origin/main`; before opening the PR run `git fetch origin` and `git rebase origin/main`, resolve conflicts, then re-run `./scripts/check.sh`.
  2. `git push -u origin HEAD` and open a PR targeting `main` (`gh pr create --base main`).
  3. Merge the PR once required checks and mergeability allow it (`gh pr merge --merge --delete-branch`), then delete the feature branch. If the PR is not mergeable because `main` moved, fetch, rebase, verify, force-push only that feature branch, and retry.
  4. The merged `main` is the only deployment source.
- When the user says "push to GitHub", "publish to GitHub" or similar, interpret it as the full PR → merge → deploy-trigger flow unless the user explicitly says PR-only, do not merge, or do not deploy.
- Production deploys only from merged `main`: `Deploy HyperTrade` runs on `push` to `main`. After merging, confirm the `main` push happened and report that deployment was triggered from `main`; waiting for it to finish is only required when the user asks for runtime verification. If the `push` event fails or is delayed, re-run the deployment for `main` from GitHub Actions; never treat a feature-branch run as a production deploy.
- After Codex causes remote `main` to update, sync local `main` before finishing: `git fetch origin`, `git switch main`, `git pull --ff-only origin main`. If a stale worktree blocks `main`, clean up or remove that worktree first so local `main` matches `origin/main`.
- Keep worktree-local bookkeeping (GitNexus alias/count refreshes) on the task branch; it does not belong on `main`.

## Production-Oriented Comments

When adding or changing core Agent code, prefer concise comments that explain production boundaries: tool permissions, provider isolation, RAG/Memory auditability, risk gates, execution idempotency, and failure modes. Do not comment every line; comment orchestration points where future operators need to understand why the boundary exists.

## Standard Loop

1. Read current project state.
2. Select or create a sprint contract.
3. Implement only that slice.
4. Run verification.
5. Record QA findings if needed.
6. Update progress and next step.
7. MANDATORY: commit on the task branch, then land on `origin/main` through a Pull Request per "Worktrees And Landing" when verification passes.

## Verification

Spec Kit 入口：`.specify/` 与 `.agents/skills/speckit-*`；规格保留在 `specs/`，按七阶段流程推进。

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
