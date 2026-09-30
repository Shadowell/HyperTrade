# 018 全自动回测矩阵与参数自动寻优沙盒规格 (Automated Backtest Matrix & Parameter Optimization Sandbox)

## 1. 业务目标与背景

在量化交易与自主进化系统（HyperTrade）中，策略从概念诞生到进入实盘，最为耗时且核心的环节是**“参数寻优与防过拟合检验”**：
1. **人工调参瓶颈**：传统流程依赖量化研究员在本地或 Jupyter Notebook 中反复手动调整参数并执行回测，耗时且容易遗漏优质解空间；
2. **单周期/单品种偏见**：某一参数在 15m 周期或单一行情下表现优异，往往在 1h 或震荡行情中迅速失效（Curve-Fitting 严重）；
3. **缺乏自主进化闭环**：自进化 Agent（无论是接入 BitPro 已有策略还是 LLM 自由代码合成策略）需要具备自主提取参数空间、多维度并行回测、Walk-Forward (WFO) 样本外验证、参数敏感度（平坦度检验）评估，并自动筛选出最优且稳健的参数组，沉淀至策略仓库，且直接兼容 BitPro / QuantLab 运行。

本规格交付 **Phase 2: 全自动回测矩阵与参数自动寻优沙盒**，使 Agent 具备对任意 BaseStrategy 进行全自主参数寻优、多维回测矩阵评估、抗过拟合打分与配置导出的完整工业级能力。

---

## 2. 需求定义 (Requirements)

### FR-001：参数搜索空间与智能变异生成器 (Parameter Space & Mutation Engine)
- 支持从策略类（通过 AST 解析或已声明的配置规范）自动推导超参数空间，也支持显式定义：
  - `IntParam(name, min_val, max_val, step=1)`
  - `FloatParam(name, min_val, max_val, step=None, scale="linear"|"log")`
  - `CategoricalParam(name, choices=[...])`
- 支持参数间逻辑约束（Constraints，例如 `fast_period < slow_period`，`stop_loss < take_profit` 等自定义校验）；
- 支持三种寻优与变异策略：
  1. `grid`：网格穷举，适用于参数维度较低（<= 3 维）时精确遍历；
  2. `random`：拉丁超立方/均匀随机采样，适用于高维参数空间在大样本下的快速探索；
  3. `llm`：LLM 指导的启发式变异（LLM-Guided Mutation），结合历史试验的成败原因与性能瓶颈，自主提出针对性的参数修正假设并向高潜区域收敛。

### FR-002：多周期/多品种/多市态回测矩阵执行器 (Multi-Dimensional Backtest Matrix)
- 构建多维回测矩阵：`Symbols x Timeframes x ParameterVariants`；
- 支持常用交易周期：`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`；
- 适配历史 K 线源（内存模拟/BitPro 归档/实时数据），使用 `hypertrade.backtest.candidate.replay_candidate_backtest` 毫秒级快速回放器；
- 采集全套量化表现指标：
  - `total_return_pct`（总收益率 %）
  - `annualized_sharpe`（年化夏普比率）
  - `sortino_ratio`（索提诺比率，仅下行波动率惩罚）
  - `calmar_ratio`（卡玛比率，年化收益 / 最大回撤）
  - `max_drawdown_pct`（最大回撤 %）
  - `win_rate`（胜率 %）
  - `profit_factor`（盈亏比，总盈利 / 总亏损）
  - `trade_count`（交易笔数）
  - `avg_holding_bars`（平均持仓周期数）
  - `turnover` & `exposure_rate`（换手率与资金暴露时间占比）

### FR-003：Walk-Forward 滚动验证与参数敏感度抗过拟合沙盒 (WFO & Overfitting Guard)
- **样本内外切分 (IS / OOS)**：
  - 自动将历史序列划分为样本内训练集（In-Sample, 如前 70%）与样本外测试集（Out-of-Sample, 如后 30%）；
- **参数敏感度检验 (Parameter Sensitivity / Ridge Test)**：
  - 对样本内排名前列的最优参数组合，在其邻域（±5% ~ ±10% 扰动）自动生成扰动变体并回测；
  - 若扰动后绩效暴跌（> 35% 性能衰减），打上“尖刺刀锋过拟合 (Knife-edge Overfitting)”标签，予以严重扣分；
  - 若邻域表现平缓稳定（Performance Plateau），赋予稳健度奖励加分；
- **综合稳健度评分卡 (Composite Robustness Score, 0 - 100)**：
  - 加权模型：夏普与收益质量（35%）、最大回撤与卡玛防御（25%）、OOS 样本外衰减容忍度（20%）、参数敏感度平坦度（20%）；
  - 只有综合得分 >= 70 且交易次数满足置信度的参数组合，才准予被标记为 `OPTIMIZED_PROMOTABLE`。

### FR-004：QuantLab / BitPro 双兼容策略配置导出 (Workbench Export)
- 寻优获胜的最佳参数组，支持一键导出为标准的 QuantLab / BitPro 配置文件格式（JSON/YAML）；
- 导出内容包括：
  - 最终优化参数字典；
  - 推荐运行品种与最佳时间周期；
  - 回测基准指标对照表；
  - 建议止损、最大风控敞口与动态资金分配参数。

### FR-005：持久化模型与审计 (Persistence & Trial Ledger)
- 数据库新增模型：
  - `OptimizationStudy`（记录一次寻优研究：ID、策略标识/源码哈希、寻优目标、空间定义、状态、最优试验 ID、最优参数、耗时、配置）；
  - `OptimizationTrial`（记录具体参数试验：ID、Study ID、试验序号、参数字典、IS 指标、OOS 指标、敏感度分、综合得分、状态）；
- 严格遵循表名前缀与迁移规范（`opt_` 表前缀）。

### FR-006：REST API 与 CLI 控制端交互
- **REST API**：
  - `POST /api/research/optimization/start`：发起一次策略参数寻优矩阵研究；
  - `GET /api/research/optimization/{study_id}`：获取寻优状态、进度、最优参数与 Pareto 前沿；
  - `GET /api/research/optimization/{study_id}/trials`：获取该研究的所有试炼指标明细；
  - `POST /api/research/optimization/{study_id}/export`：导出为 QuantLab / BitPro 格式配置。
- **CLI**：
  - `hypertrade optimize run`：命令行发起多周期/多参数寻优；
  - `hypertrade optimize list`：列出历史寻优任务；
  - `hypertrade optimize status <study_id>`：查看寻优进度与最优试验；
  - `hypertrade optimize export <study_id>`：导出至本地文件。

---

## 3. 验收标准 (Acceptance Criteria)

1. **单元测试覆益**：
   - 参数空间定义、约束校验与网格/随机/LLM变异生成器测试 100% 通过；
   - 快速回测矩阵执行器（多周期、多标的、全套量化指标）测试 100% 通过；
   - Walk-Forward 滚动验证与参数敏感度（平坦度）检验算法逻辑测试 100% 通过；
   - QuantLab & BitPro 格式导出器测试 100% 通过。
2. **全流程端到端检验 (E2E)**：
   - 对已有策略或自合成代码执行一次完整寻优，包含生成试炼、IS/OOS 回测、敏感度扰动分析、评定综合得分、持久化并在 API/CLI 正常呈现。
3. **零回归与质量门禁**：
   - `./scripts/check.sh` 完整通过（包含 ruff, mypy, pytest 全量绿灯）。
