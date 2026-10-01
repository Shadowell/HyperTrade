# Spec 021: 动态策略持久化注册表、自愈进化守护进程与前台量化指挥台 (Dynamic Strategy Registry, Self-Healing Evolution Daemon & UI Quantum Dashboard)

## 1. 业务背景与问题定义

在 Spec 018、019 与 020 中，HyperTrade 分别实现了：
1. **全自动回测矩阵与参数自动寻优沙盒 (Spec 018)**：支持超参数空间采样、极速回测矩阵与抗过拟合稳健度评分；
2. **交易反思闭环与飞书实时告警联动 (Spec 019)**：实现事后因果归因、结构化负向约束提取与 RSI 变异演练；
3. **进阶实盘/模拟盘执行器与策略动态协同总线 (Spec 020)**：实现多策略并发信号评估、逆波动率风险平价分配、渐进式晋升门禁与逐笔盯市移动止损止盈。

然而，目前系统在自主进化落地应用中存在最后的“断点”：
1. **策略硬编码与静态装配**：`MultiStrategySignalEngine` 中的执行策略（`rsi_reversal`, `macd_trend`, `momentum_breakout_v1` 等）以静态代码形式注入，进化沙盒（`RsiEvolutionEngine` / `OptimizationService`）生成的最优变体无法动态持久化并直接注入实时信号总线；
2. **缺乏自愈闭环守护（Self-Healing Loop）**：当策略在实盘或模拟盘触发熔断降级（`DEGRADED`）时，虽然有飞书告警和反思约束，但缺乏自动化常驻守护进程去自动拾取失败反思、定向变异超参数、回测验证并通过新代系（Generation N+1）重新进入孵化与模拟观察期；
3. **前台缺少直观量化指挥台**：前台 `/portfolio` 页面缺少针对 Spec 020 实时资产（Equity/PnL）、10 大持仓实时盯市价值、策略晋升阶梯状态与一键重平衡/自愈触发的交易级监控 UI。

## 2. 核心架构目标

1. **动态策略持久化注册表 (`hypertrade.paper.registry`)**：
   - 提供 `StrategyRecord` 统一实体，包含策略 ID、策略类型、超参数集、当前运行阶段（`StrategyStage`）、代系编号（`generation`）、父代策略 ID、负向反思约束列表以及绩效统计；
   - 提供 `StrategyRegistry`，支持内存高速缓存与 JSON/DB 持久化存储；
   - 提供 `StrategyFactory`，支持根据策略类型（RSI、MACD、趋势突破、自定义）与超参数动态实例化执行策略；
   - 改造 `MultiStrategySignalEngine`，使其动态从 `StrategyRegistry` 加载处于激活态且阶段允许发信的策略。

2. **自愈进化中枢 (`hypertrade.paper.self_healing`)**：
   - 监听或定期扫描处于 `DEGRADED` 状态的策略；
   - 提取该策略关联的 Reflexion 归因原因与负向约束；
   - 结合历史市场行情调用进化器（如针对 RSI 家族的自适应变异、针对趋势突破的自适应周期调整）生成候选代系；
   - 进行样本内与样本外极速回测验证；
   - 若回测达标（夏普比率、胜率、最大回撤满足门禁），自动向 `StrategyRegistry` 注册新一代变体（如 `rsi_reversal_gen2`），初始状态设为 `PAPER_OBSERVING` 或 `INCUBATING`，并派发飞书自愈成功通知卡片。

3. **后台 Worker 自愈守护循环 (`hypertrade.worker`)**：
   - 在后台 Worker 中新增 `self_healing_evolution_loop()`，定期（如每 5 分钟）检查降级策略并触发自愈进化，防止单策略永久休克。

4. **REST API 与 CLI 运维支持**：
   - 暴露 `/api/portfolio/registry`、`/api/portfolio/strategies/{key}/evolve`、`/api/portfolio/evolution/history` 端点；
   - 扩展 `hypertrade portfolio registry list/evolve` 命令行交互。

5. **前台 Web 量化指挥台 (`frontend/src/`)**：
   - 在前端 `/portfolio` 区域打造双模态量化控制台：
     - **实时账户与多策略矩阵看板**：总权益、可用现金、已实现盈亏、实时未实现盈亏、名义总头寸、实时杠杆仪表盘；策略阶段阶梯徽章、各策略指标卡片与自愈进化按钮；
     - **持仓与成交实时监控流**：10 大持仓方向、开仓价、实时标记价、未实现盈亏及颜色指示；最新成交记录；手动触发全量盯市止损扫描与风险平价重平衡。

## 3. 验收标准

1. `StrategyRegistry` 正确持久化并支持动态热插拔；
2. `MultiStrategySignalEngine` 能够实时响应注册表中的策略变更；
3. 策略熔断后触发 `SelfHealingEvolutionEngine`，正确生成下一代变体并保留代系因果链；
4. REST API 与 CLI 功能完备并通过测试；
5. 前台 `/portfolio` 量化指挥台正常加载后端数据并支持交互；
6. `./scripts/check.sh` 质量门禁全绿（前端测试/构建/Lint，后端 Ruff/Mypy/Pytest 100% 通过）。
