# Sprint 32 Contract: Learning Comments and Tool Guide

## Goal

Make the Agent engineering workflow easier to learn from the source code and docs without changing runtime behavior.

## Scope

- Add concise learning-oriented comments to core Agent modules:
  - Agent graph runtime
  - Tool registry
  - Provider routing
  - RAG search
  - Memory
  - Risk and OKX Testnet execution
  - Strategy experiment workflow
  - CLI slash command dispatcher
- Add a Chinese tool usage guide under `docs/knowledge`.
- Update repository operating rules so future work keeps comments educational but not noisy.
- Update progress after verification.

## Acceptance

- Comments explain orchestration boundaries and safety decisions, not obvious syntax.
- `docs/knowledge/tool-usage-guide.md` gives CLI/API/frontend/test/deploy usage paths.
- No secrets or server-only configuration are added.
- `./scripts/check.sh` passes.

## Verification

```bash
./scripts/check.sh
```
