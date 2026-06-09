# BitPro MCP Data Access Runbook

## Purpose

This runbook describes how HyperTrade or an external Agent should call BitPro MCP to read interface data. HyperTrade must treat BitPro as an external capability provider: planning, trace, and risk gates stay in HyperTrade; BitPro is accessed only through the stable MCP/API contract.

## Connection

- Transport: `streamable-http` for remote Agents, `stdio` for same-host local Agents.
- Remote path: `/api/v2/mcp/`.
- Default API base reported by BitPro capabilities: `http://127.0.0.1:8889/api/v2`.
- Token header: `X-BitPro-MCP-Token`, unless `BITPRO_MCP_AUTH_HEADER` overrides it.
- Token environment variable: `BITPRO_MCP_API_TOKEN`.

Do not place tokens in the frontend. MCP tokens belong in server-side environment files such as `/opt/hypertrade/.env` or the process manager environment.

## Required Call Order

Every Agent flow starts with discovery and health checks:

1. `bitpro_capabilities`
   - Parameters: `{}`
   - Use it to read `contract_version`, supported transports, remote MCP path, tool groups, tool endpoints, permissions, disabled features, data policy, and live-trading flags.

2. `bitpro_health`
   - Parameters: `{}`
   - Use it to verify BitPro API availability, version, freshness, and degraded-source flags before calling data tools.

3. Select the smallest read tool for the user request.
   - Market/reference data: `market_symbols`, `market_klines`, `market_indicators`.
   - Backtest data or artifacts: `backtest_start_job`, then `backtest_get_job`, `backtest_list_results`, `backtest_get_result`.
   - Paper/simulation state: `paper_dashboard`, `paper_events`, `paper_equity_curve`.
   - Live read-only diagnostics: `live_preflight`, `trading_balance`, `trading_positions`, `trading_open_orders`.

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
| BitPro-owned backtest result | `backtest_get_job`, `backtest_list_results`, `backtest_get_result` | Start jobs only when the user explicitly asks BitPro to own the run. |
| Paper account state | `paper_dashboard`, `paper_events`, `paper_equity_curve` | Default to read-only. Writes require a separate user confirmation. |
| Live account diagnostics | `live_preflight`, `trading_balance`, `trading_positions`, `trading_open_orders` | Read-only only unless live-write confirmation is complete. |

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

When HyperTrade implements a native BitPro MCP adapter, keep the boundary explicit:

1. Store `BITPRO_MCP_URL` and `BITPRO_MCP_API_TOKEN` server-side only.
2. Implement a small MCP client wrapper that always calls `bitpro_capabilities` and `bitpro_health` before task-specific tools.
3. Register HyperTrade tools such as `bitpro.market_klines`, `bitpro.backtest_result`, `bitpro.paper_dashboard`, and `bitpro.live_positions` as audited adapter tools.
4. Persist each call in HyperTrade trace events with request id, tool name, parameters, result status, and redaction policy.
5. Keep live write tools disabled until a separate contract adds explicit approval and risk gates.
