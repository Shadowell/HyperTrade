# 62 可插拔市场目标：自进化核心与平台解耦

> 状态：Phase 1 已交付（2026-09-14）；Phase 2 的进化读取与 sessions 日历在任务分支实现，待集成验证。Paper 写端口及 QuantLab 实机仍未完成。

## 1. 背景与问题

进化循环（ARC/AVO 自主研究 → 7+7 退化判定 → 受治理 Paper → 观察反馈）在逻辑上
与平台无关，但实现上通过 `BitProToolAdapter` 及其约 15 个窄协议把 BitPro 的响应
形状、`okx/swap/USDT` 词表、UTC 14 天窗口、`instance_id` 数字身份等假设散布在
核心路径上（完整盘点见 2026-09-14 勘察：33 处导入、46 条路由表、~1661 处
BitPro 标志）。用户目标：**自进化能力必须通用；市场可随时插拔；接入方式统一走
MCP**——BitPro 是首个目标，QuantLab（A 股/美股，将提供 MCP）是下一个。

## 2. 目标模型（`market_target.v1`）

`hypertrade/targets/schemas.py`：`MarketTargetProfileV1`，冻结字段：

| 字段 | 说明 |
|---|---|
| `target_id` | 注册键（`^[a-z][a-z0-9_-]{1,63}$`），`EvolutionConfig.target_id` 引用 |
| `transport` | `bitpro_mcp_v1`（内置适配器）或 `mcp_contract_v1`（标准 MCP 契约） |
| `tool_contract` | 平台侧契约版本（`bitpro-mcp-v1` / `market-evolution.v1`） |
| `venue/market_type/quote_currency` | 市场词表（okx/swap/USDT；QuantLab 可声明 cn/cash/CNY） |
| `strategy_id_format` | `integer`（BitPro）或 `string`（QuantLab 类） |
| `calendar` | `TargetCalendarV1`：`mode=continuous|sessions`、`timezone`、`evidence_window_days`(14)、`evidence_bucket_seconds`(3600)、sessions 模式的 `session_open/close/trading_days` |
| `evidence_contracts` | 目标必须提供的证据契约（`strategy_return_series.v1` 等） |
| `cost_policy_sources` | 可接受的成本政策来源白名单（BitPro：`bitpro_backtest_cost_resolver`） |
| `capabilities` | 能力开关（running_inventory/session_snapshot/return_series/session_trades/execution_ledger/backtest/paper_launch/cost_identity/live_preflight）；只管特性，不管权限 |

## 3. 注册表与解析

`hypertrade/targets/registry.py`：

- `register_market_target(profile, adapter_factory)` 显式注册、重复注册报错，
  内置 BitPro 目标在首次使用时惰性注册（`bitpro.py`，适配器工厂延迟构建，
  import 注册表不会创建 HTTP 客户端）。
- `get_active_market_target()` 由设置 `MARKET_TARGET`（默认 `bitpro`）决定；
  未知目标抛 `MarketTargetUnavailable` 并列出已注册清单，不静默回落。
- `adapter_for_target(target_id)` 为进化循环提供适配器。
- 进程级开关：`EvolutionConfig.target_id`（默认 `bitpro`，`configure()` 时校验
  必须已注册），循环内所有客户端解析都经 `targets` 注册表。

## 4. 通用 MCP 契约（`market-evolution.v1`）

`hypertrade/targets/mcp_contract.py`：任何暴露下述规范工具的标准 MCP 服务器都
可注册为市场目标（QuantLab 接入路径）。工具发现用 `tools/list` 实时校验：

| 能力 | 规范工具名 | 参数 |
|---|---|---|
| 运行清单 | `evolution_list_running_strategies` | `limit` |
| 会话快照 | `evolution_get_session_snapshot` | `strategy_id`, `instance_id` |
| 权益序列 | `evolution_get_equity_series` | `instance_id`, `start`, `end`, `bucket_seconds`, `limit` |
| 会话成交 | `evolution_list_session_trades` | `strategy_id`, `limit`, `since` |
| 执行台账 | `evolution_read_execution_ledger` | `session_id`, `kind`, `start_ms`, `end_ms`, `limit` |
| 配置 Paper | `evolution_configure_paper` | `strategy_id`, `capital`, `symbols`, `timeframe`, `code_sha256`, `review_hash`, `idempotency_key` |
| 启动 Paper | `evolution_start_paper` | `strategy_id`, `instance_id`, `code_sha256`, `review_hash`, `strategy_version`, `config_version`, `idempotency_key` |

`McpContractClient` 包装既有 `McpClientRegistry`（多服务器、发现缓存、指数退避、
每服务器熔断），只添加契约语义：能力→工具名解析与 `preflight()` 校验（缺哪个
工具报哪个，发现失败报错误原因）。`build_mcp_contract_profile()` 生成
`mcp_contract_v1` 目标档案。

Phase 2 读取扩展另外要求 `evolution_get_strategy_source(strategy_id)` 与
`evolution_list_trading_sessions(start_date, end_date)`（后者只在 sessions 日历必需）。
`McpContractClient.preflight_read()` 单独校验读取所需的规范工具，不放宽原七工具
`preflight()`；`McpReadPorts` 通过 `McpClientRegistry` 调用规范工具、校验目标身份与
版本化响应、映射类型化读取证据。登记目标时使用
`register_market_target(profile, lambda: McpReadPorts(McpContractClient(registry, server, profile)))`。
离线 MCP transport 夹具已验证从 `tools/list` 到同一扫描入口的资格/退化决策；
这不代表 QuantLab 或 BitPro 服务端已经暴露这些工具。

