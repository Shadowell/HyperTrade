# Sprint 41 Contract: Documentation Refresh

## Goal

Make HyperTrade documentation usable as the current source of truth for
operators and future agents, including the latest BitPro MCP and strategy
knowledge memory behavior.

## In Scope

- Add a `docs/README.md` navigation map.
- Update root README files with current capability and documentation entry
  points.
- Refresh knowledge-base docs for Memory, strategy research, tool usage, and
  operational validation.
- Refresh architecture docs for current V1 boundaries, strategy knowledge
  memory, deployment, and BitPro MCP safety.
- Refresh testing and deployment runbooks with strategy knowledge and BitPro
  result/paper smoke checks.
- Update `docs/progress.md`.

## Out Of Scope

- Code behavior changes.
- New frontend pages.
- New BitPro MCP tools.
- Publishing external documentation.

## Done Means

- A new reader can start from `README.md` or `docs/README.md` and find the
  current product scope, capability map, safety boundaries, operating guide, and
  deployment smoke checks.
- Documentation distinguishes local strategy knowledge memory from BitPro-owned
  backtest/paper evidence.
- `./scripts/check.sh` passes.

## Verification

```bash
./scripts/check.sh
```
