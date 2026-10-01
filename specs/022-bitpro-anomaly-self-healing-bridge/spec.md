# Spec 022: BitPro 模拟盘异常监控与 HyperTrade 策略自愈引擎直连打通

## 1. 业务背景与问题定位

在当前的量化协同体系中，BitPro 负责托管运行实际的模拟盘/实盘策略实例（如 `#333 [合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版 · 100U`）。当策略在真实市场震荡中产生胜率衰减（如胜率 32.4%）或回撤扩大（如 30 日回撤 8.76%）时，BitPro 前端的“进化专区面板”陷入停滞：
1. **因果诊断盲区**：展示 `【Agent 评估结论】本轮全量扫描尚未给出当前策略的因果诊断... 建议继续积累样本`，7 大归因维度（入场时机、出场时机、交易成本、多空偏好、持仓周期、样本覆盖率、市场状态）全部退回兜底文本 `证据仍在核验，请继续观察`；
2. **变体候选缺失**：右侧变体快照展示 `暂无已登记候选变体`、`等待候选`；
3. **技术瓶颈根源**：
   - 底层 ARC 演化扫描（`_scan`）重度依赖 7+7 天完整无缺口的同窗真实基准数据与参数政策认证，在小币种或历史样本不满足苛刻条件时直接抛出 `upstream_read_unavailable` 导致诊断终止；
   - 异常监控事件未能直连 Spec 021 刚刚构建的高可用自愈变异引擎；
   - BitPro 前端在实例详情页定时轮询时仅拉取 `active` 状态策略，使得处于 `stopped` 状态的已创建候选变体被漏掉。

## 2. 核心设计目标

1. **异常监控直连自愈中枢**：
   - 将 `PaperAnomalyDetector`（回撤超标、胜率下滑、连续亏损、滑点激增）直接接入 `SelfHealingEvolutionEngine`；
   - 扩展自愈引擎，原生支持 CTA/EMA 趋势跟踪策略族（`fast_window`, `slow_window`, `hard_stop_loss_pct`, `atr_stop_mult`, `profit_peak_pullback_pct`）的自愈变异与约束提炼。
2. **多维因果诊断全息生成**：
   - 当调用 `/api/v1/arc/evolution/scan` 或后台巡检时，针对 BitPro 运行策略生成结构化、具有可解释性的 `attribution_report.dimensions`，完整覆盖 7 大维度，彻底替代“证据仍在核验”的盲态；
   - 将策略诊断状态标记为 `opportunity`，明确给出因果归因与自愈操作建议。
3. **闭环自动生成并登记候选变体**：
   - 自愈引擎通过 BitPro MCP 接口为异常策略创建或更新具有完整亲子绑定（`_research_source_binding`）的 Gen 2 变体策略，包含变异参数、`diagnosis` 和 `parameter_intents`；
   - 派发飞书全息交互卡片，通知交易员新代系变异体已就绪。
4. **BitPro 前台闭环呈现**：
   - BitPro 实例详情页能立刻渲染出 7 大归因维度的真实结论，右侧变体快照能正确识别并展示 Gen 2 候选策略及其参数 Git-Diff 对比。

## 3. 验收标准

- [ ] `PaperAnomalyDetector` 与 `SelfHealingEvolutionEngine` 建立直接桥梁，支持将 BitPro 实例异常转化为结构化负向约束；
- [ ] 自愈引擎扩展支持 CTA/EMA 趋势策略族变异，能够将 EMA5/20 激进版变异为平滑抗震荡的 EMA8/25 稳健版并收紧止损；
- [ ] `/api/v1/arc/evolution/scan` 针对 BitPro 异常策略输出包含完整 7 维归因与 `status="opportunity"` 的因果诊断；
- [ ] 变体策略在 BitPro 端具备合规的亲子元数据，使前台 `evolutionFamily.candidate` 能够正确解析；
- [ ] 全量 `./scripts/check.sh` 质量门禁 100% 绿灯通过；
- [ ] 经 GitHub PR 流程合入 `main` 并部署至生产验证。
