# HyperTrade Documentation

This directory is the source of truth for HyperTrade product scope, architecture,
runbooks, and sprint state. Chat history is not considered durable project state.

## Start Here

- `spec.md`: product scope, V1 acceptance criteria, and explicit out-of-scope boundaries.
- `progress.md`: latest completed work, verification status, and deployment notes.
- `architecture/18-hypertrade-capability-roadmap.md`: post-Sprint-44 capability
  roadmap and parallel sprint plan for Agent development.
- `architecture/20-connector-framework.md`: trusted connector capability
  registry and BitPro compatibility path.
- `contracts/sprint-55-cli-slash-command-candidates.md`: focused CLI polish
  contract for slash command candidate filtering.
- `contracts/sprint-56-market-heat-summary.md`: focused market-reporting
  contract for summary-first market heat answers.
- `agent-prompts/parallel-sprint-prompts.md`: copy-ready prompts for Agents
  implementing Sprint 45-54 in parallel.
- `knowledge/tool-usage-guide.md`: operator-facing guide for validating Agent tools.
- `knowledge/connector-framework-guide.md`: steps and safety rules for adding
  trusted connectors.
- `runbooks/deployment-smoke.md`: post-deploy smoke checklist.
- `runbooks/bitpro-mcp-data-access.md`: BitPro MCP access and safety procedure.
- `runbooks/monitoring-alerts.md`: monitor execution and alert triage procedure.

## Current Capability Map

| Area | Current surface | Source of truth |
| --- | --- | --- |
| Agent graph and trace | API, CLI, `/harness` | `architecture/12-agent-graph-langgraph-runtime.md` |
| Provider routing | CLI `/model`, API, settings | `architecture/13-provider-router.md` |
| Tool calling | Agent planner, ToolRegistry, trace | `architecture/04-tool-calling.md` |
| RAG | `/rag`, `/api/rag/search`, Memory/RAG panels | `architecture/05-rag-pgvector.md` |
| Memory | `/memory`, `/api/memory`, audited items | `architecture/06-memory.md` |
| Strategy research | `/research`, `/backtest`, `/experiment` | `architecture/16-strategy-agent-workflow.md` |
| Strategy knowledge memory | `/strategy library`, `GET /api/strategy/library`, `kind=strategy_knowledge` memory search | `knowledge/strategy-research-playbook.md` |
| BitPro MCP | Agent tools, API adapter, backtest artifacts, paper evidence snapshots | `architecture/17-bitpro-tool-adapter.md` |
| Connector framework | `GET /api/connectors/capabilities`, CLI `/connectors`, ToolRegistry origin metadata | `architecture/20-connector-framework.md`, `knowledge/connector-framework-guide.md` |
| Monitoring and alerts | `/monitors`, `/monitor run`, `/alerts`, monitor API | `runbooks/monitoring-alerts.md` |
| Capability roadmap | Parallel Agent sprint contracts after Sprint 44 | `architecture/18-hypertrade-capability-roadmap.md` |
| Parallel Agent prompts | Copy-ready prompts for Sprint 45-54 Agents | `agent-prompts/parallel-sprint-prompts.md` |
| Risk/Testnet execution | `/live intent`, `/live approve`, `/live execute` | `architecture/14-risk-engine.md`, `architecture/15-okx-testnet-execution.md` |
| CLI | `hypertrade`, `ht`, slash commands | `architecture/11-cli-conversation-harness.md` |
| Frontend workbench | `/harness` core console | `architecture/09-frontend-harness.md` |
| Deployment | GitHub Actions, Docker Compose, Nginx | `architecture/10-deployment.md`, `deployment.md` |

## Documentation Rules

- Keep production behavior in docs, not only in chat.
- Do not document secrets, tokens, provider keys, or production `.env` values.
- If a feature changes API behavior, update `spec.md`, relevant architecture docs,
  the active sprint contract, and `progress.md` in the same change.
- Keep BitPro boundaries explicit: HyperTrade uses stable MCP/API contracts and
  must not copy BitPro business logic or bypass live-risk gates.
