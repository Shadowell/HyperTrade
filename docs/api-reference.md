# HyperTrade API Reference

## Overview

HyperTrade provides a comprehensive REST API for Agent-driven crypto trading research and execution. The API is built with FastAPI and follows RESTful conventions.

**Base URL**: `http://localhost:3334/api`  
**Production URL**: `http://47.79.36.92:3333/api`

**API Documentation**: Visit `/docs` for interactive Swagger documentation.

## Authentication

Most read endpoints are publicly accessible. Write operations and privileged actions require admin session authentication.

### POST /auth/login

Authenticate and obtain a session cookie.

**Request Body**:
```json
{
  "username": "string",
  "password": "string"
}
```

**Response**:
```json
{
  "status": "ok",
  "username": "string"
}
```

**Cookie Set**: `hypertrade_session` (HttpOnly, SameSite=Lax)

### POST /auth/logout

Clear the session cookie.

**Authentication**: Required

**Response**:
```json
{
  "status": "ok"
}
```

### GET /auth/me

Get the current authenticated user.

**Authentication**: Required

**Response**:
```json
{
  "username": "string"
}
```

---

## Harness & System

### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "service": "hypertrade-api"
}
```

### GET /harness/overview

Complete system overview including providers, tools, connectors, market state, recent runs, trace events, and service status.

**Response**:
```json
{
  "generated_at": "2026-07-05T12:00:00Z",
  "providers": [...],
  "tools": [...],
  "connectors": [...],
  "market": {
    "ticker_count": 100,
    "latest_ticker_at": "2026-07-05T11:59:00Z",
    "latest_update_age_seconds": 60,
    "top_movers": [...]
  },
  "agent_runs": {
    "total_count": 1234,
    "recent": [...]
  },
  "rag": {
    "document_count": 50,
    "chunk_count": 500
  },
  "memory": {
    "active_count": 80,
    "total_count": 100,
    "latest_created_at": "2026-07-05T10:00:00Z"
  },
  "trace": {
    "total_count": 5000,
    "recent_events": [...]
  },
  "paper": {...},
  "strategy_lab": {...},
  "live_orders": {...},
  "bitpro": {...},
  "evals": {...}
}
```

### GET /harness/providers

List available chat providers and their configuration.

**Response**:
```json
{
  "providers": [
    {
      "name": "deepseek",
      "display_name": "DeepSeek",
      "configured": true,
      "selected": true,
      "model": "",
      "available_models": []
    }
  ]
}
```

### POST /harness/provider-selection

Switch the active chat provider and model.

**Authentication**: Required

**Request Body**:
```json
{
  "provider": "deepseek",
  "model": ""
}
```

**Response**:
```json
{
  "default_provider": "deepseek",
  "model": "",
  "providers": [...]
}
```

### GET /harness/tools

List all registered Agent tools with their policies.

**Response**:
```json
{
  "tools": [
    {
      "name": "market.summary",
      "description": "Summarize OKX SWAP market state.",
      "category": "market",
      "requires_approval": false,
      "policy": {
        "scope": "read",
        "approval": "none",
        "idempotency": "not_required",
        "source_of_truth": "hypertrade_db",
        "timeout_class": "standard",
        "safe_sample_limit": 0,
        "failure_behavior": "return_structured_error"
      },
      "connector_origin": null
    }
  ]
}
```

---

## Agent Sessions and Tasks

`AgentTask` is the durable control record. `AgentRun` is one immutable execution
attempt linked through `resource_type=agent_run` and `resource_id`.

### POST /agent/sessions

Create a durable operator Session. **Authentication required.** Provider config
must contain names/models only; credentials are discarded.

### GET /agent/sessions

List durable Sessions. `GET /agent/sessions/{session_id}` reads one Session.

### POST /agent/sessions/{session_id}/tasks

Create a queued Task. **Authentication required.** The request includes
`objective`, a unique `idempotency_key`, optional `kind`, parent/resource refs,
and bounded budget fields.

### GET /agent/tasks

List Tasks, optionally filtered by `session_id` or `status`.
`GET /agent/tasks/{task_id}` includes the latest checkpoint projection.

### POST /agent/tasks/{task_id}/{action}

Supported actions are `pause`, `resume`, `cancel`, `retry`, and `branch`.
**Authentication required.** Every request requires `reason` and
`idempotency_key`; `actor` defaults to `operator`.

### GET /agent/tasks/{task_id}/events

Read append-only safe events with `after=<sequence>` and bounded `limit`.

### GET /agent/tasks/{task_id}/stream

Stream events using SSE. Resume with `after=<sequence>` or `Last-Event-ID`.
Each committed event includes an SSE `id` equal to its Task sequence.

---

## Agent Runs

### POST /agent/runs

Create a new Agent run with a free-form prompt.

New runs are automatically wrapped in an inline-reserved Session/Task. Clients
may send `Idempotency-Key`; a completed duplicate returns the linked Run.

**Request Body**:
```json
{
  "prompt": "看下目前市场的热度怎么样"
}
```

**Response**:
```json
{
  "run_id": "run_abc123",
  "prompt": "看下目前市场的热度怎么样",
  "status": "completed",
  "report": "...",
  "metadata": {...},
  "trace": [...],
  "created_at": "2026-07-05T12:00:00Z",
  "completed_at": "2026-07-05T12:00:05Z"
}
```

### POST /agent/runs/stream

Create a streaming Agent run with Server-Sent Events.

**Request Body**:
```json
{
  "prompt": "请做行情归纳"
}
```

**Response**: Server-Sent Events stream

**Event Types**:
- `run_start`: Run initialized
- `tool_start`: Tool execution started
- `tool_complete`: Tool execution completed
- `run_complete`: Run finished

**Example Events**:
```
event: run_start
data: {"run_id": "run_abc123", "prompt": "..."}

