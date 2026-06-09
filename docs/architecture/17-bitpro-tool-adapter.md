# 17 BitPro Tool Adapter / BitPro 工具适配

## English

BitPro can act as an external capability provider for HyperTrade Agent tools. HyperTrade must keep the boundary explicit: Agent planning happens in HyperTrade, tool execution is audited in HyperTrade, and BitPro is called through stable APIs for data and state.

The adapter should start read-first:

- `bitpro.capabilities`: supported API versions, tool names, permission scopes, disabled features, and environment.
- `bitpro.health`: upstream health, data freshness, degraded sources, and server version.
- `bitpro.market_reference`: instruments, contract metadata, limits, fees, funding, and source freshness.
- `bitpro.market_data`: tickers, candles, order book snapshots, trades, funding rates, and open interest.
- `bitpro.backtest_data`: available datasets and candle windows for local HyperTrade backtests.
- `bitpro.backtest_artifacts`: BitPro-owned backtest status, metrics, equity curve, trades, orders, fills, and reports when BitPro owns the run.
- `bitpro.paper_state`: paper sessions, balances, positions, orders, fills, events, and strategy links.
- `bitpro.live_state`: live balances, positions, open orders, order history, fills, subscriptions, and exposure.
- `bitpro.audit`: request/run/tool correlation, append-only events, and redacted exchange metadata.

Write tools must be added later and separately from read tools. Any paper, testnet, or live write path needs explicit scopes, idempotency keys, approval gates, risk prechecks, redacted audit events, and structured refusal reasons.

## 中文

BitPro 可以作为 HyperTrade Agent 工具的外部能力提供方。边界必须清晰：Agent 规划在 HyperTrade，工具执行审计在 HyperTrade，BitPro 只通过稳定 API 提供数据和状态。

适配器应先从只读能力开始：

- `bitpro.capabilities`：API 版本、工具名、权限 scope、禁用能力、环境。
- `bitpro.health`：上游健康、数据新鲜度、降级来源、服务版本。
- `bitpro.market_reference`：合约元数据、交易限制、手续费、资金费率、数据新鲜度。
- `bitpro.market_data`：ticker、K 线、盘口快照、成交、资金费率、持仓量。
- `bitpro.backtest_data`：可用数据集和 K 线窗口，供 HyperTrade 本地回测使用。
- `bitpro.backtest_artifacts`：当 BitPro 负责回测执行时，读取状态、指标、权益曲线、成交、订单、成交明细和报告。
- `bitpro.paper_state`：模拟盘 session、余额、持仓、订单、成交、事件和策略关联。
- `bitpro.live_state`：实盘余额、持仓、挂单、历史订单、成交、订阅和风险暴露。
- `bitpro.audit`：request/run/tool 关联、追加式事件和脱敏交易所元数据。

写工具应在只读工具稳定后单独加入。任何模拟盘、Testnet 或实盘写入路径都必须具备明确 scope、幂等键、审批门、风控预检、脱敏审计事件和结构化拒绝原因。
