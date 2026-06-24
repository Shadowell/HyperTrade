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

Live order-history reads are exposed to the Agent as `bitpro_live_order_history`
and registered in ToolRegistry as `bitpro.live_order_history`. The tool calls
BitPro's read-only `/trading/orders/history` path after the standard
`bitpro_capabilities` -> `bitpro_health` preflight, renders the latest returned
order in a `BitPro 实盘订单` section, and must never be used for order placement,
cancellation, transfer, or other live writes.

Live strategy performance reads are exposed to the Agent as
`bitpro_live_strategy_performance` and registered in ToolRegistry as
`bitpro.live_strategy_performance`. The tool calls BitPro's read-only
`/live/strategies` path after the same preflight, ranks rows by the BitPro page
metric `return_pct`, and renders a `BitPro 实盘策略收益` section with `total_pnl`
when BitPro returns it. Missing performance fields stay missing; HyperTrade does
not infer them from strategy names, market movement, or memory.

Research/backtest/paper writes are allowed only through explicit Agent tool calls such as strategy generation, strategy creation, BitPro-owned backtest jobs, and paper/simulation lifecycle control. Live write tools must be added later and separately. Any testnet or live write path needs explicit scopes, idempotency keys, approval gates, risk prechecks, redacted audit events, and structured refusal reasons.

Remote Agent authentication uses BitPro MCP Agent tokens, not browser login cookies. BitPro administrators generate `bp_mcp_` tokens from Settings -> Agent Access -> MCP Agent Token or through `POST /api/v2/settings/mcp-agent-tokens`; BitPro stores token hashes only and returns plaintext once. HyperTrade stores the selected token only in server-side environment such as `BITPRO_MCP_API_TOKEN`, sends it with `X-BitPro-MCP-Token`, and exposes only redacted contract metadata through `/api/harness/overview`. The adapter reports scope classes `R` read, `W` research/backtest/paper mutation, `L` live diagnostics, and `T` live mutation; HyperTrade continues to block `T` tools.

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

Operational data-access steps are documented in `docs/runbooks/bitpro-mcp-data-access.md`. The first HyperTrade implementation lives in `backend/src/hypertrade/bitpro/mcp.py`: every flow starts with `bitpro_capabilities` and `bitpro_health`, then selects the smallest tool for market data, strategy lifecycle, backtest, paper/simulation, or live read-only diagnostics. Live write tools are blocked in this adapter. The local capability document mirrors BitPro's `agent_auth`, `remote_mcp`, `tool_groups`, token-management routes, and idempotency requirements so the Agent can diagnose `401` authentication failures without depending on a BitPro web session.

The BitPro `/live/dashboard` response is treated as a current paper engine/dashboard view, not proof that only one strategy is running. When HyperTrade calls `bitpro_paper_dashboard` without a `strategy_id`, the adapter also reads `strategy_search(status=running)` with safe pagination and returns `paper_scope` plus `running_strategies`. Reports must distinguish the current dashboard strategy from the complete running strategy inventory exposed by BitPro.

Paper monitoring is deterministic and read-only. The adapter derives
`monitor_summary` from the current dashboard metrics plus the running strategy
inventory: equity, total PnL, Sharpe, drawdown, inventory coverage, alerts, data
gaps, and suggested operator checks. If `strategy_search(status=running)` does
not include per-strategy PnL or drawdown, HyperTrade reports that as a data gap
instead of inferring those metrics.

Paper monitoring evidence is split into separate read tools. `bitpro_paper_events`
reads `/live/events` with optional `strategy_id` and bounded `limit`, normalizes
event/error rows, and reports counts plus the latest event timestamp. `bitpro_paper_equity_curve`
reads `/live/equity_curve` with optional `strategy_id`, keeps a bounded sample of
equity/drawdown points, and reports latest equity plus drawdown summaries. These
tools complement the dashboard; they do not mutate paper state and they do not
invent missing rows.

Paper monitor snapshots persist this read-only evidence in HyperTrade. The
`bitpro_paper_monitor_snapshot` Agent tool captures dashboard, event summary, and
equity summary through the existing MCP/API read tools, stores normalized metrics
and nested BitPro tool calls, then compares the capture with the previous snapshot
for the same strategy/all-strategy scope. Drift alerts cover equity drops, PnL
drops, drawdown expansion, and newly observed event errors. Missing comparable
metrics remain data gaps; the snapshot tool never pauses, resumes, stops, or
starts paper/live trading.

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

When the Agent starts a BitPro-owned backtest, `bitpro_backtest_start_job` waits
for the job to reach a terminal state in the Agent execution path, then normalizes
the completed `job.result` and links it to the saved BitPro result row when the
row is available. The CLI report should show the same key metrics as the BitPro
results page rather than a polling lifecycle log.

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

实盘订单历史读取通过 Agent 工具 `bitpro_live_order_history` 暴露，并在
ToolRegistry 中注册为 `bitpro.live_order_history`。该工具在标准
`bitpro_capabilities` -> `bitpro_health` 预检后调用 BitPro 只读
`/trading/orders/history` 路径，在报告中渲染 `BitPro 实盘订单` 和最近订单；
不得用于下单、撤单、划转或任何实盘写入。

实盘策略收益读取通过 Agent 工具 `bitpro_live_strategy_performance` 暴露，并在
ToolRegistry 中注册为 `bitpro.live_strategy_performance`。该工具在同样预检后
调用 BitPro 只读 `/live/strategies` 路径，按页面口径 `return_pct` 排名，并在
报告中渲染 `BitPro 实盘策略收益`；`total_pnl` 只展示 BitPro 返回值，缺失时不
从策略名称、行情涨跌或记忆推断。

