# Sprint 89 - Route Context Metrics

## Goal

Give every routed Harness page an immediately scannable, page-specific metric strip so operators can understand the current surface before reading its detailed rows.

## In scope

- Preserve the existing Harness global telemetry cards as the workbench metric strip.
- Add read-only, route-specific metric cards to strategy, alerts, runs, Memory, and RAG pages.
- Derive each value from already loaded frontend state and clearly label its scope.
- Keep the dark observability design system, responsive layout, and existing route content intact.

## Out of scope

- New backend endpoints, database aggregations, or client polling.
- Changes to Agent, Memory, RAG, monitoring, approval, paper, or live behavior.
- Synthetic performance, risk, or storage metrics when source data is absent.

## Done means

- Every sidebar destination has a metric-card surface relevant to its own data.
- Cards remain accurate after refresh, search, and route navigation.
- Narrow layouts reflow without horizontal overflow.
- Existing frontend tests and `./scripts/check.sh` pass.

## Verification

- Add frontend coverage for representative strategy, alert, run, Memory, and RAG metric values.
- Browser-inspect all six paths at desktop and narrow widths.

## Handoff

- Route metric cards are presentation-only projections of loaded read data.
- New pages should use the shared metric strip rather than introducing unrelated dashboard chrome.
