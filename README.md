# HyperTrade & ARC (Autonomous Research Core)

<p align="center">
  <strong>生产级受治理 Agent Runtime 与通用自主进化控制内核 (ARC)</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/FastAPI-0.104+-009688.svg" alt="FastAPI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/React-18+-61DAFB.svg" alt="React" /></a>
  <a href="#"><img src="https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg" alt="TypeScript" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PostgreSQL-14+-4169E1.svg" alt="PostgreSQL" /></a>
  <a href="docs/architecture/37-arc-autonomous-research-core-architecture.md"><img src="https://img.shields.io/badge/status-ARC_SOTA_Production-brightgreen.svg" alt="ARC Status" /></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-11%20passed-success.svg" alt="Tests" /></a>
</p>

<p align="center">
  🌐 <strong>中文主文档</strong> ·
  <a href="README.en.md">🇬🇧 English Documentation</a> ·
  <a href="docs/architecture/37-arc-autonomous-research-core-architecture.md">ARC 核心架构</a> ·
  <a href="docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md">MCTS与QD搜寻设计</a> ·
  <a href="docs/architecture/39-arc-adversarial-red-blue-engine-design.md">红蓝对抗博弈设计</a> ·
  <a href="docs/architecture/40-arc-reflexion-causal-attribution-design.md">归因反思账本设计</a> ·
  <a href="docs/architecture/41-arc-voyager-skill-distillation-design.md">Voyager技能蒸馏设计</a>
</p>

---

## 🌟 概要介绍

**HyperTrade** 是一个自托管、受治理的量化研究与交易执行 Agent Runtime。在通用 **ARC (Autonomous Research Core) 控制内核** 的驱动下，HyperTrade 将自然语言量化目标转化为连续、自主演进的策略研发与模拟孵化全流程。

与传统的静态 Agent 框架（如 LangChain、AutoGen、CrewAI）不同，**ARC** 作为一个**循环工程化 Agent 内核 (Loop-Engineered Agent Kernel)**，使用蒙特卡洛树搜索 (MCTS) 动态探索策略解空间，通过红蓝对抗引擎（蓝队发明 vs. 红队找茬攻击）审查漏洞，提取多 Regime 因果归因反思，自动蒸馏 Voyager 式可复用 Python 技能组件，并在策略过检后自动上线模拟盘运行。

---

## 🚀 核心 SOTA 架构创新

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                 ARC (Autonomous Research Core) 通用控制内核                 │
│                                                                             │
│   ┌────────────────────┐   ┌────────────────────┐   ┌───────────────────┐   │
│   │ 1. 目标编译器      │──►│ 2. MCTS & MAP-Elites│──►│ 3. 状态控制器     │   │
│   │ (ARCGoalCompiler)  │   │ (策略树搜寻引擎)   │   │  (ARCController)  │   │
│   └────────────────────┘   └────────────────────┘   └─────────┬─────────┘   │
│             ▲                                                 │             │
│             │                                                 ▼             │
│   ┌─────────┴──────────┐                            ┌───────────────────┐   │
│   │ 5. 归因反思账本    │◄───────────────────────────│ 4. 红蓝对抗引擎   │   │
│   │(ARCReflexionLedger)│                            │(ARCAdversarialEngine) │
│   └────────────────────┘                            └───────────────────┘   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (标准协议接口)
═══════════════════════════════════════╧═══════════════════════════════════════
                             外层插拔式领域适配器 (Domain Adapters)
  ┌──────────────────────┬──────────────────────┬───────────────────────────┐
  │  加密货币 SWAP 适配器│  股票市场适配器     │   其他未知领域适配器      │
  │ (OKX / BitPro MCP)   │  (StockPro / A股)   │ (AI代码重构/生物AI)       │
  └──────────────────────┴──────────────────────┴───────────────────────────┘
