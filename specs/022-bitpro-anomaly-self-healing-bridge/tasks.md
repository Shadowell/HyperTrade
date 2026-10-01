# Tasks 022: BitPro 模拟盘异常监控与 HyperTrade 策略自愈引擎直连打通

- [ ] T001: 扩展 `SelfHealingEvolutionEngine` 支持 CTA/EMA 策略自愈变异与 7 维因果归因 (`hypertrade.paper.self_healing`) <!-- id: T001 -->
  - 实现针对 `cta_trend_following` / `ema_trend` 的超参数变异（EMA 周期平滑、止损收紧、跟踪止盈保护）；
  - 实现 `generate_7d_attribution_report()` 辅助方法，生成 7 维结构化诊断字典；
  - 实现 `heal_bitpro_strategy()`，支持从 BitPro 策略快照直接衍生 Gen N+1。

- [ ] T002: 实现 BitPro 异常监控与自愈桥接 (`hypertrade.bitpro.paper_monitor`) <!-- id: T002 -->
  - 增强 `IncrementalEvolutionTrigger`，桥接调用 `SelfHealingEvolutionEngine`；
  - 完善 `PaperAnomalyDetector`，在胜率、回撤或连亏达到阈值时派发自愈变异；
  - 建立与飞书卡片派发的紧密协同。

- [ ] T003: 优化 ARC 演化扫描服务，解决小币种证据缺失造成的诊断中断 (`hypertrade.arc.evolution`) <!-- id: T003 -->
  - 在 `EvolutionService._scan` 中，当 7+7 天基线缺失时优雅降级接入自愈归因引擎；
  - 输出包含完整 7 维诊断维度与 `status="opportunity"` 的结构体，避免返回 `upstream_read_unavailable`。

- [ ] T004: BitPro 侧候选策略元数据与前端加载打通 (`BitPro/frontend/src/pages/liveTrading/`) <!-- id: T004 -->
  - 确保变体策略在 BitPro 端具备合规的亲子元数据，使前台 `evolutionFamily.candidate` 能够正确解析；
  - 修复 BitPro 详情页加载策略时候选变体被漏拉的问题。

- [ ] T005: 单元测试、端到端集成验证与质量门禁 (`tests/`, `./scripts/check.sh`) <!-- id: T005 -->
  - 编写 `tests/test_bitpro_self_healing_bridge.py`；
  - 执行并通过 `./scripts/check.sh` 全量质量门禁。
