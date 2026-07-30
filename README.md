# HyperTrade & ARC (Autonomous Research Core)

<p align="center">
  <strong>Production-Grade Governed Agent Runtime & Universal Autonomous Research Kernel (ARC)</strong>
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
  <a href="README.zh-CN.md">中文文档</a> ·
  <a href="docs/architecture/37-arc-autonomous-research-core-architecture.md">ARC Core Architecture</a> ·
  <a href="docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md">MCTS & QD Search</a> ·
  <a href="docs/architecture/39-arc-adversarial-red-blue-engine-design.md">Red-Blue Adversarial</a> ·
  <a href="docs/architecture/40-arc-reflexion-causal-attribution-design.md">Reflexion Memory</a> ·
  <a href="docs/architecture/41-arc-voyager-skill-distillation-design.md">Voyager Skill Library</a>
</p>

---

## 🌟 Executive Overview

**HyperTrade** is a self-hosted, governed Agent runtime for quantitative research and trading execution. Powered by its domain-agnostic **ARC (Autonomous Research Core)** kernel, HyperTrade bridges open-ended natural language research objectives to continuous, self-evolving quantitative discovery.

Unlike standard static Agent frameworks (e.g. LangChain, AutoGen, CrewAI), **ARC** operates as a **Loop-Engineered Agent Kernel** that dynamically explores strategy search spaces using Monte Carlo Tree Search (MCTS), tests candidates against Adversarial Red-Team attacks, extracts multi-regime causal failure reflexions, distills reusable Voyager-style Python skills, and automatically provisions passing strategies into paper simulation trading.

---

## 🚀 Key SOTA Architectural Innovations

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                 ARC (Autonomous Research Core) Universal Kernel             │
│                                                                             │
│   ┌────────────────────┐   ┌────────────────────┐   ┌───────────────────┐   │
│   │ 1. Goal Compiler   │──►│ 2. MCTS & MAP-Elites│──►│ 3. State Controller │   │
│   │  (ARCGoalCompiler) │   │ (Search Tree Engine)│   │  (ARCController)  │   │
│   └────────────────────┘   └────────────────────┘   └─────────┬─────────┘   │
│             ▲                                                 │             │
│             │                                                 ▼             │
│   ┌─────────┴──────────┐                            ┌───────────────────┐   │
│   │ 5. Reflexion Memory│◄───────────────────────────│ 4. Red-Blue Engine│   │
│   │ (Causal Ledger)    │                            │ (Adversarial Team)│   │
│   └────────────────────┘                            └───────────────────┘   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (Pluggable Protocol Ports)
═══════════════════════════════════════╧═══════════════════════════════════════
                             Pluggable Domain Adapters
  ┌──────────────────────┬──────────────────────┬───────────────────────────┐
  │  Crypto SWAP Adapter │  Stock Market Adapter│   Other Domain Adapters   │
  │ (OKX / BitPro MCP)   │  (StockPro / A-Share)│ (AI Refactoring/Bio-AI)   │
  └──────────────────────┴──────────────────────┴───────────────────────────┘
