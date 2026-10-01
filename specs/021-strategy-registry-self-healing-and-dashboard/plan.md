# Plan 021: 动态策略持久化注册表、自愈进化守护进程与前台量化指挥台

## 1. 架构分解与文件映射

```
backend/src/hypertrade/
├── paper/
│   ├── registry.py           [NEW] StrategyRecord, StrategyRegistry, StrategyFactory
│   ├── self_healing.py       [NEW] SelfHealingEvolutionEngine, EvolutionEvent, HealedOffspring
│   ├── strategies.py         [MODIFY] MultiStrategySignalEngine dynamically integrates StrategyRegistry
│   ├── portfolio.py          [MODIFY] Integrate registry listing and self-healing trigger
│   └── service.py            [MODIFY] Pass registry context
├── worker.py                 [MODIFY] Add self_healing_evolution_loop
├── main.py                   [MODIFY] Add REST endpoints for strategy registry and evolution
└── cli.py                    [MODIFY] Add CLI subcommands for registry list/evolve

frontend/src/
├── App.tsx                   [MODIFY] Add Quantum Portfolio Dashboard in portfolio section
└── components/
    └── portfolio/
        └── QuantumPortfolioDashboard.tsx [NEW] Dashboard with real-time equity, strategies, positions, fills
```

## 2. 详细设计要点

### 2.1 动态策略注册表与工厂 (`hypertrade.paper.registry`)
- `StrategyRecord`:
  - `strategy_id: str` (如 `rsi_reversal_v1`, `rsi_reversal_v1_gen2`)
  - `strategy_type: str` (`rsi_reversal`, `momentum_breakout`, `macd_trend`, `utc0_momentum`)
  - `name: str`
  - `parameters: dict[str, Any]`
  - `stage: StrategyStage`
  - `generation: int`
  - `parent_strategy_id: str | None`
  - `reflexion_constraints: list[str]`
  - `performance_metrics: dict[str, Any]`
  - `is_active: bool`
  - `created_at: str`, `updated_at: str`
- `StrategyRegistry`:
  - 具备文件存储持久化（`data/strategy_registry.json` 或由配置指定的存储路径）与内存锁；
  - 自动预装系统默认 4 大核心策略基线（`rsi_reversal_v1`, `momentum_breakout_v1`, `macd_trend_v1`, `utc0_momentum_legacy`）；
  - 提供 `register()`, `get()`, `list_active()`, `update_stage()`, `update_metrics()`, `archive()`；
- `StrategyFactory`:
  - 将 `StrategyRecord` 映射转换为可执行的 `ExecutionStrategy` 实例。

### 2.2 自愈进化引擎 (`hypertrade.paper.self_healing`)
- `SelfHealingEvolutionEngine`:
  - 扫描处于 `DEGRADED` 阶段的策略记录；
  - 读取策略的超参数与历史负向约束（来自 `ARCReflexionLedger`）；
  - 进行受约束的参数变异：
    - RSI: 调整 `oversold` / `overbought`，收紧 `stop_loss_pct`，优化 `ema_filter_period`；
    - 趋势突破: 调整 `lookback_period`，优化移动止损；
    - MACD: 微调快慢线周期；
  - 对近期典型 K 线数据执行快速回测检验；
  - 若满足抗过拟合门禁，构造 `new_gen = record.generation + 1`，生成新策略 ID（如 `f"{parent_id}_gen{new_gen}"`）；
  - 自动向 `StrategyRegistry` 注册为 `PAPER_OBSERVING` 或 `INCUBATING` 状态；
  - 将原策略标记为 `is_active = False` 或保留为 `DEGRADED` 作为对照；
  - 派发飞书通知卡片。

### 2.3 前台量化指挥台 (`QuantumPortfolioDashboard.tsx`)
- 包含：
  - 账户总览区（Equity, Cash, Realized PnL, Unrealized PnL, Total Notional, Leverage Ratio Gauge）；
  - 策略阶梯与自愈矩阵卡片（展示策略类型、代系、阶段、胜率、盈亏比、回撤、操作按钮：演化自愈、阶段调整）；
  - 实时持仓盯市表格（标的、多空、数量、开仓价、标记价、名义价值、未实现盈亏及正负着色）；
  - 最新成交与平仓事件流；
  - 顶部操作栏（刷新、一键重平衡与止损扫描）。
