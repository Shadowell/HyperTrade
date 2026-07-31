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
  <a href="README.md">🇨🇳 中文主文档 (Main README)</a> ·
  🌐 <strong>English Documentation</strong> ·
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

### 5. Automated Paper Trading Sandbox Provisioning
* **Pre-authorization Derivation**: Automatically derives candidate-bound paper trading sub-authorizations from `PaperPreauthorizationV1`.
* **Zero-Touch Provisioning**: Verified strategies deploy to BitPro paper trading (`paper_observing`) without human intervention.

---

## ⚡ Industrial Infrastructure (Harness 2.5, Context 2.0, Memory 3.0, DAG Pipeline)

```text
┌─────────────────────────────────────────────────────────────────────────────────────────┐
|                          HyperTrade Industrial Infrastructure System                     |
├────────────────────────────┬────────────────────────────┬───────────────────────────────┤
| 1. Industrial Harness 2.5  | 2. Advanced Context 2.0    | 3. Autonomous Memory 3.0      |
| - Exponential Backoff      | - 4-3-2-1 Dynamic Token    | - 3-Tier Memory Pyramid       |
|   Retry (502/429 Jitter)   |   Budget Guard             |   (Working/Episodic/Semantic) |
| - MCP Flat Schema Translator| - Schema/AST Pruning       | - Ebbinghaus Time Decay       |
| - MCP Circuit Breaker (30s)| - Selective Insight 2.0     | - Auto Reflexion Flusher      |
| - L1/L2/L3 Risk Permission |   (Sharpe/Drawdown/Errors) | - Regime Filtering & Resolver |
├────────────────────────────┴────────────────────────────┴───────────────────────────────┤
| 4. DAG Pipeline & MCP Batch Aggregator                                                  |
| - DAG 2-Stage Dispatcher (Stage 0 Parallel Read -> Stage 1 Sequential Write)             |
| - MCP Batch JSON-RPC Aggregator (Single RTT Payload Dispatch)                           |
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 🛠️ 1. Industrial Agent Harness 2.5 & MCP Governance
* **`MCPToolSchemaTranslator`**: Dereferences and flattens complex MCP `$ref` and `allOf` JSON Schemas into flat parameter definitions optimized for LLM tool calling.
* **`MCPConnectionCircuitBreaker`**: 3-state circuit breaker tripping after 3 consecutive failures/timeouts for 30s. Returns `status: degraded` to guide graceful LLM tool degradation.
* **`ToolCallPermissionSandboxGuard`**: Enforces 3-tier risk permissions:
  * `L1_READ_ONLY`: Auto-approved for read queries;
  * `L2_SIMULATED_WRITE`: Validated within paper trading sandbox;
  * `L3_CRITICAL_LIVE_WRITE`: Requires valid `approval_token`.
* **`SmartToolExecutionHealer`**: Retries transient `502`/`429` errors with exponential backoff ($50\text{ms} \rightarrow 100\text{ms} \rightarrow 200\text{ms}$).
* **`ToolIdempotencyLockGuard`**: Thread-safe memory lock set preventing duplicate write tool submissions.
* **Architecture Spec**: [docs/architecture/56-mcp-circuit-breaker-and-tool-governance-v2.md](docs/architecture/56-mcp-circuit-breaker-and-tool-governance-v2.md)

### 🔀 2. DAG Tool Dispatcher & MCP Batch Pipeline (`tool_pipeline.py`)
* **`ToolDependencyGraphDispatcher`**: Constructs a 2-stage execution DAG. Stage 0 dispatches independent read-only tools concurrently via thread pools, followed by Stage 1 sequential write tool execution.
* **`MCPBatchPipelineAggregator`**: Bundles homogenous MCP tool requests targeting the same server into single batch JSON-RPC requests, eliminating redundant TCP/HTTP RTTs.
* **Architecture Spec**: [docs/architecture/57-dag-tool-dispatcher-and-mcp-batch-pipeline.md](docs/architecture/57-dag-tool-dispatcher-and-mcp-batch-pipeline.md)

### 🧠 3. Advanced Context Management 2.0
* **`DynamicTokenBudgetManager`**: Adapts to model context limits (DeepSeek 128K, Claude 200K, Qwen 32K) with strict **20% System / 40% Tool History / 30% Memory / 10% Output Reserve** physical isolation.
* **`SemanticContextPruner`**: Preserves dictionary key structures while applying head-2/tail-3 folding to large nested lists.
* **`TurnSlidingWindowSummarizer 2.0`**: Compresses >12 turn histories into a structured `[Selective Executive Insight Summary]` node with extracted Sharpe ratio, drawdown, and user directives.
* **Architecture Spec**: [docs/architecture/54-advanced-context-and-memory-management-v2-architecture.md](docs/architecture/54-advanced-context-and-memory-management-v2-architecture.md)

### 💾 4. Autonomous Memory Subsystem 3.0
* **`HierarchicalMemoryPyramid`**: 3-tier memory model: Working Memory (scratchpad), Episodic Memory (7-day task logs & backtests), Semantic Memory (long-term regime rules).
* **`EbbinghausDecayScorer`**: Composite score formula: $\text{Score} = 0.5 \text{Sim} + 0.3 e^{-0.05 \Delta t} + 0.2 \text{Imp}$.
* **`MemoryConsolidator`**: Merges duplicate observations ($>0.85$ similarity) into existing items.
* **`AutoReflexionMemoryFlusher`**: Automatically extracts post-task takeaways and flushes strategy rules into Semantic memory or error traces into Episodic memory.
* **`MarketRegimeMemoryFilter`**: Tags memories with `bull_trend`, `bear_crash`, `sideways_range`, or `high_volatility` and applies $0.5\times$ penalty score to cross-regime memory retrieval.
* **`MemoryContradictionResolver`**: Automatically flags older contradicted memory items as `deprecated: true`.
* **Architecture Spec**: [docs/architecture/55-autonomous-memory-v3-regime-filter-and-reflexion-flusher.md](docs/architecture/55-autonomous-memory-v3-regime-filter-and-reflexion-flusher.md)

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
    "objective": "Research a trend breakout strategy for BTC, auto-deploy to paper trading upon validation",
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