研究、回测、模拟盘写入只允许通过明确 Agent 工具调用执行，例如策略生成、策略创建、BitPro 回测 job 和 paper/simulation 生命周期控制。实盘写工具必须后续单独加入。任何 Testnet 或实盘写入路径都必须具备明确 scope、幂等键、审批门、风控预检、脱敏审计事件和结构化拒绝原因。

远程 Agent 认证使用 BitPro MCP Agent Token，不依赖浏览器登录 cookie。BitPro 管理员可在设置页 `Agent 接入 / MCP Agent Token` 生成 `bp_mcp_` token，或调用 `POST /api/v2/settings/mcp-agent-tokens`；BitPro 只保存哈希，明文只返回一次。HyperTrade 只把选中的 token 存在服务器环境，例如 `BITPRO_MCP_API_TOKEN`，调用 BitPro 时通过 `X-BitPro-MCP-Token` 发送，`/api/harness/overview` 只暴露脱敏合同元数据。适配器报告 `R` 只读、`W` 研究/回测/模拟盘写、`L` 实盘诊断、`T` 实盘写四类 scope；HyperTrade 继续阻断 `T` 工具。

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

具体数据调用步骤见 `docs/runbooks/bitpro-mcp-data-access.md`。第一版 HyperTrade 实现在 `backend/src/hypertrade/bitpro/mcp.py`：每条链路先调用 `bitpro_capabilities` 和 `bitpro_health`，再根据行情数据、策略生命周期、回测、模拟盘或实盘只读诊断选择最小工具。实盘写工具在该 adapter 内默认阻断。本地 capability 文档同步 BitPro 的 `agent_auth`、`remote_mcp`、`tool_groups`、Token 管理路由和幂等要求，使 Agent 遇到 `401` 时能定位到 MCP Agent Token 配置，而不是依赖 BitPro Web 登录态。

BitPro `/live/dashboard` 返回被视为当前模拟盘引擎/dashboard 视图，不能据此判断“只有一个策略在运行”。当 `bitpro_paper_dashboard` 未传 `strategy_id` 时，HyperTrade 会用安全分页额外读取 `strategy_search(status=running)`，并返回 `paper_scope` 与 `running_strategies`。报告必须区分当前 dashboard 策略和 BitPro 暴露的完整 running 策略清单。

模拟盘监控是确定性且只读的。适配器从当前 dashboard 指标和 running 策略清单生成 `monitor_summary`：权益、总收益、Sharpe、回撤、清单覆盖、告警、数据缺口和建议检查动作。如果 `strategy_search(status=running)` 不包含逐策略收益或回撤，HyperTrade 必须把它报告为数据缺口，而不是推断这些指标。

模拟盘监控证据拆成独立只读工具。`bitpro_paper_events` 读取 `/live/events`，支持可选 `strategy_id` 和有界 `limit`，标准化事件/错误行，并报告事件数量、错误数量和最新事件时间。`bitpro_paper_equity_curve` 读取 `/live/equity_curve`，支持可选 `strategy_id`，保留有界权益/回撤样本，并报告最新权益和回撤摘要。这些工具补充 dashboard 视图，不修改模拟盘状态，也不合成缺失样本。

模拟盘监控快照把这些只读证据持久化在 HyperTrade。`bitpro_paper_monitor_snapshot` Agent 工具通过现有 MCP/API 只读工具捕获 dashboard、事件摘要和权益摘要，保存标准化指标和嵌套 BitPro tool calls，然后与相同策略/全局 scope 的上一条快照比较。漂移告警覆盖权益下降、PnL 下降、回撤扩大和新增事件错误。缺失的可比指标只能作为 data gap 展示；快照工具绝不暂停、恢复、停止或启动模拟盘/实盘。

BitPro 回测排行和阈值问题必须通过 `bitpro_backtest_list_results` 回答，不能读取策略描述或 planner 记忆来推断。适配器使用 BitPro `offset`/`limit` 分页，把真实结果指标标准化为 `total_return_pct`，可在本地按阈值过滤，并用 `strategy_get` 补齐策略名以贴近页面展示。年化收益只能作为独立字段展示，不能替代回测总收益。

单个回测证据问题必须通过 `bitpro_backtest_get_result` 回答。适配器同样先执行 `bitpro_capabilities` -> `bitpro_health`，再读取 BitPro 负责的回测详情，标准化指标，并输出权益曲线、交易、订单、成交和回撤序列的有界样本。缺失 artifact 只能标记为不可用，HyperTrade 不合成样本行。

当 Agent 启动 BitPro 负责的回测时，`bitpro_backtest_start_job` 会在 Agent 执行路径中等待 job 进入终态，然后标准化 completed `job.result`，并在可用时关联到 BitPro 已保存的 result 行。CLI 报告应展示与 BitPro 回测结果页面同口径的核心指标，而不是轮询生命周期日志。默认面向交易阅读的回测报告不展示 MCP 合同版本、内部工具顺序或 RAG 引用来源；这些审计信息保留在 trace 和显式调试输出里。

容器化部署时，BitPro MCP 通过显式 host-gateway 地址访问，不能使用 `127.0.0.1`，因为容器内 loopback 指向 `hypertrade-api` 自身。如果 BitPro 不可达，API 返回结构化 `502`，并携带失败的 BitPro tool call，方便区分上游不可用和 HyperTrade 运行时故障。