```

### 1. MCTS & MAP-Elites Quality-Diversity Search Engine
* **Monte Carlo Tree Search (MCTS)**: Manages candidate strategy AST code trees (`MCTSNode`) with upper confidence bound ($UCB1 = \bar{V}_i + c \sqrt{\frac{\ln N_{parent}}{N_i}}$) node expansion.
* **MAP-Elites QD Archive**: Preserves elite strategies across multi-dimensional feature descriptors (Holding Horizon x Market Regime Fit), preventing premature convergence to single crowded factors.
* **Design Doc**: [docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md](docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md)

### 2. Red-Blue Adversarial Game Engine (Adversarial Red-Teaming)
* **Blue Team Quant (Inventor)**: Proposes strategy hypotheses, code AST mutations, and parameter bounds.
* **Red Team Quant (Falsifier)**: Attacks strategy code under black swan volatility shocks, liquidity cliffs, and whipsaw stop-loss traps.
* **Deterministic Sandbox Judge**: Enforces unbiased out-of-sample (OOS) validation; only candidates surviving Red-Team attacks pass.
* **Design Doc**: [docs/architecture/39-arc-adversarial-red-blue-engine-design.md](docs/architecture/39-arc-adversarial-red-blue-engine-design.md)

### 3. Multi-Regime Causal Attribution & Reflexion Memory Ledger
* **Quantitative Causal Attribution**: Decomposes performance across 4 market regimes (*Bull Trend*, *Bear Trend*, *High-Vol Ranging*, *Low-Vol Ranging*).
* **Reflexion Memory Ledger**: Logs structured `negative_constraints` (e.g., *"Prohibit wide stop loss >10% under high volatility ranging"*) and injects them into future LLM prompt contexts.
* **Design Doc**: [docs/architecture/40-arc-reflexion-causal-attribution-design.md](docs/architecture/40-arc-reflexion-causal-attribution-design.md)

### 4. Voyager-Style Automated Skill & Factor Distillation
* **AST Skill Distillation**: Automatically parses AST syntax trees of validated strategies to discover reusable sub-functions (e.g. adaptive volatility channels, micro imbalance exit rules).
* **Immutable Skill Library**: Registers extracted skills (`ARCSkillLibrary`), generating docstrings and code blocks for prompt injection in subsequent evolution cycles.
* **Design Doc**: [docs/architecture/41-arc-voyager-skill-distillation-design.md](docs/architecture/41-arc-voyager-skill-distillation-design.md)

### 5. Automated Paper Trading Incubation
* **Candidate-Bound Preauthorization**: Automatically derives candidate-bound paper mandates from user preauthorizations (`PaperPreauthorizationV1`).
* **Zero-Touch Provisioning**: Provisions passing strategies to simulated BitPro paper trading without manual intervention (`paper_observing`).

---

## 🛠️ Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Core Kernel** | ARC (Autonomous Research Core) Python 3.12+ Universal Event-Driven Runtime |
| **Backend & Web API** | FastAPI, Uvicorn, Resumable Cursor SSE (Server-Sent Events) |
| **ORM & Database** | SQLAlchemy 2.0 (Async), Alembic, PostgreSQL 14+ with `pgvector` extension |
| **LLM Provider Layer** | ProviderRuntime (OpenAI, DeepSeek, Claude / Vide Coding, Codex, OpenRouter, Qwen) |
| **Quant & Backtesting** | BitPro Platform (via Model Context Protocol - MCP) + Backtrader |
| **Security Sandbox** | Linux Process/Container Isolation (read-only root, no network, tmpfs limits) |
| **Frontend & UI** | React 18, TypeScript 5, Vite, TanStack Query, Recharts, Tauri 2 (macOS Floating Companion), Textual (Terminal TUI) |

---

## 🧪 Comprehensive Test Suite & Verification

The ARC engine includes an exhaustive 11-case automated test suite verifying kernel state machine, UCB1 node selection, AST mutation, Red-Team attacks, Reflexion memory, Skill distillation, and end-to-end paper incubation:

```bash
python3 -m pytest tests/test_arc_kernel.py tests/test_arc_adversarial.py tests/test_arc_reflexion.py tests/test_arc_mcts.py tests/test_arc_skills.py tests/test_arc_acceptance.py -v
```

### Verification Output:

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

## 💻 Quick Start & API

### 1. Start API Server

```bash
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

### 2. Trigger Autonomous ARC Exploration Loop

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

### 3. Inspect Mission State & Replay Events

```bash
curl http://localhost:3334/api/v1/arc/missions/{mission_id}
```

---

## 📚 Technical Architecture Documentation

| Section | Architecture Design Document |
|---------|-----------------------------|
| **Core Kernel** | [37 ARC Autonomous Research Core Architecture](docs/architecture/37-arc-autonomous-research-core-architecture.md) |
| **Search Engine** | [38 MCTS & MAP-Elites Quality Diversity Search Design](docs/architecture/38-arc-mcts-and-quality-diversity-search-design.md) |
| **Adversarial Engine** | [39 Red-Blue Adversarial Game Engine Design](docs/architecture/39-arc-adversarial-red-blue-engine-design.md) |
| **Reflexion Memory** | [40 Multi-Regime Causal Attribution & Reflexion Design](docs/architecture/40-arc-reflexion-causal-attribution-design.md) |
| **Skill Distillation** | [41 Voyager-Style Skill Distillation & Library Design](docs/architecture/41-arc-voyager-skill-distillation-design.md) |
| **Active Contract** | [User-Directed Contract — ARC](docs/contracts/arc-autonomous-research-core.md) |

---

## 📄 License & Disclaimer

Distributed under the MIT License. See `LICENSE` for details.

> **Disclaimer**: Nothing in this repository constitutes investment advice or financial guidance. Mainnet live trading execution remains strictly blocked by governance (`live_allowed=false`).
