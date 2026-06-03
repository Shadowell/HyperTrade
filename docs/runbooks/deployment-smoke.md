# Deployment Smoke

Run after GitHub Actions deploys `main`.

```bash
curl -sS http://127.0.0.1:3334/api/health
curl -sS http://127.0.0.1:3333/api/health
```

Authenticated checks:

```bash
hypertrade --remote http://127.0.0.1:3334 ask "看下ETH行情"
printf "/status\n/model\n/evals\n:q\n" | hypertrade --remote http://127.0.0.1:3334
printf "/rag 风控\n/memory search 风控\n:q\n" | hypertrade --remote http://127.0.0.1:3334
```

Expected:

- API and Nginx health return `ok`.
- CLI shows run progress and final report.
- `/evals` returns deterministic passed cases.
- `/rag` and `/memory search` return stable output or `none` without crashing.

