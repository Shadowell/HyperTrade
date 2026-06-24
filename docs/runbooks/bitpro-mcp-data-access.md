# BitPro MCP Data Access Runbook

## Purpose

This runbook describes how HyperTrade or an external Agent should call BitPro MCP to read interface data. HyperTrade must treat BitPro as an external capability provider: planning, trace, and risk gates stay in HyperTrade; BitPro is accessed only through the stable MCP/API contract.

## Connection

- Transport: `streamable-http` for remote Agents, `stdio` for same-host local Agents.
- Remote path: `/api/v2/mcp/`.
- Default API base reported by BitPro capabilities: `http://127.0.0.1:8889/api/v2`.
- Docker Compose deployments should set `BITPRO_MCP_API_BASE=http://host.docker.internal:8889/api/v2`; `docker-compose.yml` maps `host.docker.internal` to the Linux host gateway for `api` and `worker`.
- Token header: `X-BitPro-MCP-Token`, unless `BITPRO_MCP_AUTH_HEADER` overrides it.
- Token source: generate an MCP Agent Token in BitPro Settings -> Agent Access -> MCP Agent Token, or through `POST /api/v2/settings/mcp-agent-tokens`; the legacy `/settings/mcp-token/generate` UI path remains a compatible operator shortcut.
- Token environment variable in HyperTrade: `BITPRO_MCP_API_TOKEN`.

Do not place tokens in the frontend. MCP tokens belong in server-side environment files such as `/opt/hypertrade/.env` or the process manager environment. BitPro stores only token hashes and returns plaintext only at creation time.

## Required Call Order

Every Agent flow starts with discovery and health checks:

1. `bitpro_capabilities`
   - Parameters: `{}`
   - Use it to read `contract_version`, supported transports, remote MCP path, tool groups, tool endpoints, permissions, disabled features, data policy, and live-trading flags.
   - Use `agent_auth` to understand the expected header, Token management routes, scope classes, and tools that require idempotency keys.

2. `bitpro_health`
   - Parameters: `{}`
   - Use it to verify BitPro API availability, version, freshness, and degraded-source flags before calling data tools.

3. Select the smallest read tool for the user request.
   - Market/reference data: `market_symbols`, `market_klines`, `market_indicators`.
   - Backtest data or artifacts: `backtest_start_job`, then `backtest_get_job`, `backtest_list_results`, `backtest_get_result`.
   - Paper/simulation state: `paper_dashboard`, `paper_events`, `paper_equity_curve`.
   - Live read-only diagnostics: `live_preflight`, `trading_balance`, `trading_positions`, `trading_open_orders`, `trading_order_history`.

4. Record audit fields in HyperTrade.
   - Include Agent run id, tool call id, BitPro request id when available, tool name, parameters after redaction, status, latency, and data freshness.

## Example Agent Flow

```ts
const capabilities = await mcp.callTool("bitpro_capabilities", {});
assert(capabilities.contract_version === "bitpro-mcp-v1");

const health = await mcp.callTool("bitpro_health", {});
if (health.status !== "healthy") {
  throw new Error(`BitPro unavailable: ${health.status}`);
}

const klines = await mcp.callTool("market_klines", {
  symbol: "ETH-USDT-SWAP",
  timeframe: "1H",
  limit: 200
});
```

The exact parameter schema must come from `bitpro_capabilities` and the BitPro interface docs. Do not guess hidden parameters.

## Read Scopes By Use Case

| Need | First tools | Notes |
| --- | --- | --- |
| Symbol list and contract metadata | `market_symbols` | Use canonical OKX instrument ids such as `ETH-USDT-SWAP`. |
| K-line window for research or backtest | `market_klines` | If data is missing, shorten the range or ask the user whether to trigger sync. |
| Indicator snapshot | `market_indicators` | Keep indicator source and freshness in trace output. |
| BitPro-owned backtest result | `backtest_get_job`, `backtest_list_results`, `backtest_get_result` | Use `backtest_list_results` for ranking or threshold questions; filter actual `total_return_pct`, not annualized return. Start jobs only when the user explicitly asks BitPro to own the run. |
| Paper account state | `paper_dashboard`, `paper_events`, `paper_equity_curve` | Default to read-only. Writes require a separate user confirmation. |
| Live account diagnostics | `live_preflight`, `trading_balance`, `trading_positions`, `trading_open_orders`, `trading_order_history` | Read-only only unless live-write confirmation is complete. Use order history for prompts such as `我的实盘最近的一笔订单是什么`. |

