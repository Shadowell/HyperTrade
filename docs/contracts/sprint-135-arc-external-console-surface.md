# Sprint Contract

## Sprint Name

`sprint-135-arc-external-console-surface`

## Goal

Open a restricted machine-facing surface on HyperTrade so an external console (BitPro) can start an
ARC mission, watch it progress, and read the evidence it produced, while the live-approval decision
stays bound to a verified human identity. HyperTrade keeps running as an independent service; the
console implements no research logic and holds no research state beyond a mission id.

The separation this sprint exists to establish: **a service token may start missions and read
everything; it may never approve one.**

## In Scope

- Service-token authentication for ARC routes, with a scope model (`arc:read`, `arc:start`) that
  structurally excludes approval scopes.
- Signed operator assertions so a human authenticated to BitPro can decide a live approval on
  HyperTrade without a HyperTrade session, and without HyperTrade trusting an unauthenticated
  caller-supplied name.
- `GET /api/v1/arc/missions` mission list with state filter and progress, for the console index.
- `GET /api/v1/arc/missions/{mission_id}/evidence`, a shaped evidence view suitable for rendering.
- `GET /api/v1/arc/missions/{mission_id}/candidates/{attempt_id}`, per-candidate drill-down
  including strategy source, red-team findings, and reflexion constraints.
- Progress fields (`candidates_used` / `max_candidates`) derived from the existing projection.

## Out of Scope

- Moving `run_autonomous_arc_loop` from `BackgroundTasks` into the worker process. Tracked as the
  next sprint; an API restart currently orphans a running mission and that is a separate reliability
  change with its own verification.
- Any push/webhook channel from HyperTrade to BitPro. The console polls in this sprint.
- Any BitPro-side page, table, or client code. This sprint delivers only the HyperTrade surface the
  console will consume.
- Evidence retention and garbage collection.
- Resolving whether BitPro's `live_promote` requires `confirm_live_risk` / `confirmation` fields.
  Recorded under Risks; it changes the final hop, not this surface.

## Deliverables

- `backend/src/hypertrade/arc/auth.py`: service principal resolution and operator assertion
  verification.
- ARC router: new list, evidence, and candidate endpoints; approval routes accept a signed operator
  assertion as an alternative to an admin session.
- `backend/src/hypertrade/config.py`: `ARC_SERVICE_TOKENS` (hashed) and
  `ARC_OPERATOR_ASSERTION_SECRET`.
- `tests/test_arc_external_surface.py`: scope enforcement, assertion verification, evidence shape.
- `docs/progress.md` and `docs/spec.md` updated for the new external contract.

### Authentication shape

Service calls present `X-HyperTrade-Service-Token: ht_svc_...`. Tokens are stored hashed and carry a
label and scopes. `arc:start` permits mission creation and budget extension; `arc:read` permits list,
read, evidence, and candidate drill-down. No token value grants approval.

Approval calls present `X-Operator-Assertion`, an HMAC-SHA256 signature over a payload binding
`mission_id`, `decision`, `operator_id`, `idempotency_key`, and `issued_at`. HyperTrade verifies the
signature, rejects assertions older than 300 seconds, and rejects any assertion whose `mission_id` or
`decision` does not match the request. Binding the decision and mission is what stops an assertion
captured for one mission from approving another. Replay inside the freshness window is absorbed by
the existing idempotency-key handling. The recorded approver is the asserted `operator_id` with an
`identity_source` of `bitpro_signed`, so the audit trail distinguishes it from a direct HyperTrade
session decision.

### Evidence view shape

Per candidate: family, direction, state, out-of-sample Sharpe, trade count, win rate, walk-forward
folds passed over folds total, ranking basis, and rejection reason codes paired with their human
text. Per mission: goal, state, progress, and the promotion chain (BitPro validation id, strategy id,
backtest id, self-test metrics, paper instance id, paper observation) plus the live-approval package
with its `unknowns`. The raw projection endpoint stays as it is for debugging.

## Done Means

- A caller holding only `arc:read` can list missions, read evidence, and drill into a candidate, and
  is refused with 403 on mission creation and on both approval routes.
- A caller holding `arc:start` can create a mission and extend a budget, and is refused with 403 on
  both approval routes.
- A request with no service token and no admin session is refused with 401 on every ARC route.
- A valid signed operator assertion decides an approval, and the recorded operator is the asserted
  identity with `identity_source="bitpro_signed"`.
- An assertion that is expired, tampered with, issued for a different mission, or issued for a
  different decision is refused and no decision is recorded.
- An existing admin session still decides approvals unchanged, recorded with its own identity source.
- The evidence view reports, for every candidate the mission tried, why it was rejected in structured
  reason codes, without returning strategy source for the whole candidate set.
- The mission list reports progress as candidates used against the budget, and flags missions
  awaiting approval.

## Verification

```bash
uv run pytest tests/test_arc_external_surface.py tests/test_arc_router_auth.py -q
uv run pytest tests/ -k arc -q
./scripts/check.sh
```

Manual or QA checks:

- Issue a read-scoped token and confirm with `curl` that mission creation returns 403 while the
  evidence view returns 200.
- Forge an operator assertion with a wrong secret and confirm the decision is refused and absent from
  the mission event stream.
- Replay a valid assertion against a second mission id and confirm it is refused.
- Render the evidence view for the mission produced by `scratch/gate2_e2e_probe.py` and confirm every
  rejected candidate carries a reason code.

## Risks / Notes

- Signed assertions mean HyperTrade trusts BitPro's authentication of the human. A BitPro compromise
  can therefore forge an ARC approval. This is accepted for this sprint because ARC approval alone
  does not move capital: the live promote is a further hop into BitPro. If that hop turns out not to
  require its own human confirmation fields, this trust boundary must be revisited before any live
  mandate is enabled.
- The shared signing secret is a server-only secret and must live in `/opt/hypertrade/.env`. It must
  not be committed and must be distinct from `SESSION_SECRET`.
- BitPro's documented live-write rule requires `confirm_live_risk=true` and
  `confirmation="I_UNDERSTAND_REAL_TRADING_RISK"`, and forbids an agent from supplying them, but
  `arc/live_promote.py` sends neither. Either the product-level `live_promote` does not require them
  or that path has never been exercised against a real BitPro. Must be verified against a live BitPro
  before a live mandate is enabled.
- The evidence view must not become a second source of truth. It is a projection of
  `ARCMissionProjection`; any field it reports must be derived, never stored separately.

## Handoff

- Next likely step: move `run_autonomous_arc_loop` out of FastAPI `BackgroundTasks` into the worker
  process with a lease on `ArcMission`, so an API restart resumes rather than orphans a mission.
- After that: verify the `live_promote` confirmation-field question against a real BitPro, then
  decide whether the signed-assertion trust boundary is sufficient for a live mandate.
