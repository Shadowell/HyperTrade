# 013 全自主量化交易 Agent 实施计划 (Plan)

## 1. 架构总览与技术方案

本计划将规格 013 划分为 4 个高度解耦但紧密协同的工程切片：
1. **切片 1：全方位感知引擎（Perception Layer）**
   - 建立 `hypertrade/market/news.py` 与 `sentiment.py`；
   - 升级 `MarketIntelligenceService`，融合行情、衍生品指标与新闻情绪；
   - 注册 Agent 工具并在 Planner 中引入感知能力。
2. **切片 2：端到端自主执行中枢与熔断风控（Autonomous Execution & Risk Guard）**
   - 扩展 `hypertrade/risk/service.py` 引入 `AutonomousRiskGuard`，支持日亏损熔断、单笔上限、杠杆约束；
   - 扩展 `hypertrade/live/service.py` 引入 `AutonomousExecutionManager`，支持免逐单人工审批的自主交易；
   - 支持通过配置与授权决定是否开启全自主执行模式。
3. **切片 3：双轨策略自由合成与沙箱验证（Dual-Track Strategy Synthesis）**
   - 扩展 `hypertrade/research/codegen.py`，新增自由策略代码合成引擎 `FreeformStrategySynthesizer`；
   - 引入 AST 静态扫描和沙箱自动化校验；
   - 保留原有的 7 个家族和 Spec 008 原参数变体逻辑，确保存量策略调优 100% 兼容。
4. **切片 4：通用多市场写端口解耦与集成验证（Universal Market Targets）**
   - 在 `hypertrade/targets/ports.py` 中落地 `MarketWritePort`；
   - 消除 `EvolutionService.tick()` 中对非 BitPro 的硬编码跳过，接入通用适配器；
   - 编写完整的综合集成测试并确保 `./scripts/check.sh` 100% 通过。

---

## 2. 详细文件改动规划

| 序号 | 模块 | 文件路径 | 动作 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 感知层 | `backend/src/hypertrade/market/news.py` | 新增 | 新闻流摄入与模型抽象 |
| 2 | 感知层 | `backend/src/hypertrade/market/sentiment.py` | 新增 | 实时结构化情绪打分器 |
| 3 | 感知层 | `backend/src/hypertrade/market/intelligence.py` | 修改 | 融合即时新闻与情绪分析到感知总线 |
| 4 | 执行层 | `backend/src/hypertrade/risk/service.py` | 修改 | 支持 `RiskExecutionMode.AUTONOMOUS` 与日内亏损熔断器 |
| 5 | 执行层 | `backend/src/hypertrade/live/service.py` | 修改 | 增加 `AutonomousExecutionManager` 实现免逐单审批下单 |
| 6 | 策略层 | `backend/src/hypertrade/research/codegen.py` | 修改 | 增加 `FreeformStrategySynthesizer` 自由策略代码生成 |
| 7 | 适配层 | `backend/src/hypertrade/targets/ports.py` | 修改 | 强化通用 `MarketWritePort` 协议 |
| 8 | 适配层 | `backend/src/hypertrade/arc/evolution.py` | 修改 | 解除仅支持 BitPro 写端的硬编码跳过 |
| 9 | 工具层 | `backend/src/hypertrade/tools/registry.py` | 修改 | 注册自主交易与全景感知工具 |
| 10 | 测试层 | `tests/test_autonomous_trading_agent.py` | 新增 | 全流程端到端集成测试 |
