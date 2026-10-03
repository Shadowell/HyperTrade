# Tasks 025: QuantLab 市场目标生产级适配与多资产自愈闭环

- [x] T001: 配置与目标注册表扩展 (`hypertrade.config`, `hypertrade.targets.registry`) <!-- id: T001 -->
  - 在 `Settings` 增加 `quantlab_mcp_url` 与 `quantlab_mcp_token`；
  - 放宽 `targets.registry` 中对 QuantLab 的惰性注册判断，允许按需注册。

- [x] T002: 增强 QuantLab 市场适配器与双模态 MCP 接口 (`hypertrade.targets.quantlab`) <!-- id: T002 -->
  - 实现基于 `McpContractClient` 的远程调用与本地仿真双模态；
  - 增加回测工具作业代理 (`backtest_start_job`, `backtest_get_job`)；
  - 导出并注册 `quantlab` 目标。

- [x] T003: 赛马仲裁中枢与记录支持 String 策略 ID 与 QuantLab 路由 (`hypertrade.paper.race_judge`) <!-- id: T003 -->
  - 升级 `RacePairRecord` 允许 `str` 类型的 `parent_strategy_id` 与 `challenger_strategy_id`，增加 `target_id`；
  - `RaceJudgeDaemon` 支持对 QuantLab 策略对进行前瞻交易日净值获取与交接。

- [x] T004: 股票/多资产专属自愈变异与 7 维因果归因 (`hypertrade.paper.self_healing`) <!-- id: T004 -->
  - 增加针对多因子选股、动量轮动与 A 股均线趋势策略的参数变异；
  - 注入 T+1 交易制度保护与单向做空保护；
  - 实现 `heal_quantlab_strategy()` 生成股票语义的 7 维归因报告与合规策略包。

- [x] T005: 单元测试与全量质量门禁验证 (`tests/test_quantlab_target_adapter.py`, `./scripts/check.sh`) <!-- id: T005 -->
  - 编写涵盖适配器、日历切分、变异规则、ID 兼容性与赛马仲裁的完整测试集；
  - 执行并通过 `./scripts/check.sh` 质量门禁。
