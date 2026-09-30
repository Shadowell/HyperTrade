# 014 自主巡航盯盘守护进程与实时全息感知流实现计划 (Plan)

## 1. 架构总览

```mermaid
flowchart TD
    subgraph ExternalFeeds [外部实时感知流]
        RSS[Crypto RSS Feeds] --> NewsSvc[NewsIngestionService]
        CryptoPanic[CryptoPanic API] --> NewsSvc
        OKXNotice[OKX Public Notice API] --> NewsSvc
        WhaleFeed[Whale Movement Alerts] --> NewsSvc
    end

    subgraph PerceptionBus [全息感知总线]
        NewsSvc --> SentAnalyzer[NewsSentimentAnalyzer]
        SentAnalyzer --> MktIntel[MarketIntelligenceService]
        OKXMarket[OKX Tickers & Candles & Funding] --> MktIntel
    end

    subgraph PulseDaemon [自主巡航中枢 AutonomousMarketPulseService]
        CronWorker[Worker pulse_loop / API trigger] --> PulseDaemon
        MktIntel --> PulseDaemon
        PulseDaemon --> FastFilter[启发式初筛 Heuristic Filter]
        FastFilter -->|有异动/强信号| LLMReasoning[Gemini 3.8 Flash High 决策]
        FastFilter -->|平淡无量| QuickHold[生成 HOLD 记录]
        LLMReasoning --> PulseDecision[生成结构化决策]
    end

    subgraph Execution [受控执行与审计持久化]
        PulseDecision -->|Confidence >= 0.70 & BUY/SELL| AutoExec[AutonomousExecutionManager]
        AutoExec --> RiskGuard[AutonomousCircuitBreaker]
        RiskGuard -->|通过| OKXClient[OKX Testnet/Live Client]
        PulseDecision --> PulseCycleDB[(AutonomousPulseCycle Table)]
        AutoExec --> PulseCycleDB
    end
```

---

## 2. 模块设计与变更范围

### 2.1 外部新闻源适配器 (`backend/src/hypertrade/market/news.py`)
- 实现 `RssCryptoNewsSource`：基于 `urllib.request` 解析主流加密媒体 RSS/Atom XML，提取 `title`, `link`, `pubDate`, `description`，自动归一化关联币种。
- 实现 `CryptoPanicNewsSource`：请求 CryptoPanic public developer feed，提取突发快讯及社区多空投票元数据。
- 实现 `OkxAnnouncementsSource`：请求 OKX 公告接口（`/api/v5/support/announcements` 或公告列表），解析新币上线与合约交割信息。
- 实现 `WhaleMovementSource`：大单与爆仓数据流，注入紧急度为 `breaking` 的事件。
- 升级 `NewsIngestionService`：支持 `poll_all_sources()`，自动捕获异常降级，防止单数据源网络超时阻塞。

### 2.2 数据库存储与实体模型 (`backend/src/hypertrade/db.py`)
- 新增 `AutonomousPulseCycle` 表：
  - `id`: 主键，`pulse_` 前缀 ID；
  - `trigger`: 触发方式 (`scheduled`, `event_driven`, `manual`)；
  - `symbols`: 扫描的币种列表；
  - `sentiment_summary`: 当期聚合市场情绪特征；
  - `decisions_json`: 针对每个标的的决策详情数组；
  - `orders_executed`: 实际触发并执行的订单回执列表；
  - `status`: `completed`, `skipped`, `error`；
  - `error_message`: 异常信息；
  - `duration_ms`: 耗时毫秒数。

### 2.3 自主盯盘巡航服务 (`backend/src/hypertrade/agent/pulse.py`)
- `AutonomousMarketPulseService`：
  - `collect_perception_snapshot(symbols)`：并发聚合行情、资金费、未平仓合约与舆情评分；
  - `evaluate_symbols(symbols, *, dry_run=False)`：执行启发式初筛 + LLM 推理；
  - `execute_decisions(decisions)`：调用 `AutonomousExecutionManager` 下发订单；
  - `record_cycle(...)`：持久化至 `AutonomousPulseCycle`。

### 2.4 后台 Worker 挂载与并发调度 (`backend/src/hypertrade/worker.py`)
- 新增 `autonomous_market_pulse_loop(db: Database)`：
  - 根据 `settings.autonomous_pulse_interval_seconds` 定时唤醒；
  - 捕获异常记录日志，确保常驻守护进程永不退出。
- 在 `run_worker()` 启动协程池中注册 `autonomous_market_pulse_loop`。

### 2.5 API 与 CLI 端点暴露
- `backend/src/hypertrade/main.py`：
  - 增加 `/api/agent/pulse/history`
  - 增加 `/api/agent/pulse/trigger`
  - 增加 `/api/market/news/latest`
- `backend/src/hypertrade/cli.py`：
  - 增加 `pulse once` 与 `pulse history`。

---

## 3. 风险与防御

1. **API 限流与断网防御**：
   - 外部 RSS/新闻接口全部设置 5 秒超时保护，并在 HTTP 异常或限流时自动 fallback 到内存缓存或内置 Mock 数据，绝不对外抛出未处理异常。
2. **LLM 决策幻觉与频次控制**：
   - 启发式初筛（Heuristic Filter）机制：若价格 15 分钟波动小于 0.1% 且无突发新闻，直接产生 HOLD 决策，避免每一分钟无意义消耗 LLM Token；
   - 所有生成的交易指令必须经过 `AutonomousExecutionManager` 和 `AutonomousCircuitBreaker` 的严格参数校验与日亏损硬顶，LLM 无权越权扩大仓位。
