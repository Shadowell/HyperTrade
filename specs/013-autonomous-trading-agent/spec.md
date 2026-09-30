# 013 全自主量化交易 Agent：端到端感知、自进化与受控实盘中枢规格

## 1. 业务目标与背景

HyperTrade 的长远目标是成为一个具备自主研究、自主进化、并能自主进行实际交易的独立 Agent。现有系统在治理和合规方面非常严谨，但在交易自主性、信息感知全面度与策略进化自由度上存在三大瓶颈：
1. **执行受困**：代码中对主网实盘进行了全局硬拦截，即使在测试环境中也要求每笔订单由人工审批，无法做到给它一个账户就能自己跑；
2. **感知缺失**：市场情报缺乏实时新闻流、宏观日历和突发事件的结构化情绪打分；
3. **进化受限**：策略代码被锁死在 7 个固定技术指标模板中，模型无法编写创新型策略逻辑。

本规格旨在彻底打破上述枷锁，交付一套**端到端全自主量化交易 Agent 核心能力**，包含：
- **实时消息面与情绪感知总线（Perception Engine）**；
- **免人工逐单审批的受控自主执行引擎与熔断风控（Autonomous Execution & Circuit Breakers）**；
- **超越 7 个模板的自由代码策略合成器与隔离沙箱门禁（True Alpha Strategy Synthesis）**；
- **完全兼容保留存量策略的参数调优与变体 A/B 对决（Dual-Track Evolution）**；
- **解耦单一交易平台的通用多市场写端口适配（Universal Market Targets）**。

---

## 2. 需求定义 (Requirements)

### FR-001：多源消息流与实时情绪感知引擎 (Perception Layer)
- 系统必须提供 `NewsIngestionService`，支持结构化接收实时新闻与快讯流（包含标题、正文、发布时间戳、来源等级）。
- 系统必须提供 `NewsSentimentAnalyzer`，对新闻流进行快速特征提取，输出标准化结果：
  - `affected_symbols`: 关联标的列表（如 `BTC-USDT`，或宏观 `*`）；
  - `sentiment_score`: 情绪量化评分 `[-1.0, 1.0]`；
  - `event_category`: 事件类别（`regulatory`, `exploit_hack`, `macro_rates`, `partnership_listing`, `whale_movement`, `general_market`）；
  - `urgency`: 紧急度（`breaking`, `high`, `normal`, `low`）。
- 升级 `MarketIntelligenceService`，将其扩展为统一感知总线（Perception Bus），同时提供 K 线、资金费、未平仓合约与即时消息面情绪。
- Agent 工具集增加 `perception_snapshot` 与 `news_stream_query`。

### FR-002：端到端受控自主执行中枢 (Autonomous Execution Engine)
- 系统必须支持双轨执行模式：
  - `SUPERVISED`（监督模式）：写操作需等待人工审批凭证；
  - `AUTONOMOUS`（全自主模式）：在预先授权的限额（Mandate）内，Agent 可自主下单与撤单，无需人工逐单确认。
- 提供硬件级自主风控护栏 (`AutonomousRiskGuard`)：
  - **日内亏损熔断器 (Daily Loss Circuit Breaker)**：当日净亏损达到预设比例（如 3%）时，单向触发熔断，自动撤单并阻止新增开仓；
  - **单笔最大风险约束**：单笔名义价值与止损敞口不得突破账户权益上限；
  - **杠杆与持仓上限**：多空敞口受到硬顶约束。
- 提供 `AutonomousExecutionManager`，支持根据策略信号或 Agent 决策直接派发订单至交易接口，支持幂等重试与对账。

### FR-003：双轨制策略引擎与真实代码进化 (Dual-Track Strategy Hub)
- **轨道 A（存量策略保护与调优）**：
  - 100% 保留已有的 `source_variant_policy`、Spec 008 来源受控参数变体、与 Spec 011 模拟盘孪生变体 A/B 对决能力，确保既有运行中的 12 个策略平稳进化，不破坏既有测试和生产状态。
- **轨道 B（自由代码生成 True Alpha Synthesis）**：
  - 突破 7 个模板的限制，提供 `FreeformStrategySynthesizer`，支持 Agent 基于丰富的标准量化构件（如动量、均值回归、波动率、网格、多因子、事件驱动等范式）编写完整的 Python 策略代码。
  - 强化代码安全沙箱校验：严格进行 AST 语法分析、禁止调用外部非法库与危险操作，并在 UDS 沙箱内运行走步检验（Walk-Forward）与小样本回测。

### FR-004：通用多市场写端口解耦 (Universal Market Targets)
- 在 `hypertrade.targets.ports` 中完善统一的 `MarketWritePort` 规范（覆盖策略校验、部署、模拟盘/实盘实例启停、订单路由）。
- 消除 `EvolutionService.tick()` 中对非 `bitpro` 目标的跳过硬编码，根据 `target_id` 自动加载对应的市场适配器（支持 BitPro、Native 直连交易所或测试环境），使自进化引擎可无缝运用于不同市场目标。

### FR-005：系统稳定性与无人工干预自治
- 在无人值守或低频干预场景下，后台异步 Worker 能自动化运转感知、研判、执行与复盘循环，遇到异常数据自动标注降级，遇到风控红线自动平仓熔断。

---

## 3. 验收标准 (Acceptance Criteria)

1. **感知层**：
   - 单元测试覆盖新闻摄入、情绪打分、紧急事件过滤，能正确将新闻转化为结构化情绪信号，并由 `MarketIntelligenceService` 和 Agent 工具调用返回。
2. **执行中枢**：
   - 在自主模式（`AUTONOMOUS`）下，符合风控限制的订单请求可直接执行成功，返回正式订单回执，无需人工批准；
   - 当单日亏损突破预设阈值时，`AutonomousRiskGuard` 立即触发熔断，后续下单请求被明确拒绝，状态标记为 `circuit_broken`。
3. **策略双轨制**：
   - 存量策略参数调优（Spec 008/011）现有回归测试保持 100% 通过；
   - 自由策略合成器能成功生成符合 `BaseStrategy` 规范的完整 Python 源码，通过 AST 安全检查并在沙箱中可运行。
4. **代码质量**：
   - `./scripts/check.sh` 全量通过（前端 lint/test/build，后端 ruff、mypy、pytest 0 报错）。