## Write Boundary

Do not call live-write tools by default.

Live-write tools include `live_promote`, `trading_spot_order`, `trading_futures_order`, `trading_cancel_order`, and `trading_transfer`. They require:

- `BITPRO_MCP_ENABLE_LIVE_TRADING=1` on BitPro.
- User-provided `confirm_live_risk=true`.
- User-provided `confirmation="I_UNDERSTAND_REAL_TRADING_RISK"`.
- Non-empty `reason`.
- Unique `idempotency_key`.

The Agent must not generate or infer those confirmation fields for the user.

## HyperTrade Adapter Shape

HyperTrade now includes a BitPro MCP adapter in `backend/src/hypertrade/bitpro/mcp.py`. Keep the boundary explicit:

1. Store `BITPRO_MCP_API_BASE`, `BITPRO_MCP_API_TOKEN`, and `BITPRO_MCP_AUTH_HEADER` server-side only.
2. Use the adapter wrapper that always calls `bitpro_capabilities` and `bitpro_health` before task-specific tools.
3. Registered HyperTrade read tools include `bitpro.capabilities`, `bitpro.health`, `bitpro.market_klines`, `bitpro.paper_dashboard`, `bitpro.live_positions`, and `bitpro.live_order_history`.
4. Registered HyperTrade strategy lifecycle tools include `bitpro.strategy_search`, `bitpro.strategy_generate`, `bitpro.strategy_create`, `bitpro.strategy_update`, `bitpro.backtest_start_job`, `bitpro.backtest_get_job`, `bitpro.backtest_list_results`, `bitpro.backtest_get_result`, `bitpro.paper_configure`, `bitpro.paper_start`, `bitpro.paper_pause`, `bitpro.paper_resume`, and `bitpro.paper_stop`.
5. Agent calls persist nested BitPro trace events such as `bitpro.capabilities`, `bitpro.health`, `bitpro.market_klines`, `bitpro.strategy_create`, `bitpro.strategy_update`, `bitpro.backtest_start_job`, `bitpro.backtest_list_results`, `bitpro.backtest_get_result`, and `bitpro.paper_start`.
6. Strategy lifecycle writes are limited to BitPro research/backtest/paper tools. They require an explicit user request and must remain auditable in the Agent trace.
7. Backtests can use `candle_source=bitpro_mcp` or CLI `/backtest --source bitpro_mcp --symbol ETH --bar 1H --limit 200`.
8. Surface `remote_mcp`, `agent_auth`, `tool_groups`, and token status in `/api/harness/overview` without exposing token plaintext.
9. Keep live write tools disabled until a separate contract adds explicit approval and risk gates.

For a page-parity answer such as `回测收益大于100%的策略有哪些`, the Agent should call
`bitpro_backtest_list_results` with parameters similar to:

```json
{
  "min_total_return_pct": 100,
  "status": "completed",
  "sort_by": "return",
  "sort_order": "desc",
  "limit": 100
}
```

The report must name the metric as `total_return_pct`. If annualized return is
also shown, label it separately.

## HyperTrade API Entrypoints

All endpoints require the normal HyperTrade admin session:

- `GET /api/bitpro/health`
- `GET /api/bitpro/market/klines/{symbol}?timeframe=1h&limit=200`
- `GET /api/bitpro/paper/dashboard`
- `GET /api/bitpro/live/positions?exchange=okx&symbol=ETH`

The `/harness` overview exposes adapter status under `bitpro` without exposing the token value. Operators should see API base, auth header, token configured status, token source, scope classes, and the HyperTrade live-write gate.

## Production Connectivity Check

If `/api/bitpro/health` returns unavailable, verify the connection from inside the API container:

```bash
docker compose exec -T api python - <<'PY'
import os
import urllib.request

base = os.environ["BITPRO_MCP_API_BASE"].rstrip("/")
header = os.environ.get("BITPRO_MCP_AUTH_HEADER", "X-BitPro-MCP-Token")
token = os.environ["BITPRO_MCP_API_TOKEN"]
request = urllib.request.Request(f"{base}/system/health", headers={header: token})
with urllib.request.urlopen(request, timeout=5) as response:
    print(response.status)
PY
```

Inside a container, `127.0.0.1` points to the HyperTrade container itself. Use `host.docker.internal` or the Docker network gateway when BitPro runs on the host.
