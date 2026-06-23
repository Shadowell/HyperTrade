# Sprint 57 - HyperTrade Architecture Diagram

## Goal

Create a maintainable HyperTrade architecture diagram that mirrors a layered
AI-native trading-system map while staying faithful to current HyperTrade
responsibilities and BitPro boundaries.

## Scope

- Add a poster-style SVG architecture diagram under `docs/assets/`.
- Add an architecture note under `docs/architecture/` explaining the diagram,
  layer responsibilities, logical flow, and BitPro boundary.
- Link the diagram from the documentation index and keep project progress up to
  date.

## Out of Scope

- Runtime behavior changes.
- New Agent tools, connectors, frontend UI, or API routes.
- Any claim that HyperTrade owns BitPro business logic or mainnet execution.

## Acceptance

- The diagram shows client access, data inputs, Agent gateway, HyperTrade
  engine, execution/output, multi-Agent workflow, infrastructure, closed-loop
  workflow, and safety/compliance.
- The diagram and document make the HyperTrade/BitPro boundary explicit.
- The SVG is valid XML and can be rendered by a browser or documentation viewer.
- `./scripts/check.sh` passes before the docs are pushed.

## Verification

```bash
xmllint --noout docs/assets/hypertrade-architecture.svg
./scripts/check.sh
```