```

### 1. MCTS 与 MAP-Elites 质量-多样性搜寻引擎
* **蒙特卡洛树搜索 (MCTS)**：管理策略代码 AST 节点树 (`MCTSNode`)，采用上限置信区间公式 ($UCB1 = \bar{V}_i + c \sqrt{\frac{\ln N_{parent}}{N_i}}$) 进行节点展开选择。
* **MAP-Elites 网格归档**：在多维特征空间（持仓周期 x 市场 Regime 适应度）中保留各单元格的精英策略，防止策略演化早熟收敛到单一拥挤因子。
* **设计文档**：[docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md](docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md)

### 2. 红蓝对抗博弈引擎 (Adversarial Red-Teaming)
* **蓝队 (Blue Team Quant / Inventor)**：提出 Alpha 假设、策略代码 AST 突变与参数边界。
* **红队 (Red Team Quant / Falsifier)**：专职“找茬”，施加黑天鹅高波震荡、流动性踩踏与宽止损陷阱攻防测试。
* **确定性沙箱裁判**：做无偏样本外 (OOS) 验证；只有击败红队攻防的候选策略才能通过。
* **设计文档**：[docs/architecture/39-arc-adversarial-red-blue-engine-design.md](docs/architecture/39-arc-adversarial-red-blue-engine-design.md)

### 3. 多 Regime 定量因果归因与 Reflexion 记忆账本
* **定量因果归因**：拆解策略在牛市趋势、熊市趋势、高波震荡、低波盘整 4 种 Regime 下的性能表现。
* **Reflexion 记忆账本**：生成结构化否定约束（例如：*"禁止在高波震荡 Regime 下使用宽止损 >10%"*），注入后续进化轮次的 Prompt 上下文。
* **设计文档**：[docs/architecture/40-arc-reflexion-causal-attribution-design.md](docs/architecture/40-arc-reflexion-causal-attribution-design.md)

### 4. Voyager 风格技能自动提取与基因库 (Skill Distillation)
* **AST 技能提取**：策略通过验证后，自动解析 AST 发现并提取优良子函数（如自适应通道计算、订单簿失衡退出算法）。
* **不可变技能库**：注册提取的技能 (`ARCSkillLibrary`)，生成文档与代码片段，供后续进化循环继承复用。
* **设计文档**：[docs/architecture/41-arc-voyager-skill-distillation-design.md](docs/architecture/41-arc-voyager-skill-distillation-design.md)

### 5. 模拟盘自动化上线孵化
* **预授权派生**：从用户 `PaperPreauthorizationV1` 预授权中自动派生 Candidate-bound 模拟盘授权。
* **零触碰上线**：通过验证的策略无需人工干预自动配置并上线 BitPro 模拟盘运行 (`paper_observing`)。

---

## ⚡ 工业级基础设施 (Harness 3.0, Context 2.0, Memory 3.0, Flight Recorder)

```text
┌─────────────────────────────────────────────────────────────────────────────────────────┐
|                            HyperTrade 工业级底层基础设施体系                             |
├────────────────────────────┬────────────────────────────┬───────────────────────────────┤
| 1. Industrial Harness 3.0  | 2. Advanced Context 2.0    | 3. Autonomous Memory 3.0      |
| - 工具结果感知 LRU 缓存    | - 4-3-2-1 动态 Token 护城河| - 三层金字塔记忆 (Working/    |
| - KV Prompt Cache 前缀对齐 | - Schema/AST 语义折叠剪裁  |   Episodic/Semantic Pyramid)  |
| - MCP 动态 Schema 展平翻译 | - 洞察感知摘要 2.0 (提取   | - 艾宾浩斯时间衰减重排序      |
| - MCP 链接三态熔断 (30s)   |   夏普率/回撤/错误Traceback| - 自动盘后反思刷盘 (Flusher)  |
| - L1/L2/L3 工具风险门禁    |   与原始观测掩码)          | - Regime 上下文感知与冲突裁决 |
├────────────────────────────┼────────────────────────────┴───────────────────────────────┤
| 4. DAG Pipeline Aggregator | 5. Observability & Flight Recorder                          |
| - DAG 2 阶段分发器         | - 黑盒全轨迹单步 Snapshots (Input/Output Token, Latency)     |
| - MCP 同源管道 JSON-RPC    | - Step Replay 单步回退与轨迹离线 JSON 导出                   |
└────────────────────────────┴────────────────────────────────────────────────────────────┘
```

### 🛠️ 1. Industrial Agent Harness 3.0 与 Prompt 缓存治理
* **`ToolResultLRUCache` (工具结果感知 LRU 缓存)**：对只读工具引入基于 `MD5(tool_name + canonical_args)` 的 TTL 缓存（默认 15 秒），遇到写工具操作自动清空失效，杜绝重复网络请求开销。
* **`PromptCachePrefixAligner` (KV Prompt Caching 前缀对齐器)**：将 System Prompt、System Rules 与 Tools 结构静态对齐置于 Message 数组 index 0，显著提升 DeepSeek V3 / Claude 3.5 / Gemini 的 API KV Cache 命中率（降低 50%~90% Token 费用与 TTFT 延迟）。
* **`MCPToolSchemaTranslator` (Schema 展平翻译)**：解耦并展平 MCP Server 复杂的 `$ref` 与 `allOf` 嵌套 Schema。
* **`MCPConnectionCircuitBreaker` (MCP 三态熔断器)**：连续 3 次失败自动触发 30s 熔断，引导优雅降级。
* **`ToolCallPermissionSandboxGuard` (L1/L2/L3 风险门禁)**：L1 自动放行、L2 沙箱校验、L3 实盘强校验 `approval_token`。
* **架构文档**：[docs/architecture/58-tool-result-cache-and-prompt-cache-prefix-aligner.md](docs/architecture/58-tool-result-cache-and-prompt-cache-prefix-aligner.md)

### 📼 2. 黑盒飞行记录仪与全轨迹单步重放 (`flight_recorder.py`)
* **`AgentFlightRecorder` (全轨迹快照记录仪)**：以 Session 为单位不可变记录每个 Step 的 Input/Output Token 消耗、Tool Call 详情、Tool Result、Model Output 与响应延迟。
* **`FlightRecorderReplayEngine` (单步重放引擎)**：支持指定 Session 与 Step 索引进行单步重放与全轨迹 JSON 导出会话审计。
* **架构文档**：[docs/architecture/59-agent-flight-recorder-and-replay-telemetry.md](docs/architecture/59-agent-flight-recorder-and-replay-telemetry.md)

### 🔀 3. DAG 依赖图分发与 MCP 批量管道 (`tool_pipeline.py`)
* **`ToolDependencyGraphDispatcher` (DAG 2 阶段分发)**：Stage 0 并发分发无依赖只读工具，完成倒换 Stage 1 串行执行写工具。
* **`MCPBatchPipelineAggregator` (MCP 管道聚合)**：打包同源 MCP 工具请求为单一 JSON-RPC Batch 消息，一趟 RTT 取回结果。
* **架构文档**：[docs/architecture/57-dag-tool-dispatcher-and-mcp-batch-pipeline.md](docs/architecture/57-dag-tool-dispatcher-and-mcp-batch-pipeline.md)

### 🧠 3. Advanced Context Management 2.0 深度上下文管理
* **`DynamicTokenBudgetManager` (动态 Token 护城河)**：识别 DeepSeek (128K)、Claude (200K)、Qwen (32K) 模型上限，划分 **20% System / 40% Tool History / 30% Memory / 10% Output Reserve** 物理隔离预算 Guard。
* **`SemanticContextPruner` (Schema 语义剪裁)**：保留 Dict 与 Key 结构，对 List 采用“前 2 项 + 后 3 项”语义折叠，绝不损坏 JSON 语法。
* **`TurnSlidingWindowSummarizer 2.0` (选择性洞察摘要)**：对话 Turn $>12$ 时，扫描历史提取夏普率/回撤指标、用户指令与报错 Traceback，掩码原始观测，生成 `[Selective Executive Insight Summary]` 节点，支持无限轮次长会话。
* **架构文档**：[docs/architecture/54-advanced-context-and-memory-management-v2-architecture.md](docs/architecture/54-advanced-context-and-memory-management-v2-architecture.md)

### 💾 4. Autonomous Memory Subsystem 3.0 自主进化记忆体系
* **`HierarchicalMemoryPyramid` (三层记忆金字塔)**：划分 Working Memory (短暂变量)、Episodic Memory (7日任务与回测实验)、Semantic Memory (长期 Regime 规则与避坑账本)。
* **`EbbinghausDecayScorer` (艾宾浩斯时间衰减)**：结合向量相似度、时间衰减 $e^{-0.05 \Delta t}$ 与重要性权重计算综合得分：$\text{Score} = 0.5 \text{Sim} + 0.3 \text{Decay} + 0.2 \text{Imp}$。
* **`MemoryConsolidator` (记忆聚类去重)**：相似度 $>0.85$ 时自动合并增量 Observation 进既有 Memory 节点，防止数据库污染。
* **`AutoReflexionMemoryFlusher` (自动反思刷盘)**：任务结束自动挂载反思，成功任务提炼策略规律入 Semantic，失败提炼教训入 Episodic。
* **`MarketRegimeMemoryFilter` (Regime 感知隔离)**：为记忆打上 `bull_trend`, `bear_crash`, `sideways_range`, `high_volatility` 标签，同 Regime 优先召回，跨 Regime 0.5x 惩罚。
* **`MemoryContradictionResolver` (记忆冲突裁决)**：自动检测新旧记忆的语义矛盾，标记旧假设为 `deprecated: true`，确保送入 Context 的知识库无冲突。
* **架构文档**：[docs/architecture/55-autonomous-memory-v3-regime-filter-and-reflexion-flusher.md](docs/architecture/55-autonomous-memory-v3-regime-filter-and-reflexion-flusher.md)

---

## 🛠️ 技术栈

| 图层 | 技术选择 |
|-------|-------------|
| **控制内核** | ARC (Autonomous Research Core) Python 3.12+ 通用事件驱动 Agent 运行库 |
| **后端与 Web API** | FastAPI, Uvicorn, 可续传游标 SSE (Server-Sent Events) |
| **ORM 与数据库** | SQLAlchemy 2.0 (Async), Alembic, PostgreSQL 14+ 带 `pgvector` 扩展 |
| **LLM Provider 抽象** | ProviderRuntime (OpenAI, DeepSeek, Claude / Vide Coding, Codex, OpenRouter, Qwen) |
| **量化与回测** | BitPro 平台 (经由 Model Context Protocol - MCP) + Backtrader 回测引擎 |
| **安全沙箱** | Linux 进程/容器隔离 (只读根目录, 无网络, tmpfs 限制) |
| **前端与 UI** | React 18, TypeScript 5, Vite, TanStack Query, Recharts, Tauri 2 (macOS 悬浮侧边助手), Textual (终端 TUI) |

---

## 🧪 自动化测试套件与验证

ARC 引擎包含 11 项全自动化测试套件，全面验证内核状态机、UCB1 节点选择、AST 突变、红蓝对抗、Reflexion 归因记忆、技能提取及端到端模拟盘上线：

```bash
python3 -m pytest tests/test_arc_kernel.py tests/test_arc_adversarial.py tests/test_arc_reflexion.py tests/test_arc_mcts.py tests/test_arc_skills.py tests/test_arc_acceptance.py -v
```

### 测试验证输出：

```text
============================= test session starts ==============================
collected 11 items

