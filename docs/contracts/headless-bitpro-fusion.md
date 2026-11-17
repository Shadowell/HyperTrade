# Sprint Contract — HyperTrade 无头研究引擎收口与 BitPro 融合契约

> 状态：Active（2026-11-18）
> 分支：`codex/headless-engine-and-bitpro-fusion`

## Goal

将 HyperTrade 明确收口为受治理的「无头策略研究与进化引擎」（由 BitPro `/ai-lab` 与 `/evolution` 承担唯一人工操作台），在生产模式停用冗余本地行情摄入、本地 Paper 撮合与自主脉冲循环、为非关键扫描循环启用启动错峰以消除冷启动 `t=0` 并发峰值，并修复 `bitpro/mcp.py` 跨系统监控 `monitor_data_gap` 持续误报，同步 HyperTrade 前端迁移引导及全套设计文档。

## In Scope

1. **无头研究引擎模式开关与容器资源边界**（`config.py`, `.env.example`, `docker-compose.yml`）：
   - `Settings` 新增 `headless_mode`（`HYPERTRADE_HEADLESS_MODE`，代码默认 `False` 兼容已有单测与本地独立模式）、`market_ingestion_enabled`（`MARKET_INGESTION_ENABLED`，默认 `True`）、`worker_startup_stagger_enabled`（`WORKER_STARTUP_STAGGER_ENABLED`，默认 `True`）与 `worker_startup_stagger_delays`（`WORKER_STARTUP_STAGGER_DELAYS`）。
   - `.env.example` 配置 `HYPERTRADE_HEADLESS_MODE=true`；`docker-compose.yml` 为 `api` 与 `worker` 配置 `HYPERTRADE_HEADLESS_MODE: ${HYPERTRADE_HEADLESS_MODE:-true}`，并设定内存硬限 `api mem_limit: 2g`、`worker mem_limit: 3g`。
2. **Worker 循环裁剪与冷启动错峰**（`worker.py`）：
   - `build_loops(db, settings)` 在 `headless_mode=True` 时停用 `market_ingestion`、`market_rest_supplement`、`paper_trading`、`autonomous_market_pulse`；保留 `rag_scanner`、`monitor_scheduler`、`agent_task_worker`、`mission_worker_*`、`research_trigger`、`arc_observation`、`arc_evolution`、`arc_auto_review`、`arc_paper_effect_reconcile`、`arc_meta_tuning`、`cognitive_memory_replay`、`heartbeat`、`avo_research`、`self_healing_evolution`、`race_judge`、`memory_distillation`。
   - `market_ingestion_enabled=False` 在非无头模式下亦可独立停用 `market_ingestion` 与 `market_rest_supplement`。
   - `worker.main()` 仅在进程首次启动时对非关键扫描循环应用错峰延迟：`arc_evolution`（2s）、`arc_observation`（5s）、`cognitive_memory_replay`（8s）、`arc_meta_tuning`（12s）、`rag_scanner`（15s）；`supervise` 重启与直接调用循环的单测不触发启动延迟。
3. **跨系统监控 `monitor_data_gap` 误报治理**（`bitpro/mcp.py`）：
   - `_strategy_item` 与 `_paper_monitor_summary` 兼容读取运行策略清单中的 `total_pnl_pct`、`return_pct`、`cumulative_return_pct`、`pnl_pct`、`paper_metrics.total_pnl_pct`、`max_drawdown`、`max_drawdown_pct`、`paper_metrics.max_drawdown_pct`。
   - 当轻量级 `strategy_search(status=running)` 目录暂缺逐策略指标而主 `paper_dashboard` 指标可用时，仅保留 `level="info"` 的 `missing_strategy_metrics` 提示，不写入 `data_gaps`，避免 `MonitorService`（`mon_bitpro_paper_all`）每 5 分钟产生 `WARNING monitor_data_gap` 误报；当 `dashboard` 与目录双缺时继续上报 `data_gaps`。
4. **前端无头引导与全套文档同步**（`frontend/`, `README*.md`, `docs/`）：
   - HyperTrade 前端主工作区顶部显眼展示无头研究引擎提示与跳转 BitPro `/ai-lab`、`/evolution` 链接。
   - 只读盘点 HyperTrade 开放 Dependabot PR `#112`~`#117` 状态并记录至 `docs/progress.md`。

## Out of Scope

- `arc/store.py`、`arc/router.py`、`arc/observation.py`、`arc/evolution*.py`、`memory/arc_integration.py` 等事件加载与 API 内存优化（由 `ht-core` 独立分支推进）。
- 合并或修改 Dependabot PR `#112`~`#117` 与生产锁文件。
- BitPro 仓库自身后端与前端实现（由 `bp-backend`、`bp-ui-docs` 推进）。

## Done Means

1. `tests/test_worker_headless_mode.py`、`tests/test_bitpro_mcp_inventory_metrics.py`、`tests/test_bitpro_mcp_adapter.py` 与既有 worker/monitoring 套件全部通过。
2. 前端 `eslint`、`vitest`（含无头引导横幅用例）与 `tsc --noEmit && vite build` 全绿。
3. `LC_ALL=en_US.UTF-8 ./scripts/check.sh` 与 GitNexus `detect-changes` 校验通过，文档与代码完全同步。

## Safety Boundaries

- `Settings.headless_mode` 代码默认保持 `False`，确保独立开发与既有测试向后兼容；生产环境通过 `.env` 与 `docker-compose.yml` 默认开启 `true`。
- 禁止以“忽略全部 `data_gaps`”掩盖真故障：仅当主 `paper_dashboard` 已具备实时净值/收益/回撤数据时豁免轻量目录缺明细项。
