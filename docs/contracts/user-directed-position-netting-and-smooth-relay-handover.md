# User-Directed Contract — 赛马接力阶段的净额平滑换仓 (Spec 030)

> 状态：Active
> 日期：2026-10-05
> 责任人：Antigravity & Codex

## 1. 背景与业务痛点

在量化资产管理与自主进化系统中，当经由前向证据门禁（如 14 天小时级超额收益、单侧符号显著性检验、最大回撤约束）判定的优胜挑战者策略（Gen N+1）触发采纳（Adoption）时，传统粗暴交接逻辑通常要求母体策略全部平仓（Drain all positions），同时子策略从零建仓（Buy all target positions）。

这种传统交接模式存在严重缺陷：
1. **双倍摩擦损耗**：母体卖出支付印花税、佣金与滑点，挑战者买入再次支付佣金与滑点；
2. **市场冲击与冲击成本**：短时间内大额集中双向交易对盘口造成不必要的冲击；
3. **A 股现货规则冲突**：在 T+1 交易交收制度下，日内卖出再买入或同一标的日内对冲易造成资金锁定与流动性卡顿。

本合同规范并实现**赛马接力阶段的「两腿重合期净额平滑换仓 (Position Netting & Smooth Relay Handover)」**系统，消除非必要的双向换手，最大化保留共有持仓，平滑完成母子策略资金与头寸交接。

## 2. 核心规范与验收指标

### 2.1 交集标的净额保留 (Position Netting)
- **净额算法**：
  给定母策略当前持仓向量 $P = \{s: q_p\}$ 与挑战者目标持仓向量 $C = \{s: q_c\}$：
  - 交集保留量：$Q_{\text{retain}}(s) = \min(q_p(s), q_c(s))$（当 $q_p, q_c > 0$ 时）；该部分头寸在账户间直接划转/保留，零交易费，零滑点；
  - 净额调仓向量：$\Delta(s) = q_c(s) - q_p(s)$；
    - $\Delta(s) > 0$：生成增量买入指令（Buy）；
    - $\Delta(s) < 0$：生成减量卖出指令（Sell）；
    - $\Delta(s) = 0$：维持持仓不变（Hold）；
- **换手节约率 (Turnover Reduction Ratio)**：
  $$\text{Reduction Ratio} = 1 - \frac{\sum |\Delta(s)| \cdot \text{price}(s)}{\sum |q_p(s)| \cdot \text{price}(s) + \sum |q_c(s)| \cdot \text{price}(s)}$$
  在重合资产组合中，换手节约率应显著达到 $\ge 40\%$ 至 $80\%$；
- **摩擦成本节约审计**：基于 `AShareMarketRules`（或标准市场成本），精确计算避免双向交易所节约的印花税、佣金及滑点金额（以 CNY/USDT 计价）。

### 2.2 差额平滑下单调度器 (Smooth Relay Slicing)
- **重合期分批调度**：
  - 支持将差额 $\Delta(s)$ 分解为 $K$ 期执行切片（$K \in [2, 10]$，默认 5 期）；
  - 每期执行比例（默认均匀 TWAP，支持递增权重）；
- **A 股交易规则硬约束**：
  - 买入指令严格向下取整至 100 股整数手（Lot Size = 100），尾数在最后一期或合规处理；
  - 卖出指令支持零股（Odd Lot）全部卖平；
  - 涨跌停保护：触及涨停禁止追买，触及跌停禁止强卖；
- **确定性加密收据**：根据交接计划参数、初始持仓、目标持仓生成确定性 `plan_sha256` 签名。

### 2.3 状态机与接力编排
- **生命周期状态**：
  - `PLANNED`：交接计划已计算并锁定；
  - `IN_PROGRESS`：正在执行切片调仓；
  - `COMPLETED`：全量切片完成，挑战者正式成为 Primary 主力策略，母策略状态转为 `COMPLETED` 并冻结归档；
  - `ABORTED`：发生风控熔断，停止后续切片并回滚/报警。
- **系统集成**：
  - `RaceJudgeDaemon`：在 `adopt` 阶段自动触发净额换仓计划创建与切片推进，并在飞书告警卡片中展示换手节省率与节约摩擦成本；
  - `QuantLabTargetAdapter`：在纸盘模拟中支持 `paper_relay_netting_plan` 接口；
  - `PortfolioCoordinatorService`：提供换仓计划查询与推进接口。

## 3. 产出清单

1. `backend/src/hypertrade/paper/relay_netting.py`：净额对冲计算核心、切片生成器与持久化服务；
2. `backend/src/hypertrade/paper/race_judge.py`：注入净额换仓服务与飞书卡片指标展示；
3. `backend/src/hypertrade/targets/quantlab.py`：QuantLab 适配器净额计划支持；
4. `backend/src/hypertrade/paper/portfolio.py`：组合协调器换仓接口；
5. `tests/test_position_netting_relay.py`：单元与集成测试。
