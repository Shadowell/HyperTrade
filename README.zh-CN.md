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
  <a href="README.md">English README</a> ·
  <a href="docs/architecture/37-arc-autonomous-research-core-architecture.md">ARC 核心架构</a> ·
  <a href="docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md">MCTS与QD搜寻设计</a> ·
  <a href="docs/architecture/39-arc-adversarial-red-blue-engine-design.md">红蓝对抗博弈设计</a> ·
  <a href="docs/architecture/40-arc-reflexion-causal-attribution-design.md">归因反思账本设计</a> ·
  <a href="docs/architecture/41-arc-voyager-skill-distillation-design.md">Voyager技能蒸馏设计</a>
</p>

---

## 🌟 概要介绍

**HyperTrade** 是一个自托管、受治理的量化研究与交易执行 Agent Runtime。在通用**ARC (Autonomous Research Core) 控制内核**的驱动下，HyperTrade 将自然语言量化目标转化为连续、自主演进的策略研发流程。

与普通的静态 Agent 框架（如 LangChain、AutoGen、CrewAI）不同，**ARC** 作为一个**循环工程化 Agent 内核 (Loop-Engineered Agent Kernel)**，使用蒙特卡洛树搜索 (MCTS) 动态探索策略解空间，通过红蓝对抗引擎（蓝队发明 vs. 红队找茬攻击）审查漏洞，提取多 Regime 因果归因反思，自动蒸馏 Voyager 式可复用 Python 技能组件，并在策略过检后自动上线模拟盘运行。

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
