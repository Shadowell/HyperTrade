# 19 HyperTrade Architecture Diagram / 架构图

## Purpose

This document provides a poster-style HyperTrade architecture map for product
discussion, Agent handoff, and implementation planning.

The diagram is inspired by AI-native trading-system maps, but the content is
specific to HyperTrade:

- HyperTrade owns Agent planning, tool calling, trace, Memory, report rendering,
  strategy evidence, and risk governance.
- BitPro remains an external trading-system platform reached only through stable
  MCP/API contracts.
- OKX and future providers are connector inputs with explicit evidence
  boundaries.
- Live execution remains risk-gated. Mainnet execution is out of V1 scope.

![HyperTrade architecture](../assets/hypertrade-architecture.svg)

## Layer Responsibilities

| # | Layer | Responsibility |
| --- | --- | --- |
| 1 | Agent / Client Access | CLI `hypertrade`/`ht`, `/harness`, REST/SSE API, Codex, custom Agents, and future MCP clients. |
| 2 | Data and Inputs | OKX market data, BitPro MCP/API surfaces, RAG/pgvector, audited Memory, and operator prompts. |
| 3 | Governance Gateway | Provider routing, ToolRegistry metadata, approval checks, idempotency gates, trace, and audit policy. |
| 4 | Agent Engine | AgentKernel graph runtime, planner/tool-calling loop, market intelligence, strategy research/experiment/library/iteration, and report + Memory feedback. |
| 5 | World Model | Read-only WorldState snapshot, scenario decision scoring, defensive automation allowlist gate, and portfolio scheduler (Sprint 71-74). |
| 6 | Execution and Output | Operator reports, BitPro strategy lifecycle calls, paper trading runtime, and OKX Testnet execution after approval. |
| 7 | Monitoring and Alerts | Monitor definitions, alert events, scheduler worker loop (read-only, no paper/live write tools). |
| 8 | Foundation / Infrastructure | LLM providers, PostgreSQL/pgvector, async workers, connector framework, Alembic migrations, server secrets, CI/CD, Agent evals, and monitor loop. |
| 9 | Safety and Compliance | Audited runs, scoped tools, RBAC, idempotency, paper-first validation, and explicit live-risk approval; mainnet blocked in V1. |
| 10 | Closed-Loop Workflow | Market research -> strategy code -> validation -> BitPro backtest -> paper monitoring -> Memory feedback -> next iteration. |

## Logical Flow

```mermaid
flowchart TB
  subgraph Client["1. Client / Agent Access"]
    CLI["CLI / ht"]
    Harness["/harness"]
    API["REST / SSE"]
    Codex["Codex / External Agent"]
  end

  subgraph Data["2. Data & Inputs"]
    OKX["OKX Market Data<br/>tickers, candles, funding, OI"]
    BitPro["BitPro MCP/API<br/>K-lines, strategies, backtests, paper"]
    RAG["RAG / Knowledge<br/>pgvector semantic search"]
    Mem["Audited Memory<br/>strategy evidence, run conclusions"]
  end

  subgraph Gateway["3. Governance Gateway"]
    Provider["Provider Router<br/>DeepSeek / OpenAI / Codex / Qwen"]
    Registry["ToolRegistry<br/>schema, scope, approval, idempotency"]
    Risk["Risk Governance<br/>approval gates, live block"]
    Trace["Trace & Audit<br/>graph nodes, tool calls, policy decisions"]
  end

  subgraph Engine["4. Agent Engine"]
    Kernel["AgentKernel Graph Runtime<br/>intent → plan → approve → execute → reflect → report"]
    Planner["Planner + Tool Calling<br/>market, RAG, Memory, BitPro MCP"]
    Intel["Market Intelligence<br/>funding, OI, breadth, relative strength"]
    Strategy["Strategy Research Loop<br/>evidence → experiment → library → iteration"]
  end

  subgraph World["5. World Model"]
    WState["WorldState Snapshot<br/>global + crypto state"]
    Scenario["Scenario Decision<br/>action scoring"]
    Defensive["Defensive Automation<br/>allowlist gate"]
    Portfolio["Portfolio Scheduler<br/>allocation review"]
  end

  subgraph Output["6. Execution & Output"]
    Reports["Operator Reports<br/>structured Markdown + JSON"]
    BitProLifecycle["BitPro Strategy Lifecycle<br/>create, validate, backtest"]
    Paper["Paper Trading Runtime<br/>sessions, positions, fills"]
    Testnet["Risk-Gated Execution<br/>OKX Testnet only"]
  end

  subgraph Monitor["7. Monitoring & Alerts"]
    MonDef["Monitor Definitions"]
    Alerts["Alert Events"]
    Sched["Scheduler Worker"]
  end

  subgraph Infra["8. Foundation / Infrastructure"]
    LLM["LLM Providers"]
    DB["PostgreSQL + pgvector"]
    Workers["Async Workers"]
    Conn["Connector Framework"]
    CI["CI / CD"]
    Evals["Agent Evals"]
  end

  subgraph Safety["9. Safety & Compliance"]
    S1["scoped tools"]
    S2["RBAC"]
    S3["idempotency"]
    S4["paper-first"]
    S5["audit trail"]
    S6["no mainnet V1"]
  end

  Client --> Gateway
  Data --> Gateway
  Gateway --> Engine
  Engine --> World
  World --> Output
  Engine --> Output
  Gateway --> Safety
  Output --> Monitor
  Monitor -.->|read-only| Data
  Output -.->|evidence| Mem
  Mem -.->|feedback| Engine
```

## BitPro Boundary

HyperTrade may call BitPro through stable MCP/API tools for capability
discovery, health, K-line reads, strategy search/generate/create/update,
validation, backtest jobs/results, paper evidence, paper lifecycle actions, and
live diagnostics. HyperTrade must not copy BitPro business logic, query BitPro
databases directly, or bypass BitPro's risk boundaries.

## Design Notes

- Default reports should be concise and source-backed.
- Audit details should be available through trace/debug modes without cluttering
  normal operator output.
- Missing data must be rendered explicitly instead of silently inferred.
- Strategy memory is evidence, not investment advice.
- New connectors should enter through a capability/health/evidence contract
  before the planner can rely on them.
