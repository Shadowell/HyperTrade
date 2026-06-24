# Sprint 69 - README Framework Guide

## Goal

Rewrite the root README so it reads like a real open-source framework guide:
clear positioning, component responsibilities, usage paths, installation,
deployment, operations, and extension points.

## In Scope

- Replace the short capability-list README with a structured guide for
  operators, engineers, and external Agent integrators.
- Explain the major components: Agent runtime, provider router, ToolRegistry,
  market tools, RAG, Memory, strategy research, BitPro adapter, risk gates,
  monitoring, API, CLI, frontend, worker, evals, and deployment.
- Add copyable local quickstart, CLI examples, REST API examples, production
  deployment notes, and troubleshooting pointers.
- Preserve the HyperTrade/BitPro boundary and V1 safety limits.
- Update `docs/progress.md` and, if needed, `docs/spec.md` to record the
  documentation slice.

## Out of Scope

- Runtime behavior changes.
- New Agent tools, API endpoints, UI changes, or deployment mechanics.
- Editing secrets or production environment files.
- Rewriting all secondary READMEs in this slice.

## Done Means

- Root `README.md` has enough detail for a new engineer to install, run, use,
  deploy, and extend HyperTrade without reading chat history.
- Each major component has a concise purpose, entry point, source path, and
  documentation pointer.
- Verification passes with `./scripts/check.sh`.
- The change is committed, pushed to `origin/main`, deployed, and production
  health-smoked.

## Verification

```bash
./scripts/check.sh
```

Production smoke after deployment:

```bash
curl -fsS http://47.79.36.92:3333/api/health
```

## Handoff

- Future documentation slices can mirror this structure into
  `README.zh-CN.md` and `README.en.md`, or split deeper tutorials into
  `docs/knowledge/`.
