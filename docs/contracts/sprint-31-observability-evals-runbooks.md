# Sprint 31 Contract: Observability, Evals, Runbooks

## Goal

Raise the project to a clearer enterprise Agent engineering showcase standard.

## Scope

- Add deterministic Agent eval suite.
- Add API `/api/evals/status` and CLI `/evals`.
- Show eval status in `/harness`.
- Add PostgreSQL backup/restore, incident response, deployment smoke, and OKX Testnet smoke runbooks.
- Update README/spec/progress/testing docs to reflect Agent stack.

## Acceptance

- Eval suite runs locally without provider keys.
- `/harness` exposes eval status.
- `./scripts/check.sh` remains the single verification entry point.
- Operations runbooks cover backup/restore, incident handling, deployment smoke, and Testnet order smoke.

## Verification

```bash
uv run pytest tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

