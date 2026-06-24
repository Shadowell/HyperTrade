# Sprint 70 - Architecture SVG Text Fit

## Goal

Fix visible text overflow in the right-side panels of the README architecture
diagram so the poster renders cleanly in GitHub and local previews.

## In Scope

- Wrap long right-side panel titles in `docs/assets/hypertrade-architecture.svg`.
- Split long English body lines in the Execution, Multi-Agent, and Safety
  panels.
- Slightly increase the affected panel/card heights where needed.
- Verify the SVG is valid XML and render-check the right-side crop.

## Out of Scope

- Redesigning the whole architecture poster.
- Changing README prose, runtime behavior, Agent routing, APIs, or deployment
  mechanics.
- Editing unrelated Sprint 69 README framework guide work.

## Done Means

- The `Execution and Output`, `Multi-Agent Workflow`, and
  `Safety and Compliance` panels no longer show text outside their borders.
- `docs/assets/hypertrade-architecture.svg` passes XML validation.
- A local browser render confirms the right-side crop fits within panel bounds.

## Verification

```bash
xmllint --noout docs/assets/hypertrade-architecture.svg
./scripts/check.sh
```

Manual or QA checks:

- Render `docs/assets/hypertrade-architecture.svg` in a browser and inspect the
  right-side panels.

## Handoff

- Next likely step: continue any separate README framework-guide work without
  restaging this visual hotfix.
