# 09 Frontend Harness / 前端 Harness

## English

The frontend is an operational **HyperMonitor Control-Plane Workbench** for HyperTrade's governed Agent Runtime and headless research/evolution engine—not a marketing page or a trading terminal. Legacy 9-tab views (including `QuantumPortfolioDashboard.tsx` and the redundant `strategy`/`portfolio` tabs) have been consolidated into **4 high-signal routed sections** (`NavSection = "harness" | "missions" | "knowledge" | "system"` in `frontend/src/lib/routes.ts` and `frontend/src/types/index.ts`), with legacy routes redirected transparently:

1. **Workbench & Co-Pilot (`/harness` ← `/harness/runs`, `frontend/src/pages/WorkbenchPage.tsx`)**:
   - Headless 5-card `TelemetryGrid` (Worker Loops from `/api/healthz`, BitPro MCP live probe & tools, Missions/Runs, Unified Memory `active + cognitive`, Evals/Tokens).
   - Multi-turn canonical Thread/Turn Co-Pilot (`HarnessPage`, `RunControls`, `AgentProgress`, `ThreadDetails`, `ReportReader`, backed by `frontend/src/hooks/useAgentWorkbench.ts` and `frontend/src/agentThread.ts`): starts with an empty prompt (`""`, no OKX SWAP default framing), offers 4 clickable diagnostic quick-command chips (3-slot evolution status, BitPro Paper snapshot, `#strategy_id` diagnosis, cognitive rules recall), supports `Cmd/Ctrl+Enter` submit (clearing the prompt on turn start), non-destructive multi-thread switching (`listAgentThreads` via `GET /api/agent/v1/threads` fetched only when opened), active turn interruption (`interruptAgentTurn` via `POST /api/agent/v1/threads/{id}/turns/{turn_id}/interrupt`), deduplicated latest reply rendering between `ThreadDetails` and `ReportReader`, and inline HITL (`waiting_input` / `waiting_approval`) status display.
   - `RuntimeMonitor` (with `BitProCard` displaying `bitpro.live_probe` online/auth/latency and diagnostic hints) and clickable recent runs/missions that load `AgentFlightRecorder` (`GET /api/agent/runs/{run_id}/observability`, projecting both legacy `AgentRun` and canonical `mis_*` `AgentMission` timelines into `agent-observability-v1`). `AgentFlightRecorder` is also automatically loaded when a canonical turn completes with a `mission_id`.
2. **Missions & Evolution (`/harness/missions` ← `/harness/portfolio`, lazy-loaded `frontend/src/pages/MissionsEvolutionPage.tsx`)**:
   - ARC 3-Slot Autonomous Evolution control strip (`GET /api/v1/arc/evolution?compact=true`, one-click `POST /api/v1/arc/evolution/preset` `{"preset":"production_3slot"}`, `POST /api/v1/arc/evolution/scan`, `budget.sources` 3-slot occupancy & cooldown cards, `GET/POST /api/portfolio/race-judge/{status,run-now}`, and direct deep links to BitPro `/ai-lab` and `/evolution`).
   - Durable `MissionRuntime` workspace (`GET/POST /api/agent/missions*` for creating, running, pausing, resuming, canceling, steering missions, and inspecting plan/step/event/unknowns).
3. **Knowledge, Memory & Governance (`/harness/knowledge` ← `/harness/{memory,rag,strategy}`, lazy-loaded `frontend/src/pages/KnowledgeMemoryPage.tsx`)**:
   - Three-tier memory observability (`MemoryObservatory` + `GET /api/memory`): displays active Operational `MemoryItem` inventory (with `kind`/`tag` filters and `last_used_at`), Semantic causal rules (`ArcSemanticAssertion`), Episodic race outcomes (`ArcEpisodicMemory`), and `hypothesis_count` from `memory.cognitive` and `cognitive_items`.
   - Auto-executed RAG knowledge search (`GET /api/rag/search?query=risk` on tab mount), Strategy Library drilldown (`GET /api/strategy/library`), and `GovernanceReview` (`MemoryAssertion`, `SkillProposal`, `SkillRelease` review with mandatory operator reason).
4. **System, Alerts & Diagnostics (`/harness/system` ← `/harness/{alerts,quality}`, lazy-loaded `frontend/src/pages/SystemDiagnosticsPage.tsx`)**:
   - Worker loop heartbeat & stall forensics (`GET /api/healthz` `workers.instances[]`, loop `components`, `last_stall` cause/frames, DB & BitPro/QuantLab adapter status).
   - Unified alerts inbox (`GET /api/alerts` + `GET /api/v1/arc/evolution/alerts` with `POST .../ack`), deduplicated runtime exception journal (`GET /api/v1/arc/runtime-errors`), and ResearchOS deterministic eval summary.

### Strict On-Demand Fetching & Unified API Client

