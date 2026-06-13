# Deployment Smoke

Run after GitHub Actions deploys `main`.

```bash
curl -sS http://127.0.0.1:3334/api/health
curl -sS http://127.0.0.1:3333/api/health
```

Authenticated checks:

```bash
hypertrade ask "看下ETH行情"
hypertrade --remote http://127.0.0.1:3334 ask "看下ETH行情"
printf "/status\n/model\n/evals\n:q\n" | hypertrade --remote http://127.0.0.1:3334
printf "/rag 风控\n/memory search 风控\n:q\n" | hypertrade --remote http://127.0.0.1:3334
printf "/experiment 研究ETH趋势突破\n/memory search momentum_breakout_v1\n:q\n" | hypertrade --remote http://127.0.0.1:3334
```

Expected:

- API and Nginx health return `ok`.
- Host wrapper and explicit remote CLI show run progress and final report.
- `/evals` returns deterministic passed cases.
- `/rag` and `/memory search` return stable output or `none` without crashing.
- `/experiment` creates an `exp_*` experiment and a searchable `strategy_knowledge` memory item.

Optional BitPro MCP smoke when the production BitPro MCP endpoint is configured:

```bash
hypertrade --remote http://127.0.0.1:3334 ask "查看 BitPro 回测收益大于100%的策略有哪些"
hypertrade --remote http://127.0.0.1:3334 ask "查看 BitPro 回测 result 196 的权益曲线和交易证据"
hypertrade --remote http://127.0.0.1:3334 ask "监控 BitPro 所有运行中的模拟盘策略，列出异常和数据缺口"
```

Expected BitPro observations:

- Every BitPro flow starts with `bitpro_capabilities` and `bitpro_health`.
- Backtest ranking uses `total_return_pct` from BitPro result rows.
- Backtest detail shows real result metrics plus bounded artifact availability.
- Paper monitoring distinguishes the current dashboard view from all running strategies and reports missing per-strategy metrics as data gaps.
