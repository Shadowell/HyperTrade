# Implementation Plan - Spec 020: 进阶实盘/模拟盘执行器升级与策略动态协同总线

## User Review Required

> [!NOTE]
> 核心目标是将原本仅支持单一 `3%` 涨幅简单触发的纸面引擎，升级为支持多策略注册并发运行、逆波动率风险平价资金配比、实时逐笔盯市更新与自动止盈止损监控、渐进式实盘晋升/熔断降级门禁的生产级多策略协同内核。

---

## Proposed Changes

### 1. 多策略信号生成抽象与核心策略实现 (`hypertrade.paper.strategies`)
- 新增 `hypertrade/paper/strategies.py`:
  - `ExecutionStrategy` 协议定义：`evaluate(tickers, klines, context) -> list[StrategySignal]`
  - `RsiReversalExecutionStrategy`: 整合自适应 RSI 震荡指标、动态超买超卖阈值、ATR 止损点位生成
  - `MomentumBreakoutExecutionStrategy`: 突破近期唐奇安高低点产生顺势动量信号
  - `MacdTrendExecutionStrategy`: 双均线与 MACD 柱穿越策略
  - `StrategySignal`: 结构化信号模型（包含 `strategy_key`, `inst_id`, `side`, `conviction`, `stop_loss_pct`, `take_profit_pct`, `reason`）
  - `MultiStrategySignalEngine`: 统一协调多个注册策略的并发运算与信号去重/仲裁

### 2. 逆波动率风险平价资金分配器 (`hypertrade.paper.allocation`)
- 新增 `hypertrade/paper/allocation.py`:
  - `RiskParityAllocator`:
    - 历史波动率估算（根据最新价格历史或 24h 高低估算波动率 $\sigma$）
    - 逆波动率基准权重计算：$w_i \propto 1/\sigma_i$
    - 策略阶段加权（Stage Weighting）：结合策略当前的运行阶段（`INCUBATING`, `PAPER_OBSERVING`, `CANARY_LIVE`, `CONTROLLED_LIVE`, `FULL_LIVE`）对权重进行缩放
    - 资产相关性约束（Correlation Damping）：同向大盘/山寨资产同开时进行敞口缩放
    - 输出精确开仓名义价值 `target_notional`

### 3. 渐进式晋升阶梯与熔断降级门禁 (`hypertrade.paper.stage_gate`)
- 新增 `hypertrade/paper/stage_gate.py`:
  - `StrategyStage` 枚举：`INCUBATING`, `PAPER_OBSERVING`, `CANARY_LIVE`, `CONTROLLED_LIVE`, `FULL_LIVE`, `DEGRADED`
  - `ProgressiveStageGate`:
    - 维护策略当前的运行阶梯与绩效统计（胜率、盈亏比、最大回撤、交易笔数）
    - 晋升评估：满足交易门槛自动推荐升级
    - 熔断降级（Circuit Breaker）：当出现连续亏损或回撤超标时，立即将策略强制降级至 `DEGRADED`，触发 `dispatch_reflexion_alert` 告警

### 4. 纸面与实盘执行引擎升级 (`hypertrade.paper.service` & `engine`)
- 修改 `hypertrade/paper/engine.py`:
  - 增强 `PaperSignalEngine`，使其支持委托给 `MultiStrategySignalEngine`，同时保持对原生 `generate(tickers)` 的 100% 向后兼容；
- 修改 `hypertrade/paper/repository.py`:
  - 增加 `update_position_marks(session_id, mark_updates)`: 批量更新持仓标记价格与未实现盈亏；
  - 增加 `update_session_equity(session_id, equity)`: 更新会话总权益；
- 修改 `hypertrade/paper/service.py`:
  - 强化 `run_once()`:
    1. Mark-to-Market: 逐笔刷新 open positions 最新行情价格与 unrealized PnL，汇总更新 `session.equity`；
    2. Bracket Order 自动监控：检测 `stop_loss_pct` 或 `take_profit_pct`，触发时自动调用平仓；若达到单笔严重亏损，自动记录并派发反思告警；
    3. 多策略多标的评估：调用 `MultiStrategySignalEngine`，使用 `RiskParityAllocator` 计算各标的分配资金，生成 simulated fills 并入库。

### 5. 组合管理服务、REST API 与 CLI 集成
- 新增 `hypertrade/paper/portfolio.py`:
  - `PortfolioCoordinatorService`: 汇聚多策略阶段、组合总敞口、风险平价权重、杠杆使用率的统一门面
- 在 `hypertrade/main.py`:
  - `GET /api/portfolio/summary`
  - `GET /api/portfolio/strategies`
  - `POST /api/portfolio/strategies/{key}/stage`
  - `POST /api/portfolio/rebalance`
- 在 `hypertrade/cli.py`:
  - `hypertrade portfolio summary`
  - `hypertrade portfolio strategies`
  - `hypertrade portfolio rebalance`
  - `hypertrade portfolio stage`

### 6. 端到端集成测试与质量门禁
- 编写 `tests/test_multi_strategy_execution.py`
- 编写 `tests/test_risk_parity_allocation.py`
- 编写 `tests/test_progressive_stage_gate.py`
- 编写 `tests/test_portfolio_coordinator_e2e.py`
- 运行 `./scripts/check.sh` 确保 100% 通过
