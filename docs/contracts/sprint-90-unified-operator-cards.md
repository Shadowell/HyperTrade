# Sprint 90 - Unified Operator Cards

## Goal

Make the strategy-library and monitoring/approval cards use the same operator-card system as the Harness metric surfaces, so evidence and alerts are comparably scannable without flattening their different risk meanings.

## In scope

- Introduce one shared visual card treatment for strategy evidence, monitor alerts, and approval-intent rows.
- Keep semantic tones: signal for passing/normal state, brass for evidence and pending review, danger for high-risk alert state.
- Preserve existing read-only data, selection actions, empty states, keyboard behavior, and mobile layout.
- Verify desktop and narrow rendering with real read data.

## Out of scope

- New backend endpoints, aggregation, polling, or persistence.
- Changes to alert, approval, strategy, paper, or live-trading behavior.
- Creating new navigation routes or changing the current page information architecture.

## Done means

- Strategy and alerts no longer use unrelated card/row visual systems.
- Card state remains distinguishable without relying on color alone.
- Existing tests and `./scripts/check.sh` pass; narrow layouts do not overflow.

## Verification

- Frontend coverage confirms strategy selection and alert/approval rendering still work.
- Browser-inspect strategy and alerts at desktop and 390px widths using existing data.

## Handoff

- Future operator content cards should use the shared treatment and explicit semantic tone.
