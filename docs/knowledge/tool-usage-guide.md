# HyperTrade 工具运维指南

这份文档用于操作和验证 HyperTrade 的 Agent 工具链。它不是交易建议，也不包含任何密钥。

## 1. Agent Graph

用途：验证一次自由对话如何变成工具调用、审计 trace 和最终报告。

入口：

```bash
hypertrade ask "看下ETH行情"
```

远程服务器：

```bash
hypertrade --remote http://127.0.0.1:3334 ask "看下ETH行情"
```

你应该观察：

- `Agent status: run created`
- `planning next tool call`
- `executing tool ...`
- `generating final report`
- trace 里的 `graph.intent_classify`、`graph.plan_tools`、`graph.approval_check`、`graph.execute_tool`、`graph.reflect`、`graph.final_report`
- 普通行情、RAG、Memory 输出不应反复追加固定免责声明；策略、回测、Testnet、实盘订单或类似建议的语境仍应说明研究/风险边界。

相关代码：

- `backend/src/hypertrade/agent/kernel.py`
- `backend/src/hypertrade/agent/planner.py`

## 2. Tool Call

用途：让模型只选择工具名和 JSON 参数，由可信 Python 代码执行真实操作。

查看工具目录：

```bash
hypertrade
/tools
```

常用工具路径：

- 行情摘要：`market_summary`
- 单标的价格：`market_ticker`
- K 线趋势：`market_candles`
- 强弱对比：`market_compare`
- 知识检索：`rag_search`
- 记忆写入/搜索：`memory_write`、`memory_search`
- 策略研究：`strategy_draft`
- 回测：`backtest_run`
- live/testnet 意图：`live_order_intent`

相关代码：

- `backend/src/hypertrade/tools/registry.py`
- `backend/src/hypertrade/agent/kernel.py`

## 3. Provider Router

用途：切换不同 Chat Provider，但不把密钥暴露给 API、CLI 或前端。

查看当前模型：

```bash
hypertrade
/model
```

切换 provider：

```bash
/model deepseek
/model openrouter
/model qwen
```

注意：

- DeepSeek 是默认 provider。
- provider 切换只影响 chat/planner，不影响 embedding provider。
- 没有 key 的 provider 会显示 missing，但系统会保留 deterministic fallback。

相关代码：

- `backend/src/hypertrade/providers/runtime.py`
- `backend/src/hypertrade/providers/chat.py`

## 4. RAG

用途：从 `docs/knowledge` 的 Markdown 文件检索上下文，并在报告里显示引用来源。

命令：

```bash
hypertrade
/rag 风控
```

API：

```bash
curl -sS "http://127.0.0.1:3334/api/rag/search?query=风控"
```

你应该观察：

- `source_path`
- `title`
- `chunk_index`
- `score`
- `content preview`

当前本地测试使用 deterministic embedding fallback；这让 `./scripts/check.sh` 不依赖 Qwen key。

相关代码：

- `backend/src/hypertrade/rag/service.py`
- `docs/knowledge/rag-usage.md`

## 5. Memory

用途：保存 Agent 运行中产生的可审计长期记忆。

命令：

```bash
hypertrade
/memory
/memory search risk
/memory disable mem_xxx
```

Memory 和 RAG 的区别：

- RAG 读取你维护的知识文档。
- Memory 保存运行时产生的观察、偏好、策略教训、风险提醒。
- Memory item 可以追溯 `source_run_id` 和 `source_tool`。

相关代码：

- `backend/src/hypertrade/memory/service.py`
- `docs/knowledge/memory-policy.md`

## 6. Market Tools

用途：在不等待 LLM 规划的情况下直接验证行情工具。

命令：

```bash
/price ETH
/candles ETH --bar 1H --limit 100
/compare ETH SOL --bar 4H --limit 100
```

这些命令适合验证：

- symbol normalization：`ETH` -> `ETH-USDT-SWAP`
- OKX REST 数据读取
- candle trend feature
- relative strength ranking

相关代码：

- `backend/src/hypertrade/market/client.py`
- `backend/src/hypertrade/market/analysis.py`
- `backend/src/hypertrade/market/repository.py`

## 7. Strategy Research and Backtest

用途：把策略想法变成研究记录、回测记录和改进建议。

命令：

```bash
/research 研究ETH趋势突破
/backtest --live --symbol ETH --bar 1H --limit 100
/backtest --source bitpro_mcp --symbol ETH --bar 1H --limit 200
/experiment 研究ETH趋势突破并给出回测改进建议
```

你应该观察：

- research id：`srch_*`
- backtest id：`bt_*`
- experiment id：`exp_*`
- data source、bar、candle_count、trade summary、risk notes

相关代码：

