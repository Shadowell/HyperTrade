# 17 BitPro Tool Adapter / BitPro 工具适配

## English

BitPro can act as an external capability provider for HyperTrade Agent tools. HyperTrade must keep the boundary explicit: Agent planning happens in HyperTrade, tool execution is audited in HyperTrade, and BitPro is called through stable APIs for data and state.

The target split is:

- BitPro is the base trading-system platform. It owns market/reference data, strategy records, `BaseStrategy` runtime contracts, backtest execution, performance artifacts, paper/simulation instances, and future live execution.
- HyperTrade is the Agent control plane. It improves the operator's Agent capability by planning research, selecting tools, writing candidate strategies, validating code, triggering BitPro-owned backtests, reading evidence, and promoting only passing strategies to paper simulation.
- The integration boundary is MCP/API only. HyperTrade never reads BitPro databases directly for this lifecycle, never writes `backend/app/strategies/*.py`, never copies BitPro trading logic, and never restarts BitPro to make a strategy usable.

The adapter starts from read-first discovery and then permits non-live strategy lifecycle tools:

- `bitpro.capabilities`: supported API versions, tool names, permission scopes, disabled features, and environment.
- `bitpro.health`: upstream health, data freshness, degraded sources, and server version.
- `bitpro.market_reference`: instruments, contract metadata, limits, fees, funding, and source freshness.
- `bitpro.market_data`: tickers, candles, order book snapshots, trades, funding rates, and open interest.
- `bitpro.backtest_data`: available datasets and candle windows for local HyperTrade backtests.
- `bitpro.backtest_artifacts`: BitPro-owned backtest status, metrics, equity curve, trades, orders, fills, and reports when BitPro owns the run.
- `bitpro.paper_state`: paper sessions, balances, positions, orders, fills, events, and strategy links.
- `bitpro.live_state`: live balances, positions, open orders, order history, fills, subscriptions, and exposure.
- `bitpro.audit`: request/run/tool correlation, append-only events, and redacted exchange metadata.

Research/backtest/paper writes are allowed only through explicit Agent tool calls such as strategy generation, strategy creation, BitPro-owned backtest jobs, and paper/simulation lifecycle control. Live write tools must be added later and separately. Any testnet or live write path needs explicit scopes, idempotency keys, approval gates, risk prechecks, redacted audit events, and structured refusal reasons.

The production strategy R&D loop is:

1. Call `bitpro_capabilities`, then `bitpro_health`.
2. Confirm real K-line coverage with `market_klines` before strategy generation. If coverage is missing, use data sync diagnostics or shrink the range; never synthesize OHLCV.
3. Write or generate a single `BaseStrategy` subclass and validate it with `strategy_validate_code` before persistence.
4. Save the strategy through `strategy_create(script_content=...)` as a DB-backed dynamic strategy with `strategy_source=db_script` and `script_content_source=db`.
5. Use `strategy_update` for follow-up metadata fixes such as canonical BitPro naming, descriptions, config patches, or DB-backed code replacement after validation.
6. Start the BitPro-owned backtest with `backtest_start_job`, poll `backtest_get_job`, then inspect `backtest_list_results` and `backtest_get_result`.
7. Iterate only from real backtest evidence. Candidate acceptance gates should be explicit, for example minimum trade count, positive return, and bounded drawdown.
8. Only after passing the gate, configure and start paper simulation with `paper_configure` and `paper_start`.
9. Skip all live mutation tools unless the human explicitly supplies the required live-risk confirmation fields.

Server evidence on 2026-06-09 validated this loop through BitPro MCP against `http://127.0.0.1:8889/api/v2`: ETH/USDT:USDT 1h had 720 real candles from 2026-05-10T14:00:00Z to 2026-06-09T13:00:00Z; strategy `#293` passed `strategy_validate_code`; backtest job `a292d098-0657-411d-9fff-3c82b9b384d8` completed with result `#196`; metrics were 4.0441% return, 1.4438% max drawdown, 11 trades, 0.8029 Sharpe, and 63.64% win rate; paper simulation for strategy `#293` was started in dry-run mode. Live mutation tools were skipped.

