# 013 全自主量化交易 Agent 任务分解清单 (Tasks)

## 任务执行顺序

- [x] **T001: 实时消息面摄入与情绪分析引擎**
  - 新建 `hypertrade.market.news`，支持新闻条目定义、去重缓存、优先级排序与数据源适配器；
  - 新建 `hypertrade.market.sentiment`，提供新闻情绪分析器 `NewsSentimentAnalyzer`（提取标的、情绪打分、事件分类、紧急度）；
  - 编写单元测试验证新闻摄入与情绪打分逻辑。

- [x] **T002: 统一市场感知总线 (Perception Bus) 与工具集成**
  - 升级 `hypertrade.market.intelligence.MarketIntelligenceService`，整合行情、持仓资金费与实时新闻情绪；
  - 在 `hypertrade.tools.registry` 中暴露 `market.perception_snapshot` 与 `market.news_stream`；
  - 在 `hypertrade.agent.planner` 与 AgentKernel 中接通感知工具执行。

- [x] **T003: 端到端受控自主执行风控护栏 (AutonomousRiskGuard)**
  - 扩展 `hypertrade.risk.service.RiskEngine`，支持 `RiskExecutionMode.AUTONOMOUS`；
  - 实现单笔最大风险检查、杠杆限制与硬件级日内亏损熔断器（Daily Loss Circuit Breaker）；
  - 编写测试验证自主模式下的风控放行与日亏损熔断拦截。

- [x] **T004: 免逐单人工审批的自主交易执行器 (AutonomousExecutionManager)**
  - 在 `hypertrade.live.service` 中实现 `AutonomousExecutionManager`，支持直接调用撮合或交易所 API 执行订单；
  - 支持幂等写入、状态自洽与实时持仓回读；
  - 在工具注册表中暴露 `live.autonomous_order` 工具。

- [x] **T005: 自由策略代码合成器 (FreeformStrategySynthesizer) 与 AST 安全门禁**
  - 扩展 `hypertrade.research.codegen`，实现超越 7 个模板的自由策略代码合成引擎；
  - 强化 AST 语法安全白名单，验证生成的策略代码符合 `BaseStrategy` 接口且无非法指令；
  - 验证轨道 A（已有策略原参数受控调优 Spec 008/011）完全兼容无回退。

- [x] **T006: 通用多市场写端口解耦与进化引擎接入**
  - 扩展 `hypertrade.targets.ports` 中的 `MarketWritePort` 协议；
  - 改造 `hypertrade.arc.evolution.py`，移除 `config.target_id != "bitpro"` 的硬编码阻断，根据配置动态调用目标写端口；
  - 支持多市场环境下的自主策略变体部署。

- [x] **T007: 端到端集成测试与全量质量门禁**
  - 编写 `tests/test_autonomous_trading_agent_e2e.py` 覆盖感知、自主执行、风控熔断、自由策略合成与多目标适配全链路；
  - 执行 `./scripts/check.sh` 确保 100% 测试通过、前端 lint/test/build 0 报错、后端 ruff/mypy 0 报错。
