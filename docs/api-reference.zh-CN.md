# HyperTrade API 参考文档

## 概述

HyperTrade 提供全面的 REST API，用于 Agent 驱动的加密货币交易研究与执行。API 基于 FastAPI 构建，遵循 RESTful 规范。

**基础 URL**: `http://localhost:3334/api`  
**生产 URL**: `http://47.79.36.92:3333/api`

**API 文档**: 访问 `/docs` 查看交互式 Swagger 文档。

## 认证

大部分读取端点可公开访问。写入操作和特权操作需要管理员会话认证。

### POST /auth/login

认证并获取会话 Cookie。

**请求体**:
```json
{
  "username": "string",
  "password": "string"
}
```

**响应**:
```json
{
  "status": "ok",
  "username": "string"
}
```

**设置的 Cookie**: `hypertrade_session` (HttpOnly, SameSite=Lax)

### POST /auth/logout

清除会话 Cookie。

**认证**: 必需

**响应**:
```json
{
  "status": "ok"
}
```

### GET /auth/me

获取当前认证用户。

**认证**: 必需

**响应**:
```json
{
  "username": "string"
}
```

---

## 系统与控制台

### GET /health

健康检查端点。

**响应**:
```json
{
  "status": "ok",
  "service": "hypertrade-api"
}
```

### GET /harness/overview

完整的系统概览，包括提供者、工具、连接器、市场状态、最近运行、追踪事件和服务状态。

**响应**:
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

列出可用的聊天提供者及其配置。

**响应**:
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

切换活动的聊天提供者和模型。

**认证**: 必需

**请求体**:
```json
{
  "provider": "deepseek",
  "model": ""
}
```

**响应**:
```json
{
  "default_provider": "deepseek",
  "model": "",
  "providers": [...]
}
```

### GET /harness/tools

列出所有已注册的 Agent 工具及其策略。

