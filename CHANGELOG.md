# Changelog

All notable changes to HyperTrade will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive documentation system
  - API Reference (English & Chinese)
  - User Manual (English & Chinese)
  - Developer Guide (English & Chinese)
  - Documentation Index
- Visual assets
  - Project logo (SVG)
  - Architecture flow diagram
- Enhanced README with professional presentation

## [0.1.0] - 2026-07-05

### Added
- **Agent Runtime**
  - LangGraph-style AgentKernel with graph execution
  - Provider router supporting DeepSeek, OpenAI, Codex, OpenRouter
  - Tool registry with policy enforcement (scope, approval, idempotency)
  - Natural language interaction with automatic tool selection

- **Market Intelligence**
  - Real-time OKX SWAP market data ingestion
  - Technical indicators (SMA, EMA, RSI)
  - Multi-symbol comparison and relative strength ranking
  - Funding rates and open interest tracking

- **Knowledge Systems**
  - RAG with pgvector-backed citation search
  - Audited Memory system with tags, confidence, importance
  - Knowledge document scanning and indexing

- **Strategy Development**
  - Evidence-driven research workflow
  - Backtrader integration for backtesting
  - Multi-variant experiments (baseline, fast, conservative)
  - Automatic winner selection through gate conditions
  - Strategy library aggregation from memory

- **BitPro Integration**
  - MCP adapter for strategy lifecycle operations
  - Backtest diagnostics and result retrieval
  - Paper trading monitoring
  - Live position and performance diagnostics (read-only)

- **Trading Execution**
  - Paper trading simulation with full lifecycle controls
  - Approval-gated Testnet order execution
  - Risk governance policy enforcement
  - Idempotent write operations with audit trail

- **Monitoring & Alerts**
  - Read-only monitors for paper strategies
  - Connector health checks
  - Strategy library freshness monitoring
  - Alert system with severity levels

- **Client Surfaces**
  - CLI with command history, colors, and remote mode
  - Web console at `/harness` with React + Vite
  - REST/SSE API with OpenAPI documentation
  - Streaming support for long-running Agent tasks

- **Evaluation & Testing**
  - Deterministic eval suite for tool choice, RAG, Memory, risk
  - Regression guards for report quality and routing
  - Automated testing with pytest and frontend tests

- **Infrastructure**
  - Docker Compose deployment
  - GitHub Actions CI/CD pipeline
  - Self-hosted runner support
  - PostgreSQL with pgvector extension
  - SQLite support for development

- **Experimental Features**
  - World model with portfolio state tracking
  - Defensive action engine with scheduling

### Changed
- N/A (initial release)

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- Session-based authentication for privileged operations
- HttpOnly, SameSite cookies
- BitPro boundary enforcement (MCP/API contracts only)
- Audit trail for all tool executions
- Mainnet live execution blocked in V1

## [0.0.1] - 2026-06-01

### Added
- Initial project setup
- Basic Agent skeleton
- Market data ingestion proof of concept

---

## Release Notes

### Version 0.1.0 - Production-Ready Agent Runtime

This is the first production-ready release of HyperTrade, providing a complete Agent-driven environment for crypto trading research and execution.

**Highlights**:
- 🤖 Intelligent Agent with natural language interaction
- 📊 Real-time market intelligence from OKX
- 🧪 Evidence-driven strategy research and backtesting
- 🎮 Paper trading with approval-gated Testnet execution
- 🔗 BitPro integration via MCP adapter
- 💾 RAG knowledge retrieval and audited Memory
- 🛡️ Governance layer with risk policy enforcement
- 📱 Multi-surface access (CLI, Web, API)

**Breaking Changes**: None (initial release)

**Migration Guide**: N/A

**Known Issues**:
- Mainnet live execution is blocked in V1
- Large trace event tables may impact performance over time
- WebSocket support not yet implemented (use SSE for streaming)

**Upgrade Instructions**: N/A (initial release)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for information on how to contribute to this changelog.

## Links

- [Documentation](docs/documentation-index.md)
- [API Reference](docs/api-reference.md)
- [User Manual](docs/user-manual.md)
- [Developer Guide](docs/developer-guide.md)
