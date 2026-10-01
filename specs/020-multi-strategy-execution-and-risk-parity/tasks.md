# Tasks - Spec 020: 进阶实盘/模拟盘执行器升级与策略动态协同总线

- [ ] T001: 多策略信号引擎与核心策略族实现 (`hypertrade.paper.strategies`)
  - 定义 `StrategySignal` 与 `ExecutionStrategy` 协议；
  - 实现 `RsiReversalExecutionStrategy`、`MomentumBreakoutExecutionStrategy`、`MacdTrendExecutionStrategy`；
  - 实现 `MultiStrategySignalEngine` 集中调度与冲突仲裁。

- [ ] T002: 逆波动率风险平价资金分配器 (`hypertrade.paper.allocation`)
  - 实现 `RiskParityAllocator`；
  - 实现基于历史收益率/振幅的资产波动率评估与逆波动率加权；
  - 支持多策略运行阶段权重调节与跨资产相关性抑制（Correlation Damping）。

- [ ] T003: 渐进式实盘晋升阶梯与熔断降级门禁 (`hypertrade.paper.stage_gate`)
  - 定义 `StrategyStage` 枚举及阶段配额限制；
  - 实现 `ProgressiveStageGate` 评估胜率、盈亏比、回撤以支持自动推荐升级；
  - 实现硬熔断降级与联动 Reflexion 提炼负向约束并向飞书推送告警卡片。

- [ ] T004: 纸面执行引擎与盯市退出机制升级 (`hypertrade.paper.service` & `repository`)
  - `PaperRepository` 增加批量更新标记价格和总权益接口；
  - `PaperTradingService.run_once()` 实现 Mark-to-Market 估值、Bracket Order 自动止盈止损与多策略风险平价开仓。

- [ ] T005: 组合协同协调服务与 REST API / CLI 运维集成
  - 实现 `PortfolioCoordinatorService` 汇聚多策略与风险全景；
  - 在 `hypertrade.main` 暴露 `/api/portfolio/summary`、`/api/portfolio/strategies`、`/api/portfolio/strategies/{key}/stage`、`/api/portfolio/rebalance`；
  - 在 `hypertrade.cli` 暴露 `hypertrade portfolio summary`、`strategies`、`rebalance`、`stage`。

- [ ] T006: 端到端自动化测试与 `./scripts/check.sh` 质量门禁全通
  - 编写相关单元与集成测试（`tests/test_multi_strategy_execution.py`、`tests/test_risk_parity_allocation.py` 等）；
  - 执行 `./scripts/check.sh` 保证前端、Ruff、Mypy、全量 pytest 100% 绿灯。
