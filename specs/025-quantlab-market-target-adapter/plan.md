# Plan 025: QuantLab 市场目标生产级适配与多资产自愈闭环实施方案

## 架构拆解与实施步骤

### 1. 配置扩展与目标注册热加载 (`config.py` & `targets/registry.py`)
- 在 `hypertrade.config.Settings` 中增加 `quantlab_mcp_url` (默认 `http://127.0.0.1:8890/api/v1`) 与 `quantlab_mcp_token`；
- 在 `hypertrade.targets.registry` 中放宽 `get_market_target("quantlab")` 的注册条件，支持随时按需注册与获取。

### 2. QuantLab 适配器与标准 MCP 端口打通 (`targets/quantlab.py`)
- 增强 `QuantLabTargetAdapter`：
  - 支持通过 `McpContractClient` 调用标准 MCP 工具（`evolution_list_running_strategies`, `evolution_get_session_snapshot`, `evolution_get_equity_series`, `evolution_configure_paper`, `evolution_start_paper`, `evolution_stop_paper`, `evolution_list_trading_sessions`, `backtest_start_job`）；
  - 保留并完善高保真本地仿真模式（包含 A 股 20 交易日逐笔成交、印花税费与净值生成），确保断网或本地单元测试无需外部服务依赖；
  - 实现真实/仿真双模态统一工厂 `quantlab_adapter_factory()`。

### 3. 全链路 String 策略 ID 兼容与赛马裁决适配 (`paper/race_judge.py`)
- 将 `RacePairRecord` 中的 `parent_strategy_id` 与 `challenger_strategy_id` 类型从 `int` 升级为 `str`（自动对齐数字字符串或 QuantLab 命名空间 ID）；
- 增加 `target_id: str = "bitpro"` 字段；
- 在 `RaceJudgeDaemon` 中识别 `target_id == "quantlab"`，路由至 QuantLab 目标适配器与工具集（通过 `evolution_get_equity_series` 获取 A 股净值，调用 QuantLab 停止/交接接口）。

### 4. 股票/多资产专属自愈变异与 7 维因果归因 (`paper/self_healing.py`)
- 在 `SelfHealingEvolutionEngine` 中增加 `heal_quantlab_strategy()` 与多资产变异逻辑：
  - 多因子与动态池轮动策略（因子权重平滑、调仓周期拓宽至 10~15 交易日、缩减重仓股数量）；
  - A 股双均线与趋势策略（均线滤波平滑、止损收紧、跟踪止损锁定）；
  - 严格遵守 T+1 交易规则（周期 $\ge 1$ 天）与禁止裸卖空（单向多头）；
  - 生成针对股票市场的 7 维因果归因（选股时机、卖出择时、印花税滑点、仓位暴露、持仓周期、样本覆盖、指数市态）。

### 5. 单元测试与端到端验证 (`tests/test_quantlab_target_adapter.py`)
- 覆盖 QuantLab 档案与能力检查；
- 覆盖 14 交易日 `sessions` 日历生成与净值切分；
- 覆盖 A 股策略自愈变异（T+1 与多头约束）；
- 覆盖 String 策略 ID 在赛马裁决与接力中的兼容性；
- 运行 `./scripts/check.sh` 质量门禁验证。
