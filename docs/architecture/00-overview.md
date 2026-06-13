# 00 Overview / 总览

## English

HyperTrade separates the development harness from the trading agent runtime.

- Development harness: `AGENTS.md`, `docs/spec.md`, `docs/contracts`, `docs/progress.md`, `docs/qa`, and `scripts/check.sh`.
- Agent harness: ProviderRuntime, ToolRegistry, AgentKernel, RAG, Memory, Trace, and approval gates.
- Trading domain: OKX market ingestion, BitPro MCP/API adapters, market summaries, paper trading, strategy experiments, strategy knowledge memory, backtesting, and Testnet/live order intent.

Current V1 is production-oriented: HyperTrade keeps Agent planning, trace,
Memory, RAG, approval gates, and reporting, while BitPro remains an external
trading-system provider reached only through stable MCP/API contracts.

## 中文

HyperTrade 分成两层：

- 开发 Harness：`AGENTS.md`、`docs/spec.md`、`docs/contracts`、`docs/progress.md`、`docs/qa`、`scripts/check.sh`。
- Agent Harness：ProviderRuntime、ToolRegistry、AgentKernel、RAG、Memory、Trace、审批门禁。
- 交易领域：OKX 行情采集、BitPro MCP/API 适配、行情归纳、模拟盘、策略实验、策略知识记忆、回测、Testnet/实盘订单意图。

当前 V1 是生产导向的 Agent 能力：HyperTrade 负责规划、trace、Memory、RAG、审批门和报告；BitPro 作为外部交易系统能力提供方，只能通过稳定 MCP/API 合同访问。
