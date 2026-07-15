# 00 Architecture Overview / 架构总览

## Start here / 从这里开始

- [33 System Architecture](33-system-architecture.md) is the canonical current system entry point:
  Mission Runtime, control/data planes, trust boundaries, lifecycle, safety, deployment, and
  contributor decisions.
- [19 Visual Architecture Map](19-hypertrade-architecture-diagram.md) is the concise layer diagram
  for product discussion.
- [30 Professional Agent Runtime V2 Roadmap](30-professional-agent-runtime-v2-roadmap.md) explains
  why the runtime was rebuilt and records the completed vertical-cutover plan.
- [31 Professional Agent Runtime V2 Technical Design](31-professional-agent-runtime-v2-technical-design.md)
  contains the concrete contracts for Mission, Catalog, Context, Supervisor, Sandbox and cutover.

## System boundary / 系统边界

HyperTrade owns the governed Agent control and research layer: Mission planning, evidence/Artifact
references, provider/tool governance, audit, reporting and human review. BitPro remains an external
trading-system provider for market/reference data, strategy storage, backtests, paper state and future
execution state, reached only through stable MCP/API contracts.

HyperTrade does not copy BitPro business logic, query BitPro databases directly, promise profitability,
or permit mainnet execution. Missing, stale or conflicting evidence remains visible as an explicit
unknown rather than becoming an inferred recommendation.

## Documentation maintenance / 文档维护

- Product scope and acceptance: [Product Spec](../spec.md)
- Current verified state: [Progress Log](../progress.md)
- Active delivery boundary: [Sprint contracts](../contracts/)
- Deployment and operational procedures: [Runbooks](../runbooks/)
