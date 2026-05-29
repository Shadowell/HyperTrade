# 04 Tool Calling / 工具调用

## English

ToolRegistry is the single catalog for agent-callable tools. Sprint 01 tools are market summary, ticker reads, RAG search, memory write/search, strategy/backtest/paper placeholders, and live order intent.

Policy:

- non-live tools can run automatically from chat
- live order intent requires approval
- every tool call must create a trace event
- large outputs should be summarized before entering model context

Specific ticker lookup:

- `market_summary` is for all-market OKX SWAP summaries and top movers.
- `market_ticker` is for one listed OKX USDT perpetual swap symbol or instrument id.
- `market_candles` is for recent OHLCV trend research on one OKX SWAP instrument.
- `market_compare` is for comparing relative strength across 2-6 OKX SWAP instruments.
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

- 非实盘工具可由聊天自动触发
- 实盘订单意图必须审批
- 每次工具调用必须生成 trace event
- 大结果进入模型上下文前要摘要

单标的精确行情：

- `market_summary` 用于 OKX SWAP 全市场归纳和异动榜。
- `market_ticker` 用于一个已上线 OKX USDT 永续标的或 instrument id。
- `market_candles` 用于一个 OKX SWAP 标的的近期 OHLCV 趋势研究。
- `market_compare` 用于 2-6 个 OKX SWAP 标的之间的强弱比较。
- 常见输入会归一化为 OKX instrument id：`eth` -> `ETH-USDT-SWAP`，
  `SOL-USDT` -> `SOL-USDT-SWAP`，`doge_usdt` -> `DOGE-USDT-SWAP`。
- planner prompt 明确要求：用户问任意具体币种时使用 `market_ticker`，不是只支持 BTC。
- planner prompt 明确要求：用户问走势、K线、突破、回调、支撑阻力、多周期研究时使用
  `market_candles`。
- planner prompt 明确要求：用户问相对强弱、哪个更强、跑赢、强弱排名时使用
  `market_compare`。
