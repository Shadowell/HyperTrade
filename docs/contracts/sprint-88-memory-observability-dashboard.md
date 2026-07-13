# Sprint 88 - Memory Observability Dashboard

## Goal

Expand the read-only Harness Memory page into an operator-facing observability dashboard that makes active-memory composition, creation cadence, and governance metadata understandable at a glance.

## In scope

- Aggregate existing `GET /api/memory` items in the frontend without adding a new API or persistence path.
- Render a type capacity rail, per-type bars, creation-activity bars, and governance signals for importance, confidence, and reuse.
- Keep Memory search, selection, source provenance, and tags usable alongside the new dashboard.
- Preserve the dark observability design system and make charts responsive and accessible.

## Out of scope

- Memory writes, disables, deletes, retention limits, quotas, or changes to audit policy.
- A synthetic storage-capacity metric or any claim that active item count is a physical storage limit.
- Backend schema/API changes, chart dependencies, or changes to Agent/BitPro behavior.

## Done means

- `/harness/memory` shows real item-derived capacity, activity, and governance visualizations.
- Capacity visuals explicitly describe active-item composition rather than an unavailable storage quota.
- Search does not discard the full active inventory used by the dashboard.
- Existing frontend tests and `./scripts/check.sh` pass.

## Verification

- Test Memory rendering with multiple kinds, timestamps, importance, confidence, and reuse counts.
- Run the full repository check and browser-inspect the Memory route at desktop and narrow widths.

## Handoff

- The dashboard is read-only and derives all values client-side from audited API items.
- Future Memory metrics must remain source-bound and label unavailable values rather than estimating them.
