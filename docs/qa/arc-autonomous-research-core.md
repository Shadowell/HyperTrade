# ARC QA — Autonomous Research Core 合同收口

## Verdict

PASS。ARC 合同全部交付并验证：通用内核与领域合同、基因突变与红蓝对抗、归因反思账本、
模拟盘自动孵化以及端到端自主探索闭环均已实现并接入 FastAPI 主应用。`live_allowed`
恒为 `false`，合同声明的主网实盘禁用边界在代码与测试中保持成立。

## Contract Coverage

| 合同 Sprint | 交付 | 证据 | 结果 |
|---|---|---|---|
| 132 通用内核、领域合同与黄金测试 | `ARCController`、`ARCGoalV1`、`ARCBudgetV1`、`ARCSuccessCriteriaV1`、`PaperPreauthorizationV1`、状态机与事件归约 | `arc/contracts.py`、`arc/controller.py`、`tests/test_arc_kernel.py` | PASS |
| 133 策略基因突变与红蓝对抗引擎 | `ARCGeneticMutator`、`ARCAdversarialEngine`、`BlueTeamQuant`、`RedTeamQuant`、`MCTSNode` | `arc/mutation.py`、`arc/adversarial.py`、`arc/mcts.py`、`tests/test_arc_adversarial.py`、`tests/test_arc_mcts.py` | PASS |
| 134 因果归因反思账本与经验继承 | `ARCReflexionLedger`、多 Regime 归因、Negative Constraints 注入下一轮 | `arc/reflexion.py`、`tests/test_arc_reflexion.py` | PASS |
| 135 自动模拟盘孵化与端到端闭环 | `ARCPaperIncubationResolver`、candidate-bound 窄授权派生、端到端验收 | `arc/incubation.py`、`arc/router.py`、`tests/test_arc_acceptance.py` | PASS |

## SOTA 演进 Phase 覆盖（2026-07-30 批次）

| Phase | 交付 | 证据 |
|---|---|---|
| 1 模拟盘数据闭环与自动重练 | `PaperObservationMonitorDaemon`、`IncrementalEvolutionTrigger` | `tests/test_arc_paper_monitor.py` |
| 2 高阶量化因子算子库 | orderbook imbalance / VWAP zscore / ATR channel | `tests/test_arc_higher_order_factors.py` |
| 3 红队蒙特卡洛参数抖动与黑天鹅矩阵 | 100 次抖动、历史黑天鹅重放、滑点摩擦 | `tests/test_arc_adversarial_monte_carlo.py` |
| 4 并行 MCTS 与分布式 MAP-Elites | `ARCParallelMCTSEngine`、线程安全 MAP-Elites 网格 | `tests/test_arc_parallel_mcts.py` |
| 5 组合级 MCTS 协同演化与低相关性分配 | Pearson 门禁、组合净 Sharpe 提升度 | `tests/test_arc_portfolio_mcts.py` |
| 6 宏观新闻与事件因果因子化 | `MacroEventCausalExtractor`、情绪偏置与仓位缩放 | `tests/test_arc_macro_event.py` |
| 7 Live Canary 金库与风险门禁管道 | `CanaryVaultPipeline` 分级晋升/紧急降级，**确定性策略对象，无实盘写路径** | `risk/canary.py`、`tests/test_arc_canary_vault.py` |

## Automated Evidence

- ARC 黄金测试 11 passed（kernel/adversarial/reflexion/mcts/skills/acceptance）。
- ARC 演进测试 20 passed（monte_carlo/portfolio_mcts/paper_monitor/higher_order_factors/
  canary_vault/parallel_mcts/macro_event）。
- 完整 `./scripts/check.sh`：frontend lint、frontend tests、production build、Ruff、严格
  mypy、871 Python pytest 全部通过。

## API Surface

- `POST /api/v1/arc/missions` 创建并后台触发自主探索循环。
- `GET /api/v1/arc/missions/{mission_id}` 读取 mission 投影与事件重放。
- `main.py:581` `app.include_router(arc_router)` 已注册；`arc/router.py` 编排
  Goal → Parallel MCTS → Blue Proposals → Red Attacks → Reflexion → AST Mutation →
  Voyager Skill Distillation → Auto Paper Launch。

## Safety & Boundary Evidence

- `ARCGoalV1.live_allowed: Literal[False] = False`（`arc/contracts.py:75`）——类型层面物理禁用实盘。
- `CanaryVaultPipeline` 只做确定性晋升/降级判定，没有任何 exchange/order/account 写路径。
- 模拟盘上线走 `PaperPreauthorizationV1` 预授权派生的 candidate-bound 窄授权。
- 本轮未启用 Testnet/Live/order/capital 任何新能力；生产 mainnet 边界保持不变。

## 附带修复：Outcome 日历过期回归

- 全量检查发现 `tests/outcome_fixtures.py` 硬编码
  `valid_until=datetime(2026, 8, 1)`，恰在 2026-08-01 触发 `valid_until <= now`
  判定证据过期，导致 Sprint 125 的 outcome/lesson 定向测试 9 个失败。
- 已改为 `datetime.now(UTC) + timedelta(days=30)` 相对有效期；显式过期用例保持
  固定时钟（与 Sprint 129 shadow portfolio 夹具修复同款处理）。修复后 871 passed 全绿。

## Residual Risk

- ARC Phase 7 CanaryVaultPipeline 是纯代码模型，`live_allowed=false`；实盘 Canary 的真正
  激活仍需北星 Sprint 132–134（LiveTradingMandate/Risk Engine、Live Canary、自主组合 Pilot）
  在 `Awaiting explicit owner approval` 获批后实施，本报告不构成 mainnet 授权。
- ARC mission 当前以进程内存 `_ARC_MISSIONS` 存储，未持久化到 PostgreSQL；多 worker /
  重启恢复场景尚未覆盖，属后续工程项，不影响合同验收。