**响应**:
```json
{
  "tools": [
    {
      "name": "market.summary",
      "description": "总结 OKX SWAP 市场状态。",
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

## Agent 运行

### POST /agent/runs

使用自由形式的提示创建新的 Agent 运行。

**请求体**:
```json
{
  "prompt": "看下目前市场的热度怎么样"
}
```

**响应**:
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

使用服务器发送事件（SSE）创建流式 Agent 运行。

**请求体**:
```json
{
  "prompt": "请做行情归纳"
}
```

**响应**: 服务器发送事件流

**事件类型**:
- `run_start`: 运行初始化
- `tool_start`: 工具执行开始
- `tool_complete`: 工具执行完成
- `run_complete`: 运行结束

**事件示例**:
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

列出最近的 Agent 运行（最新 25 条）。

**响应**:
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

获取特定运行的详细信息。

**响应**:
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

取消正在运行的 Agent 运行。

**认证**: 必需

**响应**:
```json
{
  "status": "cancelled",
  "run_id": "run_abc123"
}
```

---

## 市场数据

### GET /market/tickers/latest

获取所有 OKX SWAP 合约的最新市场行情。

**响应**:
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

获取特定币种的行情。

**路径参数**:
- `symbol`: 币种名称（如 `BTC`、`ETH`）或合约 ID（如 `BTC-USDT-SWAP`）

**响应**:
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

获取币种的 K线数据。

**路径参数**:
- `symbol`: 币种名称或合约 ID

**查询参数**:
- `bar`: 时间级别（如 `1H`、`4H`、`1D`），默认 `1H`
- `limit`: K线数量，默认 `100`，最大 `500`

**响应**:
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

比较多个币种的相对强度排名。

**请求体**:
```json
{
  "symbols": ["BTC", "ETH", "SOL"],
  "bar": "4H",
  "limit": 100
}
```

**响应**:
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

## RAG（检索增强生成）

### GET /rag/search

使用引用就绪的结果搜索知识文档。

**查询参数**:
- `query`: 搜索查询字符串（必需）
- `limit`: 结果数量，默认 `5`，最大 `20`

**响应**:
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

搜索或列出 Memory 项。

**查询参数**:
- `query`: 搜索查询（可选）
- `tag`: 按标签过滤（可选）
- `type`: 按类型过滤（`observation`、`strategy_knowledge`、`market_context`）（可选）
- `limit`: 结果数量，默认 `10`，最大 `50`

**响应**:
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

删除或禁用 Memory 项。

**认证**: 必需

**响应**:
```json
{
  "status": "deleted",
  "memory_id": "mem_abc123"
}
```

---

## 策略研究

### POST /strategy/research

创建新的策略研究记录。

**请求体**:
```json
{
  "prompt": "研究ETH趋势突破策略"
}
```

**响应**:
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

列出最近的策略研究记录。

**查询参数**:
- `limit`: 结果数量，默认 `10`，最大 `50`

**响应**:
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

创建包含多个变体的新策略实验。

**请求体**:
```json
{
  "prompt": "实验ETH动量突破策略的不同参数"
}
```

**响应**:
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

基于先前证据规划下一个实验。

**请求体**:
```json
{
  "prompt": "基于之前的动量策略证据，规划下一个实验"
}
```

**响应**:
```json
{
  "plan": "...",
  "prior_evidence": [...],
  "suggested_variants": [...]
}
```

### GET /strategy/experiments

列出最近的策略实验。

**响应**:
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

从 Memory 中获取汇总的策略库。

**查询参数**:
- `strategy_name`: 按策略名称过滤（可选）
- `tag`: 按标签过滤（可选）

**响应**:
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

## 回测

### POST /backtests

创建并运行回测。

**请求体**:
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

**响应**:
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

列出最近的回测。

**查询参数**:
- `limit`: 结果数量，默认 `10`，最大 `50`

**响应**:
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

## 模拟盘交易

### GET /paper/status

获取模拟盘交易状态和持仓。

**响应**:
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

控制模拟盘交易（暂停、恢复、平仓、重置）。

**认证**: 必需

**请求体**:
```json
{
  "action": "pause",
  "symbol": "BTC"
}
```

**操作**:
- `pause`: 暂停某个币种或所有交易
- `resume`: 恢复交易
- `close`: 平掉所有仓位
- `reset`: 重置到初始状态

**响应**:
```json
{
  "status": "ok",
  "action": "pause",
  "symbol": "BTC"
}
```

---

## 实盘订单意图

### POST /live/order-intents

创建实盘订单意图（执行前需要批准）。

**请求体**:
```json
{
  "symbol": "BTC",
  "side": "buy",
  "size": "0.01",
  "order_type": "market",
  "price": null,
  "reason": "API 冒烟测试"
}
```

**响应**:
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

列出实盘订单意图。

**响应**:
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

批准待处理的订单意图。

**认证**: 必需

**请求体**:
```json
{
  "reason": "已审核通过"
}
```

**响应**:
```json
{
  "status": "approved",
  "intent_id": "loi_abc123",
  "approved_at": "2026-07-05T12:01:00Z"
}
```

### POST /live/order-intents/{intent_id}/reject

拒绝待处理的订单意图。

**认证**: 必需

**请求体**:
```json
{
  "reason": "风险限额超标"
}
```

**响应**:
```json
{
  "status": "rejected",
  "intent_id": "loi_abc123",
  "rejected_at": "2026-07-05T12:01:00Z"
}
```

### POST /live/order-intents/{intent_id}/execute

在 OKX Testnet 上执行已批准的订单意图。

**认证**: 必需

**响应**:
```json
{
  "status": "executed",
  "intent_id": "loi_abc123",
  "order_id": "okx_order_123",
  "executed_at": "2026-07-05T12:02:00Z"
}
```

---

## BitPro 集成

### GET /bitpro/health

检查 BitPro MCP 健康状态和能力。

**响应**:
```json
{
  "status": "ok",
  "capabilities": [...],
  "tool_groups": ["market", "strategy", "backtest", "paper", "live_read"],
  "remote_mcp": true
}
```

### GET /bitpro/market/klines/{symbol}

获取 BitPro K线数据。

**路径参数**:
- `symbol`: 币种名称

**查询参数**:
- `timeframe`: 时间级别（如 `1H`、`4H`）
- `limit`: K线数量，默认 `100`

**响应**:
```json
{
  "symbol": "BTC",
  "timeframe": "1H",
  "klines": [...]
}
```

### GET /bitpro/paper/dashboard

获取 BitPro 模拟盘仪表板。

**查询参数**:
- `strategy_id`: 按策略 ID 过滤（可选）

**响应**:
```json
{
  "running_strategies": [...],
  "alerts": [...],
  "data_gaps": []
}
```

### GET /bitpro/live/positions

获取 BitPro 实盘持仓（只读诊断）。

**查询参数**:
- `exchange`: 交易所名称，默认 `okx`
- `symbol`: 按币种过滤（可选）

**响应**:
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

## 监控与告警

### GET /monitors

列出所有监控器定义。

**响应**:
```json
{
  "monitors": [
    {
      "monitor_id": "mon_bitpro_paper_all",
      "name": "BitPro 模拟盘监控",
      "description": "监控所有运行中的 BitPro 模拟盘策略",
      "schedule": "*/5 * * * *",
      "enabled": true
    }
  ]
}
```

### POST /monitors/{monitor_id}/run

手动运行监控器。

**响应**:
```json
{
  "monitor_id": "mon_bitpro_paper_all",
  "status": "completed",
  "alerts_generated": 2,
  "run_at": "2026-07-05T12:00:00Z"
}
```

### GET /alerts

列出最近的告警。

**查询参数**:
- `severity`: 按严重性过滤（`info`、`warning`、`critical`）（可选）
- `limit`: 结果数量，默认 `25`，最大 `100`

**响应**:
```json
{
  "alerts": [
    {
      "alert_id": "alert_123",
      "monitor_id": "mon_bitpro_paper_all",
      "severity": "warning",
      "message": "策略 paper_momentum_v1 回撤过大",
      "created_at": "2026-07-05T12:00:00Z"
    }
  ]
}
```

---

## 连接器

### GET /connectors/capabilities

获取连接器能力和工具元数据。

**响应**:
```json
{
  "connectors": [
    {
      "connector_id": "bitpro",
      "name": "BitPro MCP 适配器",
      "configured": true,
      "capabilities": [...],
      "tools": [...]
    }
  ]
}
```

---

## 评估套件

### GET /evals/status

获取 Agent 评估套件状态。

**响应**:
```json
{
  "total_evals": 15,
  "passing": 14,
  "failing": 1,
  "disabled": 0,
  "evals": [
    {
      "eval_id": "tool_choice_market_summary",
      "name": "市场摘要工具选择",
      "status": "pass",
      "last_run": "2026-07-05T10:00:00Z"
    }
  ]
}
```

---

## 世界模型（实验性）

### GET /world-model/snapshot

获取当前世界模型状态快照。

**响应**:
```json
{
  "timestamp": "2026-07-05T12:00:00Z",
  "market_state": {...},
  "portfolio": {...},
  "risk_metrics": {...}
}
```

### GET /world-model/portfolio

获取世界模型投资组合状态。

**响应**:
```json
{
  "equity_usdt": "105000.0",
  "positions": [...],
  "risk_exposure": {...}
}
```

### GET /world-model/defensive-actions

列出可用的防御性操作。

**认证**: 必需

**响应**:
```json
{
  "actions": [
    {
      "action_id": "reduce_position_btc",
      "description": "将 BTC 仓位减少 50%",
      "risk_level": "medium",
      "conditions": [...]
    }
  ]
}
```

### GET /world-model/defensive-action-attempts

列出防御性操作执行尝试。

**认证**: 必需

**查询参数**:
- `limit`: 结果数量，默认 `25`

**响应**:
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

执行防御性操作。

**认证**: 必需

**请求体**:
```json
{
  "action_id": "reduce_position_btc",
  "idempotency_key": "key_123",
  "world_state": null
}
```

**响应**:
```json
{
  "status": "executed",
  "action_id": "reduce_position_btc",
  "executed_at": "2026-07-05T12:00:00Z",
  "result": {...}
}
```

---

## 错误响应

所有错误响应遵循一致的格式：

**4xx 客户端错误**:
```json
{
  "detail": "错误信息"
}
```

**502 BitPro 不可用**:
```json
{
  "detail": {
    "status": "unavailable",
    "service": "bitpro_mcp",
    "message": "连接失败",
    "status_code": 502,
    "tool_calls": [...]
  }
}
```

**常见 HTTP 状态码**:
- `200`: 成功
- `400`: 请求错误
- `401`: 未认证
- `403`: 禁止访问
- `404`: 未找到
- `502`: BitPro/外部服务不可用
- `500`: 内部服务器错误

---

## 速率限制

当前未强制执行速率限制，但建议：
- 限制并发流式运行到 5 个
- 市场数据请求间隔至少 1 秒
- 对长时间运行的 Agent 任务使用流式端点

---

## WebSocket 支持

WebSocket 支持尚未实现。使用服务器发送事件（SSE）流式端点 `/api/agent/runs/stream` 获取实时更新。

---

## 版本控制

API 版本: `0.1.0`

API 正在积极开发中。破坏性更改将在发布说明中公布。