- `backend/src/hypertrade/strategy/service.py`
- `backend/src/hypertrade/backtest/service.py`
- `backend/src/hypertrade/strategy/experiment.py`

## 8. BitPro MCP Lifecycle Adapter

用途：通过 BitPro MCP/API 合同读取外部数据，并编排策略生成、策略创建、BitPro 回测 job 和模拟盘生命周期；不直接访问 BitPro 数据库，也不复制 BitPro 业务逻辑。

Agent 示例：

```bash
hypertrade ask "用 BitPro MCP 读取 ETH 1H K线"
hypertrade ask "用 BitPro skills 开发 ETH 趋势突破策略，回测并启动模拟盘验证"
hypertrade ask "查看 BitPro 回测收益大于100%的策略有哪些"
```

API：

```bash
curl -sS http://127.0.0.1:3334/api/bitpro/health
curl -sS "http://127.0.0.1:3334/api/bitpro/market/klines/ETH?timeframe=1h&limit=200"
curl -sS http://127.0.0.1:3334/api/bitpro/paper/dashboard
curl -sS "http://127.0.0.1:3334/api/bitpro/live/positions?symbol=ETH"
```

你应该观察：

- 每条数据链路先出现 `bitpro_capabilities` 和 `bitpro_health`。
- Agent trace 里有 `bitpro.capabilities`、`bitpro.health`、`bitpro.market_klines`。
- 策略生命周期 trace 里有 `bitpro.strategy_generate`、`bitpro.strategy_create`、`bitpro.strategy_update`、`bitpro.backtest_start_job`、`bitpro.backtest_get_job`、`bitpro.paper_configure` 或 `bitpro.paper_start`。
- 回测收益排行或阈值问题 trace 里应有 `bitpro.backtest_list_results`，报告口径应写 `total_return_pct`，不能把 `annual_return_pct` 当成回测总收益。
- `/harness` 的 BitPro MCP 面板显示 `mcp_non_live_lifecycle`、API base、token 是否配置和实盘写关闭状态。
- `BITPRO_MCP_API_TOKEN` 只在服务器环境配置，不能放进前端或仓库。
- `live_promote`、真实下单、撤单、划转等实盘写工具仍然不应被调用。

相关代码：

- `backend/src/hypertrade/bitpro/mcp.py`
- `backend/src/hypertrade/agent/kernel.py`
- `docs/runbooks/bitpro-mcp-data-access.md`

## 9. Paper Trading

用途：验证自动模拟盘状态和生命周期控制。

命令：

```bash
/paper status
/paper pause
/paper resume
/paper close ETH
/paper reset
```

相关代码：

- `backend/src/hypertrade/paper/service.py`
- `backend/src/hypertrade/paper/engine.py`

## 10. Risk and OKX Testnet Execution

用途：验证审批门、风控门和 Testnet signed order execution。

创建意图：

```bash
/live intent ETH buy 0.01 --reason ops smoke
```

审批：

```bash
/live approve loi_xxx --reason checked
```

执行 Testnet：

```bash
/live execute loi_xxx
```

重要边界：

- Mainnet execution 永远 blocked。
- 创建、审批、执行前都会跑 RiskEngine。
- 执行审计只保存 redacted request，不保存 secret。
- 真实 Testnet 下单前先读 `docs/runbooks/okx-testnet-order-smoke.md`。

相关代码：

- `backend/src/hypertrade/risk/service.py`
- `backend/src/hypertrade/live/service.py`
- `backend/src/hypertrade/live/okx.py`

## 11. Frontend Harness

用途：用页面观察 Agent 运行状态、工具审计和风险边界。

入口：

```text
http://47.79.36.92:3333/harness
```

核心区域：

- Provider 状态和切换
- Tool catalog
- Agent run 和 graph trace
- RAG search
- Memory manager
- Market shortcuts
- Paper runtime
- Strategy Lab
- Live Approval
- Eval status

相关代码：

- `frontend/src/App.tsx`
- `backend/src/hypertrade/main.py`

## 12. Tests and Eval

统一检查：

```bash
./scripts/check.sh
```

常用定向测试：

```bash
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_api.py -q
uv run pytest tests/test_agent_acceptance.py -q
```

Eval 命令：

```bash
hypertrade
/evals
```

相关文档：

- `docs/testing/agent-acceptance-test-plan.md`
- `docs/testing/agent-eval-suite.md`

## 13. Deployment Smoke

服务器本地检查：

```bash
curl -sS http://127.0.0.1:3334/api/health
curl -sS http://127.0.0.1:3333/api/health
cat /opt/hypertrade/deploy/last_deployed_sha
```

相关文档：

- `docs/runbooks/deployment-smoke.md`
- `docs/runbooks/incident-response.md`
- `docs/runbooks/postgres-backup-restore.md`
