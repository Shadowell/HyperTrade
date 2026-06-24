# 04 Tool Calling / 工具调用

## English

ToolRegistry is the single catalog for agent-callable tools. Sprint 01 tools are market summary, ticker reads, RAG search, memory write/search, strategy/backtest/paper placeholders, and live order intent.

Policy:

- every registered tool has `ToolPolicy` metadata: scope, approval,
  idempotency, source of truth, timeout class, safe sample limit, and failure
  behavior
- the trusted runtime evaluates policy before execution and stores the policy
  decision in `graph.approval_check`, `graph.execute_tool`, and business trace
  payloads
- read tools can run automatically from chat; approval-required or blocked
  tools are surfaced through structured policy outcomes instead of hidden
  planner behavior
- free-form natural-language prompts do not use kernel keyword routers; a
  configured chat provider and `AgentPlanner` select tool names, while the
  trusted runtime only validates and executes the selected calls
- idempotency-required tools must supply an idempotency key before execution
- large outputs should be summarized before entering model context
- external BitPro calls must go through explicit adapter tools with scopes, idempotency, and audit correlation
- tool timeout overruns and execution exceptions return structured
  `status=unavailable` payloads with `missing_data` notes so reports do not
  collapse into opaque stack traces
- admin-authenticated `POST /api/agent/runs/{run_id}/cancel` persists
  `status=canceled`; an in-flight run checks cancellation at the next tool
  boundary

Specific ticker lookup:

- `market_summary` is for all-market OKX SWAP summaries and top movers.
- The planner should choose `market_summary` for all-market heat, sentiment,
  breadth, risk-appetite, 大盘, 全市场, or 行情归纳 prompts, not a few
  `market_ticker` calls.
- `market_ticker` is for one listed OKX USDT perpetual swap symbol or instrument id.
- `market_candles` is for recent OHLCV trend research on one OKX SWAP instrument.
- `market_compare` is for comparing relative strength across 2-6 OKX SWAP instruments.
- `bitpro.*` tools are reserved for external BitPro API capabilities such as backtest data, base market data, paper/simulation state, and live trading state.
- The planner should choose `bitpro_live_order_history` /
  `bitpro.live_order_history` for live account order-history prompts such as
  `我的实盘最近的一笔订单是什么`, not `market_summary`. This tool is read-only
  live diagnostics; live order placement, cancellation, and transfer remain
  separate write-gated paths.
- The planner should choose `bitpro_live_strategy_performance` /
  `bitpro.live_strategy_performance` for live strategy performance prompts such
  as `看下实盘收益最高的策略`, not `market_summary`. The tool reads BitPro
  `/live/strategies`, ranks by `return_pct`, and reports `total_pnl` only when
  BitPro provides it.
- Common user inputs are normalized to OKX instrument ids: `eth` -> `ETH-USDT-SWAP`,
  `SOL-USDT` -> `SOL-USDT-SWAP`, `doge_usdt` -> `DOGE-USDT-SWAP`.
- The planner prompt instructs the LLM to choose `market_ticker` for any specific listed coin, not
  only BTC examples.
- The planner prompt instructs the LLM to choose `market_candles` for trend, K-line, breakthrough,
  pullback, support/resistance, or multi-period research prompts.
- The planner prompt instructs the LLM to choose `market_compare` for relative-strength prompts such
  as "比较 ETH 和 SOL 哪个更强".

## 中文

ToolRegistry 是 Agent 可调用工具的唯一目录。Sprint 01 包含行情归纳、ticker 读取、RAG 搜索、Memory 写入/搜索，以及策略、回测、模拟盘、实盘订单意图的扩展位。

策略：

- 每个注册工具都有 `ToolPolicy` 元数据：scope、approval、idempotency、
  source of truth、timeout class、safe sample limit 和 failure behavior
- 可信运行时在执行前评估 policy，并把决策写入 `graph.approval_check`、
  `graph.execute_tool` 和业务 trace payload
- 只读工具可由聊天自动触发；需要审批或被阻断的工具会以结构化 policy outcome
  展示，而不是隐藏在 planner 行为里
- 自然语言提示不再由 kernel 里的关键词路由决定工具；配置好的 chat provider 和
  `AgentPlanner` 负责选择工具名，可信运行时只做校验、执行和审计
- 要求幂等的工具必须携带 idempotency key 才能执行
- 每次工具调用必须生成 trace event
- 大结果进入模型上下文前要摘要
- 外部 BitPro 调用必须通过显式 adapter tool，并带有权限 scope、幂等和审计关联
- 工具超时和执行异常会返回结构化 `status=unavailable` payload，并带
  `missing_data`，报告不会退化成不透明异常字符串
- 管理员可通过 `POST /api/agent/runs/{run_id}/cancel` 持久化取消状态；
  运行中的 Agent 会在下一次工具边界检查取消状态

单标的精确行情：

- `market_summary` 用于 OKX SWAP 全市场归纳和异动榜。
- 全市场热度、市场情绪、breadth、风险偏好、大盘、全市场或行情归纳类问题应由
  planner 选择 `market_summary`，不能只用几个 `market_ticker` 调用替代。
- `market_ticker` 用于一个已上线 OKX USDT 永续标的或 instrument id。
- `market_candles` 用于一个 OKX SWAP 标的的近期 OHLCV 趋势研究。
- `market_compare` 用于 2-6 个 OKX SWAP 标的之间的强弱比较。
- `bitpro.*` 工具预留给外部 BitPro API 能力，例如回测数据、基础行情、模拟盘状态和实盘状态。
- `我的实盘最近的一笔订单是什么` 这类实盘订单历史问题应由 planner 选择
  `bitpro_live_order_history` / `bitpro.live_order_history`，不能回退到
  `market_summary`。该工具只是实盘只读诊断；真实下单、撤单和划转仍属于
  单独写入门禁路径。
- `看下实盘收益最高的策略` 这类实盘策略收益问题应由 planner 选择
  `bitpro_live_strategy_performance` / `bitpro.live_strategy_performance`，
  不能回退到 `market_summary`。该工具读取 BitPro `/live/strategies`，按
  `return_pct` 排名，并且只展示 BitPro 返回的 `total_pnl`。
- 常见输入会归一化为 OKX instrument id：`eth` -> `ETH-USDT-SWAP`，
  `SOL-USDT` -> `SOL-USDT-SWAP`，`doge_usdt` -> `DOGE-USDT-SWAP`。
- planner prompt 明确要求：用户问任意具体币种时使用 `market_ticker`，不是只支持 BTC。
- planner prompt 明确要求：用户问走势、K线、突破、回调、支撑阻力、多周期研究时使用
  `market_candles`。
- planner prompt 明确要求：用户问相对强弱、哪个更强、跑赢、强弱排名时使用
  `market_compare`。
