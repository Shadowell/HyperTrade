# 014 自主巡航盯盘守护进程与实时全息感知流规格 (Autonomous Market Pulse & Live Perception Feeds)

## 1. 业务目标与背景

在 Spec 013 中，HyperTrade 完成了全自主交易 Agent 核心能力的奠基（包含受控免审批自主执行器、自由策略代码合成、通用市场写端口与 AST 沙箱）。然而，目前系统仍然处于**“被动响应”**和**“数据隔离”**的状态：
1. **被动响应**：自主下单工具 `live.autonomous_order` 只能在人类通过 Chat/API 主动发起任务时被触发，后台缺乏一个 7x24 小时常驻的主动盯盘与信号扫描守护进程（Market Pulse Daemon）；
2. **感知数据源局限**：`NewsIngestionService` 仅有 `InMemoryNewsFeed`，缺乏真正可连通公网的流式新闻、交易所公告与巨鲸异动摄入适配器。

本规格交付 **Phase 1: 自主巡航盯盘守护进程 + 真实外部感知流**，使 HyperTrade 具备主动盯盘、主动感知、主动决策与主动交易的 7x24 全自动闭环。

---

## 2. 需求定义 (Requirements)

### FR-001：真实多源加密资讯与公告流适配器 (Live Perception Feeds)
- 系统在 `hypertrade.market.news` 中提供真实公网数据源适配器：
  1. `RssCryptoNewsSource`：支持从主流加密媒体（如 CoinDesk, Cointelegraph, Decrypt 等）的公开 RSS/XML 提要中摄入突发新闻，无需第三方付费 Key；
  2. `CryptoPanicNewsSource`：支持对接 CryptoPanic 开放聚合 API，提取最新快讯与投票情绪；
  3. `OkxAnnouncementsSource`：抓取 OKX 官方上线（Listing）、下架、合约升级公告并解析受影响币种；
  4. `WhaleMovementSource`：支持链上大单/大额爆仓事件接入与紧急度打标。
- `NewsIngestionService` 具备周期性自动轮询聚合与内存去重，在无外网环境或接口报错时静默降级，不阻断主流程。

### FR-002：常驻自主巡航盯盘守护进程 (Autonomous Market Pulse Daemon)
- 新增 `hypertrade.agent.pulse.AutonomousMarketPulseService`：
  1. **周期性全息快照采集**：定时收集目标标的（如 BTC-USDT-SWAP, ETH-USDT-SWAP 等）的最新行情（K 线趋势、RSI、波动率、资金费率、订单簿价差）以及近期的突发新闻舆情；
  2. **启发式初筛与 LLM 自主决策**：
     - 若市场处于极度缩量整理且无任何异动，可直接判定 `HOLD`，节约 Token 消耗；
     - 若发现趋势突破、异常资金费率或突发重要事件，调用 `ChatProvider`（`gemini-3.8-flash-high`）进行自主推理，输出结构化决策（标的、动作 `BUY/SELL/HOLD/CLOSE`、置信度 `confidence` [0.0 - 1.0]、建议手数、决策原因与风控评估）；
  3. **受控自主执行**：
     - 当置信度高于阈值（默认 0.70）且动作符合交易逻辑时，直接调用 `AutonomousExecutionManager.execute_order` 下单；
     - 执行全程受 `AutonomousCircuitBreaker` 硬件级熔断与单日亏损硬限拦截；
  4. **全审计日志记录**：
     - 将每次巡航记录（时间戳、触发模式、扫描标的、情绪摘要、决策详情、实际执行订单 ID、耗时）持久化至数据库 `AutonomousPulseCycle` 表，供前端与 CLI 实时查询。

### FR-003：后台 Worker 任务挂载与运行时配置
- 在 `hypertrade.config` 增加自主巡航与感知参数：
  - `AUTONOMOUS_PULSE_ENABLED` (bool, 默认 True)
  - `AUTONOMOUS_PULSE_INTERVAL_SECONDS` (int, 默认 60)
  - `AUTONOMOUS_PULSE_SYMBOLS` (str, 默认 "BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP")
  - `AUTONOMOUS_PULSE_MIN_CONVICTION` (float, 默认 0.70)
  - `ENABLE_EXTERNAL_NEWS_FEED` (bool, 默认 True)
  - `CRYPTOPANIC_API_KEY` (str, 默认空)
- 在 `hypertrade.worker` 中新增 `autonomous_market_pulse_loop`，与模拟盘和行情摄入一同在后台稳定并发运行。

### FR-004：API 与 CLI 控制端交互
- API 暴露：
  - `GET /api/agent/pulse/history`：获取最近 N 次巡航记录与决策细节；
  - `POST /api/agent/pulse/trigger`：手动触发单次自主盯盘与交易循环；
  - `GET /api/market/news/latest`：获取最新摄入的结构化新闻。
- CLI 暴露：
  - `hypertrade pulse once`：单次触发自主巡航；
  - `hypertrade pulse history`：查询最近巡航决策历史。

---

## 3. 验收标准 (Acceptance Criteria)

1. **真实感知源测试**：
   - RSS 与 OKX 公告适配器单元测试通过，能正确解析 XML/JSON 为 `NewsArticle` 并提取受影响标的；
   - 接口网络异常或超时时具备容错回退机制，确保系统零 Crash。
2. **自主巡航服务测试**：
   - 单元测试覆盖 `AutonomousMarketPulseService` 的决策流程：当产生高置信度信号时能触发自主下单；置信度不足或判定 `HOLD` 时能记录理由且不触发下单；
   - 巡航循环产物正确写入 `AutonomousPulseCycle` 数据表。
3. **Worker 与 API 端到端集成**：
   - `worker.py` 能成功加载并运行 `autonomous_market_pulse_loop`；
   - API `/api/agent/pulse/trigger` 与 `/api/agent/pulse/history` 正常响应。
4. **代码质量与部署**：
   - `./scripts/check.sh` 全量通过（前端与后端所有测试、lint、typecheck 0 报错）；
   - 代码同步至测试服务器 `tokyo`，验证容器健康与实时巡航状态。
