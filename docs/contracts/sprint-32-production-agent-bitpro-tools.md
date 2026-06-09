# Sprint 32 Contract: Production Agent and BitPro Tool Surface

## Goal

Reposition HyperTrade as a production-grade, stable Agent capability platform and define the BitPro API capabilities required for safe tool calling.

## Scope

- Remove project copy that frames HyperTrade as a non-production showcase project.
- Keep concise source comments only where they explain production boundaries, auditability, risk, idempotency, or failure handling.
- Update the tool guide so it serves operators validating Agent capabilities.
- Define the BitPro-facing tool surface needed for:
  - backtest data and run artifacts
  - base market/reference data
  - paper and simulation state
  - live trading state
  - risk, permission, health, and audit metadata
- Keep HyperTrade independent from BitPro business logic. BitPro is an external provider reached through explicit API contracts.

## BitPro Capabilities Needed

### Cross-Cutting API Contract

- Service-to-service auth with separate read-only and write scopes.
- Environment separation for local, testnet/simulation, and production.
- Capability discovery endpoint that reports supported tools, versions, permissions, and disabled features.
- Health/version endpoint with data freshness and degraded-source flags.
- Stable error envelope with machine-readable codes, human messages, request id, retryability, and upstream status.
- Pagination, sorting, time-range filtering, and cursor support for large datasets.
- UTC timestamps, explicit timezone policy, and canonical OKX instrument ids such as `ETH-USDT-SWAP`.
- Rate-limit headers and deterministic retry guidance.
- Audit correlation fields: request id, actor/service, tool name, run id, decision id, and idempotency key.

### Backtest Data and Artifacts

- List available datasets by symbol, bar, source, start/end time, row count, and freshness.
- Fetch candle windows with validated OHLCV schema.
- Fetch archived strategy signals/features when available.
- Create or request a backtest run only if BitPro should own the run; otherwise HyperTrade only pulls data.
- Read backtest status, metrics, equity curve, orders, fills, trades, drawdown, and report artifacts.
- Preserve deterministic inputs so a HyperTrade Agent run can reproduce or audit the backtest.

### Base Market and Reference Data

- Instruments, status, tick size, lot size, min order size, contract value, leverage limits, and margin mode support.
- Latest tickers, recent candles, order book snapshots, trades, funding rates, open interest, and fee metadata.
- Source freshness per symbol and per data type.
- Explicit fallback behavior when OKX, cache, or BitPro-derived data is stale.

### Paper and Simulation State

- Paper sessions, balances/equity, positions, orders, fills, events, realized/unrealized PnL, and strategy links.
- Lifecycle controls: pause, resume, close position, reset session, and optional simulated order creation.
- Every write operation must accept an idempotency key and return an auditable event id.
- Simulation state must be clearly separated from live/testnet state.

### Live Trading State and Execution Boundaries

- Read live account balances, positions, open orders, order history, fills, subscriptions, and risk exposure.
- Expose live-write capabilities only behind explicit permissions and approval gates.
- If BitPro executes orders, provide precheck/dry-run, place, cancel, and amend endpoints with idempotency keys.
- Return exchange request/response metadata with secrets redacted.
- Support testnet/mainnet separation and a hard capability flag so HyperTrade can block unsupported or unsafe actions.

### Risk and Permissions

- Endpoint-level scopes for read, simulated write, testnet write, and live write.
- Account and symbol limits: max notional, max open orders, max leverage, min size, reduce-only support, and maintenance state.
- Current exposure summaries for symbols, strategies, and accounts.
- Structured refusal reasons that HyperTrade can surface directly in trace, CLI, and `/harness`.

### Observability and Audit

- Append-only audit log query by request id, tool call id, run id, symbol, account, or time range.
- Event stream or polling endpoint for long-running backtests, simulations, and live-order state changes.
- Redaction policy for secrets, account identifiers, and raw exchange credentials.
- SLA fields for freshness, latency, partial data, and degraded upstreams.

## Acceptance

- Project docs no longer describe HyperTrade as a non-production showcase project.
- `docs/spec.md`, `docs/progress.md`, and architecture docs describe production-grade Agent operation.
- BitPro tool-surface requirements are documented before implementation starts.
- No secrets, BitPro credentials, database files, or production `.env` are added.
- `./scripts/check.sh` passes.

## Verification

```bash
./scripts/check.sh
```

Also run a repository search for deprecated non-production positioning terms and resolve any matches that are not historical finance terms.