## 5. 已接线点与 Phase 2 端口

**Phase 1 已接线**（行为与旧版逐字节一致，测试钉死）：

- `EvolutionService._client()`（含 tick 内二次身份复核路径）经注册表解析适配器。
- `readiness()` 的窗口天数与对齐时区来自目标日历（continuous/UTC/14 天默认与
  旧逻辑相同；`completed_utc_window` 阻塞码保持不变——面板文案绑定该码）。
- `EvolutionConfig.configure()` 拒绝未注册目标。
- 归因/成本身份/供给写路径等仍走既有窄协议，按目标能力开关门控。

**Phase 2 读取切片（任务分支，待集成验证）**：`EvolutionService._scan` 的运行清单、
原策略、会话快照、成交和权益序列从 `targets` 读取端口取得；BitPro 通过只读适配器
维持旧证据契约。`sessions` 日历从目标读取完整交易日清单，在目标时区按 14 个已收盘
交易日组成 7+7 窗口，另要求前一交易日收盘作为第 15 个取证日期；第 7 日收盘是两窗
共享边界，隔夜跳空计入最近窗收益与回撤。每点必须携带匹配的交易日，缺日历、边界、版本、成本身份或
分页完整性时拒绝判定。非 BitPro 目标可读取并判定，但因 Paper 写端口尚未迁移，
研究创建明确停在 `deferred_target_write_port`。

**Phase 2 未交付**：成本身份词表与 Paper 供给三段写路径迁移、非 BitPro 的
告警/效果账本适配、BitPro 服务端规范工具名、QuantLab 实机接入及真实市场
数据/费用证据。`MCP` 工具声明或离线夹具不能作为这些能力已接通的证明。

## 6. 离线元学习调参（`evolution_tuning.v1`）

`hypertrade/arc/meta_tuning.py`。只回放**已结算的历史观测**：每个扫描周期在
`EvolutionCycle.payload` 冻结了当轮配置与 7+7 窗口值
（`return_drop_pp`/`drawdown_increase_pp`），调参器据此计算：

- 规则：退化阈值定在观测分布的 **p90**——前 10% 幅度的事件触发研究、其余视为
  噪声；下限 `max(5pp, p50)`、上限 20pp；样本 < 12 条不调参（`insufficient_data`）。
- 边界：`TuningBoundsV1`（min 5 / max 20 / 单步 ≤ 3pp / 最小样本 12）。
- 授权：`meta_tuning_enabled`（默认 True）只产出建议回执；`meta_tuning_auto_apply`
  （默认 False）才允许应用，且每次仅一步、每日最多一次（`tune_YYYYMMDD` 回执幂等，
  worker 每小时轮询不会叠加放大）、经 `EvolutionService.configure` 修订审计，
  操作者记为 `hypertrade:meta-tuner`。
- 面：`GET /api/v1/arc/evolution/tuning`（只读报告）；worker `arc_meta_tuning_loop`。
- 边界声明：只调 `threshold_pp`；`paper_criteria`/`min_trades`/冷却/预算上限不在
  自动调整范围。

## 7. 归因：见证式绑定，不推断

`paper_evidence.v1` 的 `coverage.fields` 是上游对每种能力的自述。升级后的
`costs`/`long_short` 维度只在**两页都标记 `observed`** 且台账条目携带通过数值
校验的值时点亮（费用合计、净 PnL、long/short 计数与净 PnL）；`side` 仅识别
`long/short` 词表。当前 BitPro 上游全部字段为 `unknown`，因此线上行为不变；
语义仍为 `descriptive_execution_coverage_only`、`causal_conclusion=not_established`。
`source_field_states` 状态为 unknown/observed/unverified 三态。

## 8. 安全与兼容性

- 默认开启（`enabled=True`）只影响新配置：生产已持久化的配置与 revision 不变；
  每个周期的数据门槛（14 天窗口/成交数/证据完整性）完全不变。
- 未注册目标在配置时即被拒绝（409），不会带病运行到扫描期。
- 元学习默认只建议；自动应用必须显式授权、有界、可审计、每日一次。
- Live 边界不变：目标能力 `live_preflight` 只读；任何 live 写动作仍由既有
  审批链独占，`targets` 层不持有任何直接写权限。

## 9. 验证与运维

```bash
uv run pytest tests/test_market_targets.py tests/test_meta_tuning.py \
  tests/test_arc_attribution.py tests/test_arc_evolution.py \
  tests/test_evolution_continuation.py -q
./scripts/check.sh
```

运维：`MARKET_TARGET` 切换活跃目标；`GET /evolution` 的 config 含 `target_id`；
调参回执以 `meta_tuning` 状态出现在周期账本中。QuantLab 接入步骤：
（1）MCP 服务器实现第 4 节七个工具；（2）`MCP_SERVERS_JSON` 注册服务器；
（3）`build_mcp_contract_profile()` 生成档案并注册；（4）`preflight()` 冒烟通过后
将 `MARKET_TARGET` 指向该目标；（5）按 Phase 2 端口完成读取/供给路径接线。
