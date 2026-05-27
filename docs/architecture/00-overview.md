# 00 Overview / 总览

## English

HyperTrade separates the development harness from the trading agent runtime.

- Development harness: `AGENTS.md`, `docs/spec.md`, `docs/contracts`, `docs/progress.md`, `docs/qa`, and `scripts/check.sh`.
- Agent harness: ProviderRuntime, ToolRegistry, AgentKernel, RAG, Memory, Trace, and approval gates.
- Trading domain: OKX market ingestion, market summaries, later paper trading, backtesting, and Testnet/live order intent.

Sprint 01 implements the smallest complete agent loop: market data enters PostgreSQL, the user asks for a summary, the AgentKernel calls tools, and `/harness` shows what happened.

## 中文

HyperTrade 分成两层：

- 开发 Harness：`AGENTS.md`、`docs/spec.md`、`docs/contracts`、`docs/progress.md`、`docs/qa`、`scripts/check.sh`。
- Agent Harness：ProviderRuntime、ToolRegistry、AgentKernel、RAG、Memory、Trace、审批门禁。
- 交易领域：OKX 行情采集、行情归纳，后续扩展模拟盘、回测、Testnet/实盘订单意图。

Sprint 01 的目标是最小完整闭环：行情进入 PostgreSQL，用户发起归纳，AgentKernel 调用工具，`/harness` 展示运行过程。

