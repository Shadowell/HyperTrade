# Spec 020: 进阶实盘/模拟盘执行器升级与策略动态协同总线 (Multi-Strategy Dynamic Execution & Risk-Parity Allocation Gate)

## 1. 业务背景与问题 (Context & Problem)

在 HyperTrade 现有架构中：
1. **执行器信号源单一硬编码**：`hypertrade/paper/engine.py` 中的 `PaperSignalEngine` 仅支持静态的 `change_utc0_pct >= 3%` 规则，无法直接加载、执行已由寻优矩阵（Spec 018）和自主反思进化闭环（Spec 019）产出的自适应策略（如 `rsi_reversal`、`momentum_breakout`、`macd_trend` 等）；
2. **资金分配缺乏风险平价（Risk Parity）**：现有仓位计算直接采用平均名义资金切分（`equity * max_symbol_pct`），忽视了高 Beta 山寨币与低波动大盘币（BTC/ETH）的巨大波动率差异，极易因单一边缘币种剧烈波动导致组合整体回撤超标；
3. **持仓缺乏持续逐笔盯盘与自动化止盈止损 Bracket Orders**：当前仅在操作员主动调用 `close()` 时平仓，缺乏持续的盯市估值（Mark-to-Market）、移动止损（Trailing Stop-Loss）、阶梯止盈与信号反转平仓机制；
4. **缺乏从模拟盘到实盘的渐进式晋升阶梯与熔断降级门禁（Progressive Promotion Gate）**：策略缺乏分阶段的风险预算保护（`INCUBATING` -> `PAPER_OBSERVING` -> `CANARY_LIVE` -> `CONTROLLED_LIVE` -> `FULL_LIVE`）。当策略发生连续亏损或回撤超标时，缺乏自动熔断降级并触发 Reflexion 负向反思与飞书告警的联动。

本项目实现「多策略动态协同执行器 + 风险平价资金分配 + 动态盯盘阶梯止损 + 渐进式晋升熔断门禁」，为 HyperTrade 打造生产级实盘/模拟盘执行内核。

---

## 2. 核心功能与指标 (Core Capabilities)

### 2.1 多策略动态信号引擎 (`MultiStrategySignalEngine`)
* 支持策略统一协议接入（`ExecutionStrategy` 协议），包括：
  * `RsiReversalExecutionStrategy`：基于动态自适应 RSI + 波动率布林带/均线过滤，产生超买超卖反转信号；
  * `MomentumBreakoutExecutionStrategy`：基于唐奇安通道/EMA 突破的趋势动量信号；
  * `MacdTrendExecutionStrategy`：基于 MACD 柱状图背离与双线穿越的趋势信号；
  * 支持注册自定义进化策略候选（`CandidateEvolutionStrategy`）；
* 统一产生结构化信号 `StrategySignal`：
  * `strategy_key`: 策略标识；
  * `inst_id`: 交易标的（如 `BTC-USDT-SWAP`）；
  * `side`: `"long"` 或 `"short"`；
  * `conviction`: 信号置信度（0.0 ~ 1.0）；
  * `stop_loss_pct`: 止损百分比；
  * `take_profit_pct`: 止盈百分比；
  * `reason`: 信号生成依据。

### 2.2 风险平价资金分配器 (`RiskParityAllocator`)
* 引入逆波动率风险平价（Inverse Volatility Weighting）：
  * 计算标的的历史波动率 $\sigma_i$（基于 Rolling Returns 标准差或 ATR 归一化）；
  * 基础风险权重 $w_i \propto \frac{1}{\sigma_i}$，使得各资产对组合的边际风险贡献趋于对齐；
* 引入策略绩效加权：结合策略近期的 Sharpe、胜率及信号置信度 $c$ 进行权重二次调整；
* 引入资产相关性抑制（Correlation Damping）：当高度正相关资产（如 BTC 与 ETH）同时产生同向信号时，自动衰减后续仓位，防止单向敞口过度集中；
* 计算最终开仓名义价值（`target_notional`），严格受限于单币种最大敞口与账户总杠杆。

### 2.3 动态盯盘、实时盯市与 Bracket Order 退出机制
* 在 `PaperTradingService.run_once()` 中实现三阶段闭环：
  1. **Mark-to-Market 估值**：读取最新行情报价值，逐笔更新所有 open position 的 `mark_price` 与 `unrealized_pnl`，实时同步 `session.equity = session.cash + sum(unrealized_pnl)`；
  2. **Bracket Order 自动止盈止损监控**：
     * 触发止损价：立即市价平仓，记录 `stop_loss` 平仓事件；
     * 若单笔亏损超过账户风控红线（如 > 5%），自动联动 Reflexion 提炼负向约束并向飞书推送告警卡片；
     * 触发止盈价：自动分批/一次性锁定利润，记录 `take_profit` 平仓事件；
  3. **多策略新信号评估与开仓撮合**：执行 `MultiStrategySignalEngine`，通过 `RiskParityAllocator` 计算头寸并执行模拟撮合。

### 2.4 渐进式晋升阶梯与自动熔断降级门禁 (`ProgressiveStageGate`)
* 策略执行生命周期五阶段：
  * `INCUBATING` (研究沙盒孵化)
  * `PAPER_OBSERVING` (模拟盘观测，最大可用总资金 10%)
  * `CANARY_LIVE` (金丝雀试跑，最大可用总资金 20%)
  * `CONTROLLED_LIVE` (受控实盘，最大可用总资金 50%)
  * `FULL_LIVE` (全量实盘，100% 可用资金)
  * `DEGRADED` (熔断降级状态，禁止开新仓，仅允许减仓/平仓)
* 自动晋升考核规则：
  * 模拟盘观测满足：交易笔数 >= 15，胜率 >= 55%，盈亏比 >= 1.5，最大回撤 <= 5% -> 自动提议/升级至 `CANARY_LIVE`；
* 自动熔断与降级保护（Circuit Breaker）：
  * 当策略累计回撤超过 8% 或连续亏损达到 4 笔时，系统触发硬熔断，立即将状态从实盘降级为 `DEGRADED` / `PAPER_OBSERVING`；
  * 自动触发 Reflexion 反思总账，派发飞书交互式卡片告警。

### 2.5 REST API 与 CLI 运维交互
* REST API:
  * `GET /api/portfolio/summary`: 获取多策略组合全景、净值、未实现盈亏、保证金使用率与风险平价敞口分布；
  * `GET /api/portfolio/strategies`: 获取当前总线接入策略列表、运行阶段、风险权重与表现；
  * `POST /api/portfolio/strategies/{key}/stage`: 手动/受控切换策略运行阶段；
  * `POST /api/portfolio/rebalance`: 触发组合风险平价重平衡计算；
* CLI 命令:
  * `hypertrade portfolio summary`
  * `hypertrade portfolio strategies`
  * `hypertrade portfolio rebalance`
  * `hypertrade stage set --strategy <key> --stage <stage>`

---

## 3. 安全与架构边界 (Boundaries & Safety)
1. **资本安全铁律**：未通过晋升门禁的策略严禁分配超过 `PAPER_OBSERVING` 阶段的额度；
2. **算子幂等性**：每次 tick 运行必须保证幂等，避免重复开仓或重复平仓；
3. **向后兼容性**：保留原有 `PaperTradingService` 接口，原有的重置、平仓、暂停、恢复接口行为保持 100% 兼容。
