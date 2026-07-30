# 37 ARC (Autonomous Research Core) 自主进化控制内核架构设计

> 文档性质：核心架构规范、技术设计与组件接口指南。
> 状态：Approved & Active — 2026-07-30。

## 1. 概述与设计愿景

**ARC (Autonomous Research Core)** 是 HyperTrade 项目中的通用自主进化 Agent 控制内核。

与传统基于单次问答 (Chat/Ask) 或固定节点图 (Static DAG / LangGraph) 的 Agent 不同，ARC 被设计为一个**独立于具体交易标的与领域逻辑的通用闭环内核 (Domain-Agnostic Core Kernel)**。它实现了真实的“自主搜索、自我代码演变、因果反思归因、红蓝对抗与自动化孵化上线”能力。

### 1.1 六边形架构 (Hexagonal Architecture)

ARC 遵循端口与适配器模式 (Ports and Adapters)：

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                 ARC (Autonomous Research Core) 控制内核                     │
│                                                                             │
│   ┌────────────────────┐   ┌────────────────────┐   ┌───────────────────┐   │
│   │ 1. 目标与章程编译器 │──►│ 2. 策略突变与基因库 │──►│ 3. 闭环状态控制器 │   │
│   │ (ARCGoalCompiler)  │   │(ARCGeneticMutator) │   │  (ARCController)  │   │
│   └────────────────────┘   └────────────────────┘   └─────────┬─────────┘   │
│             ▲                                                 │             │
│             │                                                 ▼             │
│   ┌─────────┴──────────┐                            ┌───────────────────┐   │
│   │ 5. 因果反思归因账本 │◄───────────────────────────│ 4. 红蓝对抗与验证器│   │
│   │(ARCReflexionLedger)│                            │(ARCAdversarial)   │   │
│   └────────────────────┘                            └───────────────────┘   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (通过标准 ARCPlatformAdapter 端口)
═══════════════════════════════════════╧═══════════════════════════════════════
                             外层插拔式领域适配器 (Domain Adapters)
  ┌──────────────────────┬──────────────────────┬───────────────────────────┐
  │  加密货币 Adapter    │  A股/美股/港股 Adapter│   其他未知探索领域 Adapter│
  │ (OKX / BitPro 永续)  │  (StockPro / 股票日历)│ (如: AI代码重构/生物分子) │
  └──────────────────────┴──────────────────────┴───────────────────────────┘
```

---

## 2. ARC 核心组件层 (Core Kernel Components)

### 2.1 `ARCController` (闭环状态控制器)
* **职责**：整个自主研究循环的调度与状态机控制。它管理资源预算 (`ARCBudgetV1`)、分布式 Worker 行锁、事件追加与重放。
* **边界**：不包含任何具体交易所或股票的硬编码逻辑，纯依靠确定性事件驱动。

### 2.2 `ARCGeneticMutator` (代码基因突变与搜寻引擎)
* **职责**：基于品质-多样性 (Quality-Diversity / MAP-Elites) 搜寻算法与大模型 AST 变异算子。
* **功能**：将策略代码拆解为因子模块、触发规则、风控模块。LLM 作为基因突变算子，在过去成功/失败经验指导下进行交叉重组与代码变异。

### 2.3 `ARCAdversarialEngine` (红蓝对抗引擎)
* **蓝队 (BlueTeamQuant / Inventor)**：提出新假设、生成并改进策略代码。
* **红队 (RedTeamQuant / Falsifier)**：寻找蓝队策略逻辑中的缺陷，施加黑天鹅高波动测试、流动性冲击测试、参数敏感性扰动测试。
* **死刑法官 (Deterministic Verifier)**：执行真实的沙箱隔离回测与样本外 (OOS) 交叉验证。

### 2.4 `ARCReflexionLedger` (因果归因与反思账本)
* **职责**：当回测或红队测试失败时，提取定量失败原因（如：“在极端剧烈波动 Regime 下由过于狭窄的 ATR 导致频繁砍仓”），生成结构化的**负向约束条件 (Negative Constraints)**。
* **持久化**：以不可变日志写入 `arc_reflexion_events`，作为下一轮突变循环上下文的强制约束。

### 2.5 `ARCPaperIncubationResolver` (模拟盘自动孵化器)
* **职责**：当候选策略击败红队攻击并通过确定性验证后，根据任务开始时由用户授予的 `PaperPreauthorizationV1` 预授权，自动派生 Candidate-bound 窄授权，并自动配置上线运行模拟盘。

---

## 3. 分阶段 Sprint 研发路线图 (Sprint Breakdown)

整个 ARC 系统的研发与落地划分为 4 个有序的 Sprint 推进：

### 📌 Sprint 132 — ARC 通用内核、领域合同与黄金测试 (Core Kernel & Domain Contracts)
* **目标**：建立 ARC 内核基础、事件溯源 Reducer、状态机以及核心数据合同。
* **产出**：
  * `ARCGoalV1`, `ARCBudgetV1`, `ARCCandidateAttemptV1` 数据模型。
  * `ARCController` 状态机与底层存储。
  * 黄金测试 `tests/test_arc_kernel.py`（使用 Fake Adapter 跑通全状态迁移）。

### 📌 Sprint 133 — ARC 策略基因突变与红蓝对抗引擎 (Mutation & Red-Blue Adversarial Engine)
* **目标**：实现 `ARCGeneticMutator` 策略代码 AST 级变异与红蓝对抗博弈机制。
* **产出**：
  * `BlueTeamQuant` 与 `RedTeamQuant` 对抗交互与测试算子。
  * AST 规则拆解与基因代码变异器。
  * 单元与集成测试 `tests/test_arc_adversarial.py`。

### 📌 Sprint 134 — ARC 因果归因反思账本与经验继承 (Reflexion Ledger & Negative Constraints)
* **目标**：实现定量失败归因与 Reflexion 经验记忆闭环。
* **产出**：
  * `ARCReflexionLedger` 归因日志库与 `FailureDiagnosisV1`。
  * 负向约束算子：自动将历史失败注入下一轮候选生成 Prompt。
  * 集成测试 `tests/test_arc_reflexion.py`。

### 📌 Sprint 135 — ARC 自动模拟盘孵化与端到端自主探索闭环 (Auto-Incubation & Acceptance)
* **目标**：连接自动模拟盘上线机制，提供统一 API/CLI 入口并完成 Canary 验收。
* **产出**：
  * 自动模拟盘派生授权与上线运行 (`paper_observing`)。
  * 统一入口 API `/api/v1/arc/missions` 及 CLI `/arc`。
  * 全量端到端自主探索与进化测试 `tests/test_arc_acceptance.py`。