tests/test_arc_kernel.py::test_arc_goal_and_budget_contracts PASSED      [  9%]
tests/test_arc_kernel.py::test_arc_controller_state_machine_and_event_reduction PASSED [ 18%]
tests/test_arc_kernel.py::test_arc_controller_reflexion_and_budget_exhaustion PASSED [ 27%]
tests/test_arc_adversarial.py::test_blue_team_strategy_generation PASSED [ 36%]
tests/test_arc_adversarial.py::test_red_team_adversarial_attack PASSED   [ 45%]
tests/test_arc_adversarial.py::test_ast_mutation_and_red_team_survival PASSED [ 54%]
tests/test_arc_reflexion.py::test_reflexion_ledger_failure_diagnosis PASSED [ 63%]
tests/test_arc_mcts.py::test_mcts_tree_construction_and_ucb1_selection PASSED [ 72%]
tests/test_arc_mcts.py::test_map_elites_quality_diversity_grid PASSED    [ 81%]
tests/test_arc_skills.py::test_arc_skill_distillation_and_registration PASSED [ 90%]
tests/test_arc_acceptance.py::test_arc_end_to_end_autonomous_loop_acceptance PASSED [100%]

======================== 11 passed, 42 warnings in 0.11s ========================
```

---

## 💻 快速开始与 API

### 1. 启动 API 服务

```bash
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

