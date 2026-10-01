# Tasks 021: 动态策略持久化注册表、自愈进化守护进程与前台量化指挥台

- [x] T001: 动态策略持久化注册表与工厂 (`hypertrade.paper.registry`) <!-- id: T001 -->
  - 实现 `StrategyRecord` 数据结构与持久化序列化；
  - 实现 `StrategyRegistry`，支持内存热读写与文件持久化；
  - 实现 `StrategyFactory`，支持动态映射构建 `ExecutionStrategy`；
  - 改造 `MultiStrategySignalEngine` 动态依赖 `StrategyRegistry`。

- [x] T002: 策略自愈突变与闭环进化中枢 (`hypertrade.paper.self_healing`) <!-- id: T002 -->
  - 实现 `SelfHealingEvolutionEngine`，支持对 `DEGRADED` 策略的因果归因与负向约束提取；
  - 实现多策略超参数针对性突变逻辑；
  - 实现快速回测与样本验证评估；
  - 自动向注册表注册下一代变体并派发飞书通知。

- [x] T003: 后台 Worker 自愈进化守护循环 (`hypertrade.worker`) <!-- id: T003 -->
  - 在后台 Worker 中接入 `self_healing_evolution_loop`；
  - 配置定期巡航与防并发锁机制。

- [x] T004: RESTful API 与 CLI 运维扩展 (`hypertrade.main`, `hypertrade.cli`, `hypertrade.paper.portfolio`) <!-- id: T004 -->
  - 暴露 `/api/portfolio/registry`、`/api/portfolio/strategies/{key}/evolve`、`/api/portfolio/evolution/history`；
  - 提供 `hypertrade portfolio registry list/evolve` 命令行交互。

- [x] T005: 前台量化交易指挥台组件 (`frontend/src/`) <!-- id: T005 -->
  - 构建 `QuantumPortfolioDashboard.tsx` 组件；
  - 集成账户总览、策略矩阵、实时持仓盯市、成交流与一键重平衡/自愈演化；
  - 在 `App.tsx` 的 `portfolio` 区域集成展示。

- [x] T006: 单元测试、端到端验证与质量门禁 (`tests/`, `./scripts/check.sh`) <!-- id: T006 -->
  - 编写 `tests/test_strategy_registry.py`；
  - 编写 `tests/test_self_healing_evolution.py`；
  - 编写 `tests/test_portfolio_dashboard_api.py`；
  - 运行并通过 `./scripts/check.sh` 全量质量门禁。
