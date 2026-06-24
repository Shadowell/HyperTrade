# Sprint 66 - README Architecture and Onboarding Refresh

## Goal

Make the root README a richer project entry point by embedding the layered
HyperTrade architecture diagram and summarizing the current Agent, BitPro,
provider/model, workflow, and safety boundaries.

## In Scope

- Add the existing poster-style architecture SVG to the root README.
- Expand the root README with HyperTrade ownership, BitPro MCP/API boundary,
  V1 capabilities, core workflows, safety boundaries, documentation map, and
  repository layout.
- Mention the Codex numbered model picker and default `CODEX_MODEL_OPTIONS`
  allowlist so README readers understand where model choices come from.
- Keep the change documentation-only and avoid modifying unrelated Sprint 65
  live strategy performance routing files.

## Out of Scope

- Redesigning the architecture SVG asset.
- Changing Agent runtime, provider routing, CLI behavior, BitPro adapter
  behavior, deployment scripts, or tests.
- Committing secrets or production environment values.

## Done Means

- Root `README.md` displays `docs/assets/hypertrade-architecture.svg`.
- Root `README.md` explains the Agent/BitPro split, primary workflows, current
  capabilities, and safety boundaries without relying on chat history.
- `docs/progress.md` records the documentation refresh result.
- `./scripts/check.sh` is run before handoff.

## Verification

```bash
./scripts/check.sh
```

Manual or QA checks:

- Open the root README on GitHub or locally and confirm the architecture diagram
  renders before the quick-start section.
- Confirm the README links to
  `docs/architecture/19-hypertrade-architecture-diagram.md`.

## Risks / Notes

- The worktree already contains unrelated Sprint 65 live-strategy-performance
  routing changes. This sprint must not stage or overwrite those files.

## Handoff

- Next likely step: mirror any desired README structure updates into
  `README.en.md` and `README.zh-CN.md` if those language-specific pages should
  stay section-for-section identical with the root README.
