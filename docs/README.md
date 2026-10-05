# HyperTrade Documentation

This directory is the source of truth for HyperTrade product scope, architecture,
runbooks, and sprint state. Chat history is not considered durable project state.

## Start Here

- `spec.md`: product scope, V1 acceptance criteria, and explicit out-of-scope boundaries.
- `progress.md`: latest completed work, verification status, and deployment notes.
- `architecture/00-overview.md`: architecture document reading index and maintenance rules.
- `architecture/33-system-architecture.md`: canonical system architecture (Mission Runtime,
  control/data planes, multi-market targets, trust boundaries, lifecycle, safety and deployment).
- `architecture/66-quantlab-adapter-a-share-microstructure-and-relay-handover.md`: QuantLab
  market adapter, A-share microstructure hard rules, Co-STEER strategy transpiler and position netting relay.
- `architecture/67-production-observability-probes-and-token-rotation.md`: production container
  probes (`/livez`, `/readyz`, `/healthz`), zero-trust security token hot rotation and multi-target console.
- `architecture/65-rd-agent-evolution-and-finmem-layered-memory.md`: RD-Agent Hypothesis Evolution
  Tree (HET), Co-STEER structured synthesis and FinMem 3-tier cognitive memory.
- `architecture/64-autonomous-trading-agent-system-architecture.md`: end-to-end perception,
  tri-speed decision cycles, and bounded autonomous execution.
- `architecture/62-pluggable-market-targets.md` & `63-evolution-effectiveness-alerts-and-benchmark.md`:
  pluggable market targets and evolution engine hardening.
- `architecture/19-hypertrade-architecture-diagram.md`: poster-style HyperTrade architecture map.
- `runbooks/deployment-smoke.md`: post-deploy smoke checklist.
- `runbooks/bitpro-mcp-data-access.md`: BitPro MCP access and safety procedure.
- `runbooks/monitoring-alerts.md`: monitor execution and alert triage procedure.

## Current Capability Map

| Area | Current surface | Source of truth |
| --- | --- | --- |
| System architecture | Canonical system context, runtime layers, data flow, trust boundaries and deployment model | `architecture/33-system-architecture.md` |
| Architecture overview & maintenance | Architecture reading guide and synchronization rules | `architecture/00-overview.md` |
| Multi-market QuantLab & A-Share rules | QuantLab adapter, A-share rules (T+1, long-only, lot size), Transpiler, Position Netting Relay | `architecture/66-quantlab-adapter-a-share-microstructure-and-relay-handover.md` |
| Production probes & Token rotation | Container probes (`/healthz`, `/readyz`, `/livez`), TokenRotationService, Quantum console | `architecture/67-production-observability-probes-and-token-rotation.md` |
| RD-Agent HET & FinMem memory | Hypothesis Evolution Tree, Co-STEER synthesis, AST gatekeeper, 3-tier cognitive memory | `architecture/65-rd-agent-evolution-and-finmem-layered-memory.md` |
| Autonomous trading agent | Perception bus, tri-speed decision cycles, bounded autonomous execution | `architecture/64-autonomous-trading-agent-system-architecture.md` |
| Pluggable market targets | `market_target.v1` profile, `market-evolution.v1` MCP contract | `architecture/62-pluggable-market-targets.md` |
| Evolution hardening & alerts | Benchmark-relative decay, continuation ledger, effectiveness ledger, Feishu alerts | `architecture/63-evolution-effectiveness-alerts-and-benchmark.md` |
| Professional Mission Runtime | Mission/Plan/Step/Event, reviewed Catalog, Context, Supervisor, sandbox | `architecture/30-professional-agent-runtime-v2-roadmap.md`, `architecture/31-professional-agent-runtime-v2-technical-design.md` |
| Target architecture & audit | Canonical Thread/Turn protocol, state machines, tool governance, evaluation gates | `architecture/34-next-generation-agent-runtime-audit-and-target-design.md` |
| BitPro MCP & Paper evidence | Agent tools, API adapter, backtest artifacts, paper evidence snapshots | `architecture/17-bitpro-tool-adapter.md` |
| Strategy research & AVO loop | `/research`, `/backtest`, AVO research loop, adversarial red-teaming | `architecture/16-strategy-agent-workflow.md`, `architecture/37-arc-autonomous-research-core-architecture.md` |
| Provider routing | CLI `/model`, API, settings, multi-provider fallbacks | `architecture/13-provider-router.md` |
| Memory & RAG | `/memory`, `/rag`, pgvector storage, audited assertions | `architecture/05-rag-pgvector.md`, `architecture/06-memory.md` |
| CLI & TUI harness | `hypertrade`, `ht`, interactive streaming research watcher | `architecture/11-cli-conversation-harness.md` |
| Frontend workbench | Quantum portfolio dashboard, mission control, HET tree, relay monitor | `architecture/09-frontend-harness.md` |
| Deployment & ops | Docker Compose, Nginx, GitHub Actions CI/CD, `./scripts/check.sh` | `architecture/10-deployment.md`, `deployment.md` |

## Documentation Rules

1. **Architecture & Design Docs Synchronization (强约束)**:
   Whenever the overall architecture undergoes changes (such as new core modules, multi-market adapters,
   data/control flow updates, storage migrations, or execution model evolution), all related architecture
   design documents under `docs/architecture/`, `docs/spec.md`, `docs/progress.md`, sprint contracts,
   and both Chinese and English README files (`README.md`, `README.en.md`) MUST be updated promptly.
   Code evolution without synchronized design documentation is strictly forbidden.
2. Keep production behavior in docs, not only in chat.
3. Do not document secrets, tokens, provider keys, or production `.env` values.
4. Keep market boundaries explicit: HyperTrade uses stable MCP/API contracts and
   must not copy external platform business logic or bypass live-risk gates.
