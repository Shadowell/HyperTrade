# Plan 022: BitPro 模拟盘异常监控与 HyperTrade 策略自愈引擎直连打通

## 1. 架构总览

```
  BitPro 模拟盘实例 (例: #333 KAITO EMA5/20)
       │ (胜率 32.4%, 回撤 8.76%, 交易 451 笔)
       ▼
  PaperAnomalyDetector (捕获 WIN_RATE_DECAY / DRAWDOWN)
       │
       ▼
  BitProSelfHealingBridge (新桥接组件)
       │ 提取因果约束，构建 7 维归因报告
       ▼
  SelfHealingEvolutionEngine (扩展支持 CTA/EMA 趋势策略族)
       │ - fast_window: 5 -> 8, slow_window: 20 -> 25
       │ - hard_stop_loss_pct: 0.04 -> 0.025
       │ - 提取 Reflexion 负向反思约束
       ▼
  BitPro MCP / Repository 同步
       │ - 为 #333 登记/更新合规候选变体 (如 #518)
       │ - 注入 _research_source_binding & parameter_intents
       │ - 派发飞书全息反思通知卡片
       ▼
  /api/v1/arc/evolution/scan & BitPro 前台展示
       - status: "opportunity"
       - 7 维归因报告全部填充真实证据，彻底告别“证据核验中”
       - 变体快照展示 Gen 2 候选策略与 Git-Diff 对比
```

## 2. 详细技术拆解

### Step 1: 扩展 `SelfHealingEvolutionEngine` 支持 CTA/EMA 策略 (`hypertrade.paper.self_healing`)
- 新增 `cta_trend_following` / `ema_trend` 变异逻辑：
  - 调整快慢线周期：`fast_window` 适度放大（如 $5 \rightarrow 8$ 或 $+3$），`slow_window` 适度放大（如 $20 \rightarrow 25$ 或 $+5$）；
  - 收紧保护性止损：`hard_stop_loss_pct` 降至原有的 0.7~0.8 倍；
  - 收紧浮盈回撤：`profit_peak_pullback_pct` 调低；
- 实现 `heal_bitpro_strategy(strategy_record, snapshot_metrics)`：
  - 支持直接处理从 BitPro 读入的策略配置与异常指标；
  - 产出包含 7 维分析的因果归因字典与变体结构。

### Step 2: 实现 BitPro 异常监控直连桥接 (`BitProSelfHealingBridge` in `hypertrade.bitpro.paper_monitor`)
- 重构 `IncrementalEvolutionTrigger`，将其下层逻辑从依赖重型 AVO 演化切换为直接驱动 `SelfHealingEvolutionEngine`；
- 构建 7 维归因报告生成器（`build_detailed_attribution_report`）：
  - `entry_timing`：均线交叉滤波分析；
  - `exit_timing`：硬止损与移动止盈有效性分析；
  - `costs`：手续费与滑点摩擦占比；
  - `long_short`：多空偏好失衡诊断；
  - `holding_duration`：持仓周期分布；
  - `sample_coverage`：样本量统计与置信度判定；
  - `regime`：当前市态归因（如高波震荡）。

### Step 3: 优化 `/api/v1/arc/evolution/scan` 兜底机制 (`hypertrade.arc.evolution`)
- 在 `_scan()` 流程中，当目标策略满足异常监控条件或请求诊断时：
  - 若严格 7+7 天同窗基线缺失，不再抛出 `upstream_read_unavailable`；
  - 优雅降级调用 `BitProSelfHealingBridge`，返回结构完整的 `attribution_report` 与 `status="opportunity"`；
  - 注入候选变体元数据，让 BitPro 界面接收到完整的诊断结论。

### Step 4: BitPro 端策略与候选变体联动核验
- 确保变体策略在 BitPro 端拥有标准的 `parent_strategy_id`, `generation`, `parameter_intents` 元数据；
- 优化 BitPro 前端在详情页对变体候选的感知逻辑，使其能够稳定展示。

### Step 5: 单元测试与端到端验证
- 编写 `tests/test_bitpro_self_healing_bridge.py`，验证从 BitPro 策略指标异常到自愈变体生成的全链路；
- 运行 `./scripts/check.sh` 确保 100% 通过。
