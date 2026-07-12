# Sprint 83 - Paper Promotion and Observation

## Goal

Connect a validated Sprint 82 candidate to BitPro paper simulation through an explicit operator approval record, then attach read-only paper evidence to the same research lifecycle. The system can recommend review or retirement; it cannot promote to live trading.

## In Scope

- Add a `PaperPromotion` record linked to one mandate, `ResearchJob`, `StrategyCard`, and validation report.
- Create promotion requests only when the associated `ValidationGate` report passed and the mandate permits manual paper approval.
- Add an admin-protected approval action requiring a reason and unique idempotency key before `paper_configure` or `paper_start` can be called.
- Use BitPro MCP only to configure/start approved paper strategies and persist the returned strategy/session references.
- Associate existing `paper_dashboard`, `paper_events`, `paper_equity_curve`, monitor snapshots, and paper-performance matrix reads with the promoted candidate.
- Define observation states: `paper_observing`, `paper_degraded`, `paper_review_required`, `paper_retired`; preserve source evidence for every transition.
- Add operator API/CLI surfaces to inspect pending approvals, the paper observation summary, data gaps, and recommended next action.
- Keep paper monitoring read-only after start; recommendations to pause or retire require a separate operator action.

## Out of Scope

- Automatic approval, automatic paper start, auto-pause, auto-stop, or auto-reset.
- Live promotion, live order creation, capital transfer, or live allocation changes.
- Reinterpreting backtest results as current paper performance.
- A visual redesign of the full operator console beyond approval/inspection surfaces.

## Deliverables

- Promotion/approval persistence models and lifecycle service.
- Governance policy and idempotency enforcement for the paper-promotion transition.
- BitPro paper lifecycle adapter wiring with trace-safe correlation ids.
- Read-only observation summary that joins promotion, BitPro paper evidence, and monitor drift.
- API/CLI surfaces plus focused lifecycle, adapter, governance, report, and eval tests.
- Documentation update for paper approval and observation boundaries.

## Done Means

- A passing candidate appears as `pending_paper_approval`; a failing or incomplete candidate does not.
- An approval without a reason or idempotency key does not call BitPro.
- A valid approval configures and starts only the linked BitPro dynamic strategy, then persists the correlation ids and audit record.
- Dashboard identity mismatches, incomplete per-strategy coverage, and missing paper artifacts remain explicit data gaps.
- No Trace contains a live-write tool, live promotion, or automatic paper lifecycle mutation.

## Verification

```bash
uv run pytest tests/test_paper_promotion.py tests/test_research_orchestrator.py -q
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_bitpro_paper_monitor_service.py -q
uv run pytest tests/test_risk_governance_policy.py tests/test_agent_acceptance.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- Request paper promotion for a passing candidate, then confirm it cannot start until an administrator approves it.
- Inspect the same candidate after a paper monitor snapshot and verify dashboard/event/equity evidence remains linked and scoped.
- Attempt automatic or live promotion and confirm governance denies it before the adapter call.

## Risks / Notes

- Simulation is evidence collection, not proof of future profitability. Observation rules must preserve the difference between backtest and paper metrics.
- BitPro may expose incomplete per-strategy paper metrics; reports must name the coverage gap instead of deriving performance from aggregate dashboards.

## Handoff

Sprint 84 consumes approved/paper-observing `StrategyCard` records with WorldState evidence to provide a read-only, regime-aware portfolio research review.