- **Initial `/harness` mount** executes ONLY `GET /api/harness/overview` and `GET /api/healthz` (plus optional active thread restoration when `localStorage` already stores `hypertrade.agent.thread.v1`). Hidden tabs (`missions`, `knowledge`, `system`) are code-split via `React.lazy` + `<Suspense>` (with `vite.config.ts` `manualChunks` for `react-vendor` and `icons`) and never fetched until navigated to.
- **Unified HTTP layer (`frontend/src/api/client.ts`)**: All console requests use `apiGet`, `apiPost`, `apiPut`, and `apiDelete` (`credentials: "include"`, mapping non-2xx responses to `ApiError` and 401/403 via `isAuthError` -> `readonly` mode).
- **Honest unknowns & passive auth**: Before `/api/harness/overview` arrives, overview is `null` (`EMPTY_OVERVIEW` is all zeros). The console never probes `/api/auth/me` and renders no login form; only when a privileged call returns 401/403 does it enter `readonly` mode (`ht /login` hint and disabled mutations). When `headless_mode=true`, `/api/harness/overview` omits dormant market/paper/strategy_lab/live_orders DB scans and renders `headlessNotice` links to BitPro `/ai-lab` and `/evolution`.

### HyperMonitor Design Direction (`ConsoleShell.tsx`, `HyperBrandMark.tsx`, `styles.css`, `tailwind.config.ts`)

- **3-tier control-plane shell**: `.hm-topbar` (68px with `<HyperBrandMark />`, BitPro quick links, theme toggle, ZH/EN toggle, alert bell, live clock, `AccessBadge`), `.hm-sub-topbar` (42px with sidebar collapse toggle, breadcrumb, `.hm-headless-strip`, pinned tab pill), and `.hm-layout` (collapsible sticky left `<aside className="hm-sidebar ...">`, fluid `.hm-workspace`, and right 280px `.hm-signals-rail` `<div>`).
- **Dual-theme tokens**: Obsidian Dark (`:root`: `--bg: #070708`, `--panel: #141416`, `--panel2: #1c1c20`, `--line: #2a2a30`, `--accent: #c026d3`, `--accent-gradient: linear-gradient(90deg, #7c3aed, #db2777)`, `--up: #10b981`, `--warn: #f59e0b`, `--down: #ef4444`, `--info: #06b6d4`, `--radius-card: 22px`, `--radius-inset: 16px`) and Light Surface (`[data-theme="light"]`: `--bg: #f3f1f8`, `--panel: #ffffff`, `--card-inset-bg: #f6f4fb`, `--line: #e8e3f2`), toggled via `hypertrade.theme.v1` and mapped to Tailwind `--rgb-*` utilities.
- Chinese UI by default, English toggle available; `lucide-react` icons throughout.

---

## 中文

HyperTrade 前端是一个面向受治理 Agent Runtime 与无头研究/进化引擎的 **HyperMonitor 控制平面工作台**，不是营销页，也不是交易下单终端。重构后，原有 9 个分散视图（含已删除的 `QuantumPortfolioDashboard.tsx` 与内联 `PortfolioLifecyclePanel`、以及冗余的 `strategy`/`portfolio` 页签）已按第一性原理收敛为 **4 个高信噪比核心路由**（`NavSection = "harness" | "missions" | "knowledge" | "system"`，定义于 `frontend/src/lib/routes.ts` 与 `frontend/src/types/index.ts`），并保留旧路径透明重定向：

1. **控制台与对话 (`/harness` ← `/harness/runs`，`frontend/src/pages/WorkbenchPage.tsx`)**：
   - 顶部 5 卡无头遥测条 `TelemetryGrid`（`/api/healthz` Worker 循环存活与 Stall、BitPro MCP 实时探活与工具数、Missions/Runs 计数、统一记忆 `active + cognitive`、评测/Token 用量）。
   - 多轮规范 Thread/Turn Co-Pilot（由 `HarnessPage`、`RunControls`、`AgentProgress`、`ThreadDetails`、`ReportReader` 组成，状态收敛于 `frontend/src/hooks/useAgentWorkbench.ts` 与 `frontend/src/agentThread.ts`）：清空历史 OKX SWAP 默认提示词，内置 4 个可点击诊断快捷芯片（`3-Slot 进化状态`、`BitPro Paper 快照`、`#strategy_id 诊断`、`认知规则召回`）；支持 `Cmd/Ctrl+Enter` 发送并在开轮后清空输入框；按需拉取历史会话切换器（`listAgentThreads` 调用 `GET /api/agent/v1/threads`）且新建会话不再强行归档旧会话；支持运行中回合中断（`interruptAgentTurn` 调用 `POST /api/agent/v1/threads/{id}/turns/{turn_id}/interrupt`）、去重 `ThreadDetails` 与 `ReportReader` 的最新回复，以及行内 HITL 等待审批/输入状态展示。
   - 右栏 `RuntimeMonitor`（含展示 `bitpro.live_probe` 实时连通/延迟/诊断提示的 `BitProCard`）与可点击的最近运行/Mission 列表，点击或 Turn 完成带 `mission_id` 时自动加载 `AgentFlightRecorder`（`GET /api/agent/runs/{run_id}/observability`，兼容投影 `AgentRun` 与 `mis_*` `AgentMission` 的 `agent-observability-v1` 时间线）。
