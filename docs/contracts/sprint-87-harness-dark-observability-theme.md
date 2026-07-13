# Sprint 87 - Harness Dark Observability Theme

## Goal

Unify every routed HyperTrade Harness page under the dark observability visual language already used by the Agent Flight Recorder, without changing research, risk, or trading behavior.

## In scope

- Replace the global Harness color tokens with deep green-black surfaces, light operational text, cyan state, amber audit, and red risk colors.
- Apply a restrained grid background and low-contrast panel borders across `/harness`, `/harness/strategy`, `/harness/alerts`, `/harness/runs`, `/harness/memory`, and `/harness/rag`.
- Update shell, navigation, panels, controls, inputs, reports, and empty states so they remain legible in the new theme.
- Preserve the Flight Recorder as the reference component and retain its existing telemetry semantics.

## Out of scope

- Backend/API changes, new data fetching, or changes to routing behavior.
- Changes to Agent tools, BitPro MCP, research evidence, paper lifecycle, approval, or live-trading controls.
- New design dependencies, new routes, or a marketing-site redesign.

## Done means

- All six Harness paths render the same dark observability visual system after direct navigation or refresh.
- Navigation, selected states, inputs, buttons, status colors, reports, and responsive layouts remain usable and accessible.
- Existing frontend tests and the repository verification script pass.

## Verification

- Run the existing frontend unit tests and build through `./scripts/check.sh`.
- Inspect every Harness path at desktop and narrow viewport widths with a browser smoke test.

## Handoff

- The global Tailwind tokens and shared component styles are the source of truth for future Harness surfaces.
- The Flight Recorder remains the visual reference for new operational telemetry components.