Operational data-access steps are documented in `docs/runbooks/bitpro-mcp-data-access.md`. The first HyperTrade implementation lives in `backend/src/hypertrade/bitpro/mcp.py`: every flow starts with `bitpro_capabilities` and `bitpro_health`, then selects the smallest tool for market data, strategy lifecycle, backtest, paper/simulation, or live read-only diagnostics. Live write tools are blocked in this adapter.

The BitPro `/live/dashboard` response is treated as a current paper engine/dashboard view, not proof that only one strategy is running. When HyperTrade calls `bitpro_paper_dashboard` without a `strategy_id`, the adapter also reads `strategy_search(status=running)` with safe pagination and returns `paper_scope` plus `running_strategies`. Reports must distinguish the current dashboard strategy from the complete running strategy inventory exposed by BitPro.

BitPro backtest ranking and threshold questions are answered through
`bitpro_backtest_list_results`, not by reading strategy descriptions or planner
memory. The adapter uses BitPro `offset`/`limit` pagination, normalizes the
actual result metric as `total_return_pct`, optionally filters it locally, and
enriches rows with `strategy_get` names for page parity. Annualized return is
reported as a separate field and must not be substituted for total backtest
return.

Specific backtest evidence questions are answered through
`bitpro_backtest_get_result`. The adapter preflights the same
`bitpro_capabilities` -> `bitpro_health` sequence, reads the BitPro-owned result
detail, normalizes metrics, and exposes bounded samples for equity curve, trades,
orders, fills, and drawdown series. Missing artifacts are reported as unavailable;
HyperTrade never synthesizes artifact rows.

For containerized deployments, BitPro MCP is reached through an explicit host-gateway address instead of `127.0.0.1`, because loopback inside `hypertrade-api` points to the container itself. If BitPro is unavailable, API endpoints return a structured `502` with the failed BitPro tool calls so operators can distinguish upstream outage from HyperTrade runtime failure.

## 中文

BitPro 可以作为 HyperTrade Agent 工具的外部能力提供方。边界必须清晰：Agent 规划在 HyperTrade，工具执行审计在 HyperTrade，BitPro 只通过稳定 API 提供数据和状态。

目标分层：

- BitPro 是基础交易系统平台，负责行情/基础数据、策略记录、`BaseStrategy` 运行合同、回测执行、绩效结果、模拟盘实例和未来实盘执行。
- HyperTrade 是 Agent 控制平面，通过规划研发、选择工具、编写候选策略、校验代码、触发 BitPro 回测、读取证据，以及只把通过门禁的策略推进到模拟盘，来提升操作者的 Agent 能力。
- 集成边界只允许 MCP/API。该生命周期中 HyperTrade 不直接读 BitPro 数据库，不写 `backend/app/strategies/*.py`，不复制 BitPro 交易逻辑，也不通过重启 BitPro 让策略生效。

适配器从只读发现开始，并允许非实盘策略生命周期工具：

- `bitpro.capabilities`：API 版本、工具名、权限 scope、禁用能力、环境。
- `bitpro.health`：上游健康、数据新鲜度、降级来源、服务版本。
- `bitpro.market_reference`：合约元数据、交易限制、手续费、资金费率、数据新鲜度。
- `bitpro.market_data`：ticker、K 线、盘口快照、成交、资金费率、持仓量。
- `bitpro.backtest_data`：可用数据集和 K 线窗口，供 HyperTrade 本地回测使用。
- `bitpro.backtest_artifacts`：当 BitPro 负责回测执行时，读取状态、指标、权益曲线、成交、订单、成交明细和报告。
- `bitpro.paper_state`：模拟盘 session、余额、持仓、订单、成交、事件和策略关联。
- `bitpro.live_state`：实盘余额、持仓、挂单、历史订单、成交、订阅和风险暴露。
- `bitpro.audit`：request/run/tool 关联、追加式事件和脱敏交易所元数据。