2. **任务与进化 (`/harness/missions` ← `/harness/portfolio`，懒加载 `frontend/src/pages/MissionsEvolutionPage.tsx`)**：
   - ARC 3-Slot 自主进化控制条（`GET /api/v1/arc/evolution?compact=true`、一键应用 `POST /api/v1/arc/evolution/preset` `{"preset":"production_3slot"}`、触发扫描 `POST /api/v1/arc/evolution/scan`、`budget.sources` 3 槽位占用与冷却卡片、`GET/POST /api/portfolio/race-judge/{status,run-now}` 以及跳转 BitPro `/ai-lab` 与 `/evolution` 链接）。
   - 持久化 `MissionRuntime` 工作区（`/api/agent/missions*`，支持创建、运行、暂停、恢复、取消、Steer 与计划/步骤/事件/未知项检视）。
3. **记忆与治理 (`/harness/knowledge` ← `/harness/{memory,rag,strategy}`，懒加载 `frontend/src/pages/KnowledgeMemoryPage.tsx`)**：
   - 三层记忆可观测台（`MemoryObservatory` + `GET /api/memory`）：同时展示操作型 `MemoryItem`（支持 `kind`/`tag` 过滤与 `last_used_at`）、语义因果规则（`ArcSemanticAssertion`）、情景赛马经验（`ArcEpisodicMemory`）及 `memory.cognitive` / `cognitive_items` 统计与条目。
   - 进页自动触发默认 RAG 检索（`GET /api/rag/search?query=risk`）、策略知识库下钻（`GET /api/strategy/library`）及 `GovernanceReview`（`MemoryAssertion` / `SkillProposal` / `SkillRelease` 人工复核）。
4. **告警与诊断 (`/harness/system` ← `/harness/{alerts,quality}`，懒加载 `frontend/src/pages/SystemDiagnosticsPage.tsx`)**：
   - Worker 循环心跳与 Stall 取证矩阵（`GET /api/healthz` 的 `workers.instances[]`、循环 `components`、`last_stall` 归因与调用帧、DB 及适配器健康）。
   - 统一告警收件箱（`GET /api/alerts` + `GET /api/v1/arc/evolution/alerts` 含一键 Ack）、去重运行时错误台账（`GET /api/v1/arc/runtime-errors`）及 ResearchOS 确定性评测状态。

### 严格按需取数与统一 API 客户端

- **首屏严格按需取数**：`/harness` 挂载时只请求 `GET /api/harness/overview` 与 `GET /api/healthz`（若 `localStorage` 已存 `hypertrade.agent.thread.v1` 则按需恢复当前会话）。非首屏页面通过 `React.lazy` + `<Suspense>` 与 `vite.config.ts` `manualChunks`（`react-vendor`、`icons`）按需分包加载，切换进入前零请求。
- **统一请求层（`frontend/src/api/client.ts`）**：全站收敛至 `apiGet`、`apiPost`、`apiPut`、`apiDelete`（统一携带 `credentials: "include"`，将非 2xx 映射为 `ApiError`，经 `isAuthError` 被动识别 401/403 切换至只读态）。
- **诚实未知与被动鉴权**：不主动探测 `/api/auth/me`、不渲染登录表单，仅在特权写/读被 401/403 拒绝时显示 `Read-only` 徽标与 `ht /login` 提示；`headless_mode=true` 时后端跳过休眠本地行情/模拟盘/策略研究/实盘订单查库并保持 `EMPTY_OVERVIEW` 零值基线。

### HyperMonitor 视觉体系（`ConsoleShell.tsx`、`HyperBrandMark.tsx`、`styles.css`、`tailwind.config.ts`）

- **三层控制面外壳**：`.hm-topbar`（68px，`<HyperBrandMark />` 脉搏心电徽标、`HYPERTRADE` 渐变品牌字标、BitPro 快捷入口、深浅主题切换、中英切换、告警铃铛、实时时钟与 `AccessBadge`）、`.hm-sub-topbar`（42px，侧栏折叠、面包屑、`.hm-headless-strip` 无头引导条与固定页签胶囊）、`.hm-layout`（可折叠 sticky 左侧 `<aside className="hm-sidebar ...">`、流式 `.hm-workspace` 主区与右侧 280px `.hm-signals-rail` 实时信号轨）。
- **暗黑曜石 + 浅紫白卡双主题**：暗色默认 `:root`（`--bg: #070708`、`--panel: #141416`、`--panel2: #1c1c20`、`--line: #2a2a30`、`--accent: #c026d3`、紫粉渐变 `--accent-gradient: linear-gradient(90deg, #7c3aed, #db2777)`、`--radius-card: 22px`、`--radius-inset: 16px`）与浅色 `[data-theme="light"]`（`--bg: #f3f1f8`、`--panel: #ffffff`、`--card-inset-bg: #f6f4fb`、`--line: #e8e3f2`），由 `hypertrade.theme.v1` 持久化并通过 `--rgb-*` 变量映射至 Tailwind 语义色板。默认中文界面，支持英文一键切换。
