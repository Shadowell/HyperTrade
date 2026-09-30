# 014 自主巡航盯盘守护进程与实时全息感知流任务清单 (Tasks)

## 任务执行顺序

- [ ] **T001: 真实外部新闻流与交易所公告适配器**
  - 在 `hypertrade.market.news` 中实现 `RssCryptoNewsSource`、`CryptoPanicNewsSource`、`OkxAnnouncementsSource` 与 `WhaleMovementSource`；
  - 增强 `NewsIngestionService`，增加并发聚合、超时保护与自动降级机制；
  - 编写单元测试 `tests/test_live_perception_sources.py`。

- [ ] **T002: 数据库持久化实体 AutonomousPulseCycle**
  - 在 `hypertrade.db` 中新增 `AutonomousPulseCycle` 表定义；
  - 在 `Database.create_tables` 中确保其自动初始化；
  - 编写数据库持久化与查询单元测试。

- [ ] **T003: 自主盯盘巡航中枢 AutonomousMarketPulseService**
  - 新建 `hypertrade.agent.pulse`，实现全息快照聚合、启发式初筛、LLM 自主决策推理与受控自主下单执行；
  - 接入 `AutonomousExecutionManager` 与硬件级风控熔断；
  - 编写单元测试 `tests/test_autonomous_pulse_service.py`。

- [ ] **T004: 后台 Worker 守护进程挂载与配置扩展**
  - 在 `hypertrade.config` 中增加巡航与感知参数；
  - 在 `hypertrade.worker` 中新增 `autonomous_market_pulse_loop` 并并入后台事件循环；
  - 编写 Worker 周期性驱动单元测试。

- [ ] **T005: API 端点与 CLI 交互支持**
  - 在 `hypertrade.main` 中暴露 `/api/agent/pulse/history`、`/api/agent/pulse/trigger`、`/api/market/news/latest`；
  - 在 `hypertrade.cli` 中增加 `pulse once` 与 `pulse history` 命令；
  - 编写 API 接口测试。

- [ ] **T006: 端到端集成测试与测试服务器验证部署**
  - 编写 `tests/test_autonomous_pulse_e2e.py`，串联感知流、盯盘巡航、自主决策、执行与审计查询；
  - 运行 `./scripts/check.sh` 确保 100% 测试通过、0 lint 报错、0 类型错误；
  - 同步代码至测试服务器 `tokyo`，重启服务并验证线上实时巡航运行状态。
