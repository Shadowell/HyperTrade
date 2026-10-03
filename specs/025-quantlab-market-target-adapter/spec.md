# Spec 025: QuantLab 市场目标生产级适配与多资产自愈闭环

## 1. 目标与背景

HyperTrade 架构旨在实现跨交易平台的可插拔自进化（`market_target.v1` & `market-evolution.v1`）。继首个加密市场目标（BitPro）完成全链路闭环后，本规格旨在将 **QuantLab**（A 股 / 美股多资产量化工作台）正式升级为一等公民生产级市场目标。

核心诉求：
1. **MCP 契约与连接器解耦**：支持通过 `McpContractClient` 直连 QuantLab 生产暴露的标准 MCP 端口（8890），同时保留高保真本地嵌入式工作台（Embedded Simulator）供离线研究与自动化测试；
2. **非连续交易日历与指数相对基准**：完整支持 A 股/美股 `sessions` 日历（工作日 09:30-15:00 / 09:30-16:00），以 14 个已收盘交易日构建 7+7 窗口；
3. **股票现货交易规则与约束沙箱**：集成 A 股 T+1 交易规则（禁止单日高频日内回转）、禁止裸卖空（单向多头与现金比例管理）及印花税/过户费摩擦成本模型；
4. **全链路 String 策略 ID 兼容**：放宽 `RaceJudgeDaemon`、`HealedOffspring` 与自愈历史中的整数 ID 假定，全面兼容 QuantLab 命名空间字符串 ID（如 `quantlab:alpha_trend_01`）；
5. **股票专属 7 维因果归因与自愈变异**：针对多因子轮动、均线趋势与动态标的池策略提供超参数自愈变异，并产出符合 A 股语义的 7 维归因诊断报告。

## 2. 核心架构契约

### 2.1 市场目标档案 (`QUANTLAB_TARGET_PROFILE`)
- `target_id`: `quantlab`
- `tool_contract`: `market-evolution.v1`
- `venue`: `multi_asset` (A_SHARE / US_EQUITY)
- `market_type`: `cash`
- `quote_currency`: `CNY` (可按美股切为 `USD`)
- `strategy_id_format`: `string`
- `calendar`: `sessions` 模式，`Asia/Shanghai` 时区，14 交易日证据窗口。

### 2.2 变异与规则护栏
- **T+1 保护**：变异禁止将调仓或持仓周期缩短至 1 个交易日以下；
- **单向做空保护**：`allow_short = False`，仓位变异范围约束在 $[0.0, 1.0]$；
- **印花税与费率对齐**：回测与自愈收益需扣除万分之五印花税与券商佣金。