### 2. 触发 ARC 自主探索与进化循环

```bash
curl -X POST http://localhost:3334/api/v1/arc/missions \
  -H "Content-Type: application/json" \
  -d '{
    "objective": "研究一个适应BTC高波动的趋势打破策略，过检后自动上线模拟盘",
    "symbol": "BTC-USDT-SWAP",
    "max_candidates": 5,
    "paper_preauth_approved": true
  }'
```

### 3. 查询 Mission 状态与事件重放

```bash
curl http://localhost:3334/api/v1/arc/missions/{mission_id}
```

---

## 📚 详细技术架构设计文档

| 模块 | 架构设计文档 |
|---------|-----------------------------|
| **通用控制内核** | [37 ARC 自主进化控制内核架构设计](docs/architecture/37-arc-autonomous-research-core-architecture.md) |
| **搜寻引擎** | [38 MCTS 与 MAP-Elites 质量-多样性搜寻引擎设计](docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md) |
| **红蓝对抗** | [39 ARC 红蓝对抗博弈引擎技术设计](docs/architecture/39-arc-adversarial-red-blue-engine-design.md) |
| **归因反思** | [40 多 Regime 定量因果归因与 Reflexion 记忆账本设计](docs/architecture/40-arc-reflexion-causal-attribution-design.md) |
| **技能提取** | [41 Voyager 风格技能自动提取与基因库设计](docs/architecture/41-arc-voyager-skill-distillation-design.md) |
| **活动合同** | [用户定向合同 — ARC](docs/contracts/arc-autonomous-research-core.md) |

---

## 📄 开源许可与免责声明

基于 MIT 许可证开源。详见 `LICENSE` 文件。

> **免责声明**：本仓库中包含的任何内容均不构成投资建议。主网实盘交易执行由风控硬性禁用 (`live_allowed=false`)。