研究、回测、模拟盘写入只允许通过明确 Agent 工具调用执行，例如策略生成、策略创建、BitPro 回测 job 和 paper/simulation 生命周期控制。实盘写工具必须后续单独加入。任何 Testnet 或实盘写入路径都必须具备明确 scope、幂等键、审批门、风控预检、脱敏审计事件和结构化拒绝原因。

生产级策略研发闭环：

1. 先调用 `bitpro_capabilities`，再调用 `bitpro_health`。
2. 生成策略前先用 `market_klines` 确认真实 K 线覆盖。覆盖不足时做同步诊断或缩短区间；禁止合成 OHLCV。
3. 编写或生成单个 `BaseStrategy` 子类，持久化前必须通过 `strategy_validate_code`。
4. 通过 `strategy_create(script_content=...)` 保存为 DB 动态策略，并写入 `strategy_source=db_script` / `script_content_source=db`。
5. 用 `strategy_update` 做后续元数据修正，例如 BitPro canonical 命名、描述、配置补丁，或在重新校验后替换 DB 代码。
6. 用 `backtest_start_job` 启动 BitPro 负责的回测，轮询 `backtest_get_job`，再读取 `backtest_list_results` 和 `backtest_get_result`。
7. 只基于真实回测证据迭代。候选策略门禁要显式，例如最低交易数、正收益和受控回撤。
8. 只有通过门禁后，才用 `paper_configure` 和 `paper_start` 进入模拟盘。
9. 除非人类明确提供实盘风险确认字段，否则跳过所有实盘写工具。

2026-06-09 服务器验证已经跑通该闭环：通过 BitPro MCP 访问 `http://127.0.0.1:8889/api/v2`；ETH/USDT:USDT 1h 有 720 根真实 K 线，覆盖 2026-05-10T14:00:00Z 到 2026-06-09T13:00:00Z；策略 `#293` 通过 `strategy_validate_code`；回测任务 `a292d098-0657-411d-9fff-3c82b9b384d8` 完成并生成结果 `#196`；指标为收益 4.0441%、最大回撤 1.4438%、11 笔交易、Sharpe 0.8029、胜率 63.64%；策略 `#293` 已以 dry-run 模式启动模拟盘。实盘写工具已跳过。

具体数据调用步骤见 `docs/runbooks/bitpro-mcp-data-access.md`。第一版 HyperTrade 实现在 `backend/src/hypertrade/bitpro/mcp.py`：每条链路先调用 `bitpro_capabilities` 和 `bitpro_health`，再根据行情数据、策略生命周期、回测、模拟盘或实盘只读诊断选择最小工具。实盘写工具在该 adapter 内默认阻断。

BitPro `/live/dashboard` 返回被视为当前模拟盘引擎/dashboard 视图，不能据此判断“只有一个策略在运行”。当 `bitpro_paper_dashboard` 未传 `strategy_id` 时，HyperTrade 会用安全分页额外读取 `strategy_search(status=running)`，并返回 `paper_scope` 与 `running_strategies`。报告必须区分当前 dashboard 策略和 BitPro 暴露的完整 running 策略清单。

BitPro 回测排行和阈值问题必须通过 `bitpro_backtest_list_results` 回答，不能读取策略描述或 planner 记忆来推断。适配器使用 BitPro `offset`/`limit` 分页，把真实结果指标标准化为 `total_return_pct`，可在本地按阈值过滤，并用 `strategy_get` 补齐策略名以贴近页面展示。年化收益只能作为独立字段展示，不能替代回测总收益。

单个回测证据问题必须通过 `bitpro_backtest_get_result` 回答。适配器同样先执行 `bitpro_capabilities` -> `bitpro_health`，再读取 BitPro 负责的回测详情，标准化指标，并输出权益曲线、交易、订单、成交和回撤序列的有界样本。缺失 artifact 只能标记为不可用，HyperTrade 不合成样本行。

容器化部署时，BitPro MCP 通过显式 host-gateway 地址访问，不能使用 `127.0.0.1`，因为容器内 loopback 指向 `hypertrade-api` 自身。如果 BitPro 不可达，API 返回结构化 `502`，并携带失败的 BitPro tool call，方便区分上游不可用和 HyperTrade 运行时故障。