event: tool_start
data: {"tool": "market.summary", "started_at": "..."}

event: tool_complete
data: {"tool": "market.summary", "result": {...}}

event: run_complete
data: {"run_id": "run_abc123", "status": "completed", "report": "..."}
```

### GET /agent/runs

List recent Agent runs (latest 25).

**Response**:
```json
{
  "runs": [
    {
      "id": "run_abc123",
      "prompt": "看下目前市场的热度怎么样",
      "status": "completed",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

### GET /agent/runs/{run_id}

Get detailed information about a specific run.

**Response**:
```json
{
  "run_id": "run_abc123",
  "prompt": "...",
  "status": "completed",
  "report": "...",
  "metadata": {...},
  "trace": [...],
  "created_at": "...",
  "completed_at": "..."
}
```

### POST /agent/runs/{run_id}/cancel

Cancel a running Agent run.

**Authentication**: Required

**Response**:
```json
{
  "status": "cancelled",
  "run_id": "run_abc123"
}
```

---

## Market Data

### GET /market/tickers/latest

Get latest market tickers for all OKX SWAP instruments.

**Response**:
```json
{
  "tickers": [
    {
      "inst_id": "BTC-USDT-SWAP",
      "last": "50000.0",
      "volume_ccy_24h": "1000000.0",
      "change_utc0_pct": "2.5",
      "updated_at": "2026-07-05T12:00:00Z"
    }
  ],
  "count": 100,
  "latest_at": "2026-07-05T12:00:00Z"
}
```

### GET /market/ticker/{symbol}

Get ticker for a specific symbol.

**Path Parameters**:
- `symbol`: Symbol name (e.g., `BTC`, `ETH`) or instrument ID (e.g., `BTC-USDT-SWAP`)

**Response**:
```json
{
  "inst_id": "BTC-USDT-SWAP",
  "last": "50000.0",
  "volume_ccy_24h": "1000000.0",
  "change_utc0_pct": "2.5",
  "funding_rate": "0.0001",
  "open_interest": "5000000.0",
  "updated_at": "2026-07-05T12:00:00Z"
}
```

### GET /market/candles/{symbol}

Get candlestick data for a symbol.

**Path Parameters**:
- `symbol`: Symbol name or instrument ID

**Query Parameters**:
- `bar`: Timeframe (e.g., `1H`, `4H`, `1D`), default `1H`
- `limit`: Number of candles, default `100`, max `500`

**Response**:
```json
{
  "symbol": "BTC",
  "inst_id": "BTC-USDT-SWAP",
  "bar": "1H",
  "candles": [
    {
      "ts": "2026-07-05T12:00:00Z",
      "open": "50000.0",
      "high": "50500.0",
      "low": "49800.0",
      "close": "50200.0",
      "volume": "1000.0"
    }
  ],
  "count": 100,
  "trend_features": {
    "sma_20": "50100.0",
    "ema_12": "50150.0",
    "rsi_14": "55.0"
  }
}
```

### POST /market/compare

Compare multiple symbols for relative strength ranking.

**Request Body**:
```json
{
  "symbols": ["BTC", "ETH", "SOL"],
  "bar": "4H",
  "limit": 100
}
```

**Response**:
```json
{
  "symbols": ["BTC", "ETH", "SOL"],
  "bar": "4H",
  "comparison": [
    {
      "symbol": "SOL",
      "rank": 1,
      "change_pct": "5.2",
      "relative_strength": "strong"
    },
    {
      "symbol": "ETH",
      "rank": 2,
      "change_pct": "3.1",
      "relative_strength": "moderate"
    },
    {
      "symbol": "BTC",
      "rank": 3,
      "change_pct": "1.8",
      "relative_strength": "moderate"
    }
  ]
}
```

---

## RAG (Retrieval-Augmented Generation)

### GET /rag/search

Search knowledge documents with citation-ready results.

**Query Parameters**:
- `query`: Search query string (required)
- `limit`: Number of results, default `5`, max `20`

**Response**:
```json
{
  "query": "风控",
  "hits": [
    {
      "chunk_id": "chunk_123",
      "document_path": "docs/knowledge/risk-management.md",
      "content": "风控是交易系统的核心...",
      "score": 0.85,
      "metadata": {
        "section": "风险管理基础"
      }
    }
  ],
  "count": 3
}
```

---

## Memory

### GET /memory

Search or list memory items.

**Query Parameters**:
- `query`: Search query (optional)
- `tag`: Filter by tag (optional)
- `type`: Filter by type (`observation`, `strategy_knowledge`, `market_context`) (optional)
- `limit`: Number of results, default `10`, max `50`

**Response**:
```json
{
  "items": [
    {
      "id": "mem_abc123",
      "type": "strategy_knowledge",
      "content": "动量突破策略在趋势市场中表现良好...",
      "tags": ["strategy", "momentum", "breakout"],
      "confidence": 0.8,
      "importance": 0.9,
      "disabled": false,
      "usage_count": 5,
      "created_at": "2026-07-05T10:00:00Z"
    }
  ],
  "count": 1
}
```

### DELETE /memory/{memory_id}

Delete or disable a memory item.

**Authentication**: Required

**Response**:
```json
{
  "status": "deleted",
  "memory_id": "mem_abc123"
}
```

---

## Research Evidence V2

Research Evidence V2 is append-only. Read endpoints return effective expiry,
source-health/data-gap projections, content hash, lifecycle, and legacy labels;
they never promote Memory into a verified fact.

### POST /research/evidence

Append one discriminated `fact`, `inference`, `counter_evidence`, or `data_gap`.
**Authentication required.** Common fields include `claim`, `scope`, `sources`,
`confidence`, `as_of`, optional `valid_until`, Task/Node/role refs, and supporting
or opposing evidence IDs. Facts require an available non-Memory source.

### GET /research/evidence

List V2 evidence. Filters: `task_id`, `type`, `status`, `symbol`, and `limit`.
Set `include_legacy=true` without other filters to include explicitly labelled
legacy experiment and Memory projections.

### GET /research/evidence/{evidence_id}

Read one V2 or legacy record. V2 responses include stable `content_hash`,
`stored_status`, effective `status`, `source_health`, `data_gaps`, and lifecycle.

### GET /research/evidence/{evidence_id}/graph

Read bounded relation nodes/edges. `depth` defaults to 2 and is capped at 5.

### POST /research/evidence/{evidence_id}/{action}

Supported lifecycle actions are `supersede`, `expire`, and `reject`.
**Authentication required.** Expire/reject require a reason; supersede requires
a reason plus a complete replacement evidence payload. Historical claim/payload
content is never updated in place.

---

## Strategy Research

### POST /strategy/research

Create a new strategy research record.

**Request Body**:
```json
{
  "prompt": "研究ETH趋势突破策略"
}
```

**Response**:
```json
{
  "research_id": "res_abc123",
  "prompt": "研究ETH趋势突破策略",
  "status": "created",
  "report": "...",
  "created_at": "2026-07-05T12:00:00Z"
}
```

### GET /strategy/research

List recent strategy research records.

**Query Parameters**:
- `limit`: Number of results, default `10`, max `50`

**Response**:
```json
{
  "research_records": [
    {
      "research_id": "res_abc123",
      "prompt": "研究ETH趋势突破策略",
      "status": "completed",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

### POST /strategy/experiments

Create a new strategy experiment with multiple variants.

**Request Body**:
```json
{
  "prompt": "实验ETH动量突破策略的不同参数"
}
```

**Response**:
```json
{
  "experiment_id": "exp_abc123",
  "variants": ["baseline", "fast", "conservative"],
  "results": [...],
  "winner": "fast",
  "next_experiment": "尝试优化止损参数"
}
```

### POST /strategy/experiments/iterate

Plan the next experiment based on prior evidence.

**Request Body**:
```json
{
  "prompt": "基于之前的动量策略证据，规划下一个实验"
}
```

**Response**:
```json
{
  "plan": "...",
  "prior_evidence": [...],
  "suggested_variants": [...]
}
```

### GET /strategy/experiments

List recent strategy experiments.

**Response**:
```json
{
  "experiments": [
    {
      "experiment_id": "exp_abc123",
      "prompt": "...",
      "winner": "fast",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

### GET /strategy/library

Get strategy library aggregated from memory.

**Query Parameters**:
- `strategy_name`: Filter by strategy name (optional)
- `tag`: Filter by tag (optional)

**Response**:
```json
{
  "strategies": [
    {
      "strategy_name": "momentum_breakout_v1",
      "evidence_count": 5,
      "avg_confidence": 0.85,
      "tags": ["momentum", "breakout"],
      "latest_evidence": {...}
    }
  ]
}
```

---

## Backtest

### POST /backtests

Create and run a backtest.

**Request Body**:
```json
{
  "research_id": "res_abc123",
  "strategy_key": "momentum_breakout_v1",
  "initial_cash": "100000",
  "symbol": "BTC",
  "bar": "1H",
  "candle_limit": 100,
  "candle_source": "okx",
  "use_live_candles": true
}
```

**Response**:
```json
{
  "backtest_id": "bt_abc123",
  "status": "completed",
  "metrics": {
    "total_return_pct": 15.5,
    "sharpe_ratio": 1.8,
    "max_drawdown_pct": -8.2,
    "win_rate": 0.65,
    "total_trades": 50
  },
  "equity_curve": [...],
  "trades": [...]
}
```

### GET /backtests

List recent backtests.

**Query Parameters**:
- `limit`: Number of results, default `10`, max `50`

**Response**:
```json
{
  "backtests": [
    {
      "backtest_id": "bt_abc123",
      "strategy_key": "momentum_breakout_v1",
      "total_return_pct": 15.5,
      "status": "completed",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

---

## Paper Trading

### GET /paper/status

Get paper trading status and positions.

**Response**:
```json
{
  "enabled": true,
  "running": true,
  "equity_usdt": "105000.0",
  "starting_equity_usdt": "100000.0",
  "pnl_usdt": "5000.0",
  "pnl_pct": "5.0",
  "positions": [
    {
      "symbol": "BTC",
      "side": "long",
      "size": "0.5",
      "entry_price": "48000.0",
      "current_price": "50000.0",
      "pnl_usdt": "1000.0"
    }
  ]
}
```

### POST /paper/control

Control paper trading (pause, resume, close, reset).

**Authentication**: Required

**Request Body**:
```json
{
  "action": "pause",
  "symbol": "BTC"
}
```

**Actions**:
- `pause`: Pause trading for a symbol or all
- `resume`: Resume trading
- `close`: Close all positions
- `reset`: Reset to initial state

**Response**:
```json
{
  "status": "ok",
  "action": "pause",
  "symbol": "BTC"
}
```

---

## Live Order Intents

### POST /live/order-intents

Create a live order intent (requires approval before execution).

**Request Body**:
```json
{
  "symbol": "BTC",
  "side": "buy",
  "size": "0.01",
  "order_type": "market",
  "price": null,
  "reason": "API smoke test"
}
```

**Response**:
```json
{
  "intent_id": "loi_abc123",
  "status": "pending_approval",
  "symbol": "BTC",
  "side": "buy",
  "size": "0.01",
  "created_at": "2026-07-05T12:00:00Z"
}
```

### GET /live/order-intents

List live order intents.

**Response**:
```json
{
  "intents": [
    {
      "intent_id": "loi_abc123",
      "status": "pending_approval",
      "symbol": "BTC",
      "side": "buy",
      "size": "0.01",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

### POST /live/order-intents/{intent_id}/approve

Approve a pending order intent.

**Authentication**: Required

**Request Body**:
```json
{
  "reason": "Approved for testing"
}
```

**Response**:
```json
{
  "status": "approved",
  "intent_id": "loi_abc123",
  "approved_at": "2026-07-05T12:01:00Z"
}
```

### POST /live/order-intents/{intent_id}/reject

Reject a pending order intent.

**Authentication**: Required

**Request Body**:
```json
{
  "reason": "Risk limit exceeded"
}
```

**Response**:
```json
{
  "status": "rejected",
  "intent_id": "loi_abc123",
  "rejected_at": "2026-07-05T12:01:00Z"
}
```

### POST /live/order-intents/{intent_id}/execute

Execute an approved order intent on OKX Testnet.

**Authentication**: Required

**Response**:
```json
{
  "status": "executed",
  "intent_id": "loi_abc123",
  "order_id": "okx_order_123",
  "executed_at": "2026-07-05T12:02:00Z"
}
```

---

## BitPro Integration

### GET /bitpro/health

Check BitPro MCP health and capabilities.

**Response**:
```json
{
  "status": "ok",
  "capabilities": [...],
  "tool_groups": ["market", "strategy", "backtest", "paper", "live_read"],
  "remote_mcp": true
}
```

### GET /bitpro/market/klines/{symbol}

Get BitPro K-line data.

**Path Parameters**:
- `symbol`: Symbol name

**Query Parameters**:
- `timeframe`: Timeframe (e.g., `1H`, `4H`)
- `limit`: Number of candles, default `100`

**Response**:
```json
{
  "symbol": "BTC",
  "timeframe": "1H",
  "klines": [...]
}
```

### GET /bitpro/paper/dashboard

Get BitPro paper trading dashboard.

**Query Parameters**:
- `strategy_id`: Filter by strategy ID (optional)

**Response**:
```json
{
  "running_strategies": [...],
  "alerts": [...],
  "data_gaps": []
}
```

### GET /bitpro/live/positions

Get BitPro live positions (read-only diagnostics).

**Query Parameters**:
- `exchange`: Exchange name, default `okx`
- `symbol`: Filter by symbol (optional)

**Response**:
```json
{
  "positions": [
    {
      "symbol": "BTC",
      "side": "long",
      "size": "0.5",
      "unrealized_pnl": "1000.0"
    }
  ]
}
```

---

## Monitoring & Alerts

### GET /monitors

List all monitor definitions.

**Response**:
```json
{
  "monitors": [
    {
      "monitor_id": "mon_bitpro_paper_all",
      "name": "BitPro Paper Monitor",
      "description": "Monitor all running BitPro paper strategies",
      "schedule": "*/5 * * * *",
      "enabled": true
    }
  ]
}
```

### POST /monitors/{monitor_id}/run

Manually run a monitor.

**Response**:
```json
{
  "monitor_id": "mon_bitpro_paper_all",
  "status": "completed",
  "alerts_generated": 2,
  "run_at": "2026-07-05T12:00:00Z"
}
```

### GET /alerts

List recent alerts.

**Query Parameters**:
- `severity`: Filter by severity (`info`, `warning`, `critical`) (optional)
- `limit`: Number of results, default `25`, max `100`

**Response**:
```json
{
  "alerts": [
    {
      "alert_id": "alert_123",
      "monitor_id": "mon_bitpro_paper_all",
      "severity": "warning",
      "message": "Strategy paper_momentum_v1 has high drawdown",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

---

## Connectors

### GET /connectors/capabilities

Get connector capabilities and tool metadata.

**Response**:
```json
{
  "connectors": [
    {
      "connector_id": "bitpro",
      "name": "BitPro MCP Adapter",
      "configured": true,
      "capabilities": [...],
      "tools": [...]
    }
  ]
}
```

---

## Evaluation Suite

### GET /evals/status

Get Agent evaluation suite status.

**Response**:
```json
{
  "total_evals": 15,
  "passing": 14,
  "failing": 1,
  "disabled": 0,
  "evals": [
    {
      "eval_id": "tool_choice_market_summary",
      "name": "Market summary tool selection",
      "status": "pass",
      "last_run": "2026-07-05T10:00:00Z"
    }
  ]
}
```

---

## World Model (Experimental)

### GET /world-model/snapshot

Get current world model state snapshot.

**Response**:
```json
{
  "timestamp": "2026-07-05T12:00:00Z",
  "market_state": {...},
  "portfolio": {...},
  "risk_metrics": {...}
}
```

### GET /world-model/portfolio

Get world model portfolio state.

**Response**:
```json
{
  "equity_usdt": "105000.0",
  "positions": [...],
  "risk_exposure": {...}
}
```

### GET /world-model/defensive-actions

List available defensive actions.

**Authentication**: Required

**Response**:
```json
{
  "actions": [
    {
      "action_id": "reduce_position_btc",
      "description": "Reduce BTC position by 50%",
      "risk_level": "medium",
      "conditions": [...]
    }
  ]
}
```

### GET /world-model/defensive-action-attempts

List defensive action execution attempts.

**Authentication**: Required

**Query Parameters**:
- `limit`: Number of results, default `25`

**Response**:
```json
{
  "attempts": [
    {
      "attempt_id": "att_123",
      "action_id": "reduce_position_btc",
      "status": "executed",
      "executed_at": "2026-07-05T11:00:00Z"
    }
  ]
}
```

### POST /world-model/defensive-actions/execute

Execute a defensive action.

**Authentication**: Required

**Request Body**:
```json
{
  "action_id": "reduce_position_btc",
  "idempotency_key": "key_123",
  "world_state": null
}
```

**Response**:
```json
{
  "status": "executed",
  "action_id": "reduce_position_btc",
  "executed_at": "2026-07-05T12:00:00Z",
  "result": {...}
}
```

---

## Error Responses

All error responses follow a consistent format:

**4xx Client Errors**:
```json
{
  "detail": "Error message"
}
```

**502 BitPro Unavailable**:
```json
{
  "detail": {
    "status": "unavailable",
    "service": "bitpro_mcp",
    "message": "Connection failed",
    "status_code": 502,
    "tool_calls": [...]
  }
}
```

**Common HTTP Status Codes**:
- `200`: Success
- `400`: Bad Request
- `401`: Not Authenticated
- `403`: Forbidden
- `404`: Not Found
- `502`: BitPro/External Service Unavailable
- `500`: Internal Server Error

---

## Rate Limiting

No rate limiting is currently enforced, but it's recommended to:
- Limit concurrent streaming runs to 5
- Space market data requests at least 1 second apart
- Use streaming endpoints for long-running Agent tasks

---

## WebSocket Support

WebSocket support is not currently implemented. Use the Server-Sent Events (SSE) streaming endpoint `/api/agent/runs/stream` for real-time updates.

---

## Versioning

API version: `0.1.0`

The API is in active development. Breaking changes will be announced in release notes.
