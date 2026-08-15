# ARC External Console Integration

Implementation-ready framework design spanning two repositories:

- `HyperTrade` at `/Users/jie.feng/Dev/Github/Private/HyperTrade` — owns ARC, keeps running standalone.
- `BitPro` at `/Users/jie.feng/Dev/Github/Private/BitPro` — gains a console page that drives ARC.

Sprint contract: `docs/contracts/sprint-135-arc-external-console-surface.md` (HyperTrade side only).

## 1. Topology and the invariant

BitPro implements no research logic and stores no research state beyond a mission id. It calls
HyperTrade over HTTP with a service token, renders what comes back, and relays a human approval.

```
BitPro UI  ──POST /api/v2/arc/missions──▶  BitPro API  ──X-HyperTrade-Service-Token──▶  HyperTrade
    ▲                                          │                                            │
    │                                          │                                       ARC worker
    └───────── poll evidence ──────────────────┘                                            │
                                                                                    BitPro MCP (self-test,
    human clicks approve                                                             paper, live promote)
        │
        └─▶ BitPro signs assertion ──X-Operator-Assertion──▶ HyperTrade records the decision
```

**The invariant that governs every decision below: a service token may start missions and read
everything, and may never approve one.** Approval requires a signed human assertion. This is enforced
structurally through the scope model, not by a conditional in a handler.

## 2. HyperTrade side

### 2.1 Settings — `backend/src/hypertrade/config.py`

Follow the existing `Field(default=..., alias="UPPER_SNAKE")` pattern.

| Field | Alias | Default | Meaning |
|---|---|---|---|
| `arc_service_tokens` | `ARC_SERVICE_TOKENS` | `""` | `label:scope1+scope2:sha256hex` entries, comma separated |
| `arc_operator_assertion_secret` | `ARC_OPERATOR_ASSERTION_SECRET` | `""` | HMAC key shared with BitPro |
| `arc_operator_assertion_max_age_seconds` | `ARC_OPERATOR_ASSERTION_MAX_AGE_SECONDS` | `300` | freshness window |

Tokens are stored as SHA-256 hex, never plaintext. Empty secret disables assertion auth entirely
(sessions still work), so a misconfigured deployment fails closed rather than accepting unsigned
assertions.

### 2.2 New module — `backend/src/hypertrade/arc/auth.py`

```python
class ARCScope(StrEnum):
    READ = "arc:read"
    START = "arc:start"
    # No approve scope exists. Approval is not a token capability.

@dataclass(frozen=True)
class ServicePrincipal:
    label: str
    scopes: frozenset[ARCScope]

@dataclass(frozen=True)
class OperatorIdentity:
    operator_id: str
    identity_source: Literal["hypertrade_session", "bitpro_signed"]

def resolve_service_principal(request: Request) -> ServicePrincipal | None:
    """Read X-HyperTrade-Service-Token, hash it, match against configured tokens."""

def require_scope(scope: ARCScope) -> Callable[[Request], None]:
    """FastAPI dependency factory. 401 when unauthenticated, 403 when scope is absent."""

def verify_operator_assertion(
    request: Request, *, mission_id: str, decision: str, idempotency_key: str
) -> OperatorIdentity | None:
    """Verify X-Operator-Assertion against the request it claims to authorize."""
```

`require_scope` must accept **either** a valid service token carrying the scope **or** an admin
session (`request.state.admin_user`, set by `require_admin` in `main.py`). A human browsing
HyperTrade directly keeps working unchanged.

#### Assertion format

Header: `X-Operator-Assertion: v1:{issued_at}:{operator_id_b64url}:{signature_hex}`

Signed payload, reconstructed by the verifier from the actual request rather than from the header:

```
v1|{mission_id}|{decision}|{operator_id}|{idempotency_key}|{issued_at}
```

`signature = HMAC-SHA256(arc_operator_assertion_secret, payload)`, compared with
`hmac.compare_digest`.

Because `mission_id`, `decision`, and `idempotency_key` are taken from the path and body and are not
re-transmitted in the header, an assertion captured for one mission cannot authorize another, and an
approve assertion cannot be replayed as a reject. Reject `issued_at` older than the max age or more
than 60 seconds in the future. Replay inside the window is already absorbed by the existing
idempotency-key handling in the decide route.

### 2.3 Router — `backend/src/hypertrade/arc/router.py`

Remove the blanket `dependencies=[Depends(require_admin)]` on the ARC router in `main.py` and apply
per-route scopes instead. Keeping the router mounted bare again is not acceptable; every route must
carry an explicit dependency.

| Route | Dependency | Notes |
|---|---|---|
| `POST /missions` | `require_scope(START)` | existing |
| `POST /missions/{id}/continue` | `require_scope(START)` | existing |
| `GET /missions` | `require_scope(READ)` | **new** |
| `GET /missions/{id}` | `require_scope(READ)` | existing, raw projection, unchanged shape |
| `GET /missions/{id}/evidence` | `require_scope(READ)` | **new** |
| `GET /missions/{id}/candidates/{attempt_id}` | `require_scope(READ)` | **new** |
| `GET /missions/{id}/live-approval` | `require_scope(READ)` | existing |
| `GET /evidence/preflight` | `require_scope(READ)` | existing |
| `POST /missions/{id}/live-approval/decide` | session **or** assertion | never a token alone |
| `POST /missions/{id}/live-approval/revoke` | session **or** assertion | never a token alone |

`_require_operator` becomes: use the admin session identity if present; otherwise call
`verify_operator_assertion`; otherwise 401. It must no longer fall back to the `X-Operator-Id` header
value as an identity. The header may remain accepted as a hint only when an assertion or session
already established the identity and the two agree.

#### `GET /missions`

Query: `state` optional, `limit` default 50 max 200. Built from `store.list_mission_ids(state=...)`
plus each controller's projection. Returns summaries only, never candidate bodies:

```json
{"missions": [{
  "mission_id": "arc_...", "state": "live_approval_ready",
  "objective": "...", "symbol": "ETH-USDT-SWAP", "timeframe": "1H",
  "created_by": "...", "created_at": "...", "updated_at": "...",
  "progress": {"candidates_used": 37, "max_candidates": 90},
  "awaiting_approval": true, "survivor_count": 1
}]}
```

`candidates_used` is `len(projection.attempts)`; `max_candidates` is
`projection.goal.budget.max_candidates`. `awaiting_approval` is
`state == "live_approval_ready"` or a `live_approval` package whose status is `ready`.

#### `GET /missions/{id}/evidence`

New module `backend/src/hypertrade/arc/evidence_view.py` with a single pure function:

```python
def build_evidence_view(projection: ARCMissionProjection) -> dict[str, Any]:
```

It must be a pure projection of `ARCMissionProjection` and must not read the database or store
anything. The evidence view is a rendering, never a second source of truth.

```json
{
  "mission": {"mission_id": "...", "state": "...", "objective": "...",
              "symbol": "...", "timeframe": "...", "progress": {...}},
  "candidates": [{
    "attempt_id": "...", "candidate_id": "...", "state": "rejected",
    "family": "donchian_breakout", "direction": "short_only",
    "oos_sharpe": 1.64, "trades": 23, "win_rate": 0.52,
    "folds_passed": 3, "folds_total": 4, "ranking_basis": "out_of_sample",
    "rejections": [{"code": "OOS_SAMPLE_TOO_SMALL", "text": "样本外成交笔数不足..."}]
  }],
  "promotion": {"bitpro_strategy_id": "...", "bitpro_backtest_id": "...",
                "validation_id": "...", "paper_instance_id": "...",
                "self_test": {...}, "paper_observation": {...}},
  "approval": {"status": "ready", "unknowns": []}
}
```

Field derivation:

- `family` / `direction` from `attempt.strategy_spec`.
- `oos_sharpe`, `trades`, `win_rate`, `folds_passed`, `folds_total`, `ranking_basis` from
  `attempt.observed_metrics`.
- `rejections` from `attempt.reflexion_events`: `reason_codes` paired with `negative_constraints`,
  which already carry the human-readable remediation text.
- `promotion` from the attempt fields plus `projection.self_test_records` and
  `projection.paper_observation`.
- `approval` from `projection.live_approval`.

**`strategy_code` must not appear in this response.** Ninety candidates of source is unrenderable and
turns a list view into a megabyte payload. Source lives behind the drill-down.

#### `GET /missions/{id}/candidates/{attempt_id}`

One candidate in full: everything the list row carries, plus `strategy_code`, `strategy_spec`, and
the complete `reflexion_events`. 404 when the attempt id is not in the mission.

### 2.4 Tests — `tests/test_arc_external_surface.py`

Name tests after the behaviour they defend, matching the existing ARC test style.

- A read-scoped token lists, reads evidence, drills down; is refused 403 on create and on both
  approval routes.
- A start-scoped token creates and extends; is refused 403 on both approval routes.
- No token and no session is 401 on every route.
- A valid assertion decides; the recorded operator is the asserted id with
  `identity_source="bitpro_signed"`.
- A tampered signature, an expired `issued_at`, a future `issued_at`, an assertion signed for a
  different mission, and an assertion signed for a different decision are each refused, and no
  `live_decided` event is appended.
- An empty `ARC_OPERATOR_ASSERTION_SECRET` refuses every assertion.
- An admin session still decides, recorded as `hypertrade_session`.
- The evidence view carries a reason code for every rejected candidate and no `strategy_code`.
- The evidence view is byte-identical when built twice from the same projection.

Extend `tests/test_arc_router_auth.py` rather than replacing it; its anonymous-caller assertions
still hold.

## 3. BitPro side

Conventions to follow, discovered from the existing codebase — do not invent alternatives:

- Endpoint modules live in `backend/app/api/v2/endpoints/`, are registered in
  `backend/app/api/v2/api.py`, and return `ok(...)` / `fail(...)` from `app.core.contracts`.
- Outbound HTTP uses `httpx.AsyncClient(timeout=..., trust_env=False)`.
- Auth is global middleware (`app/core/auth_middleware.py`), not per-route dependencies. Sessions
  carry `role` of `admin` or `guest`.
- Frontend pages live in `frontend/src/pages/`, are lazily routed in `frontend/src/App.tsx`, and
  appear in the `navItems` array in `frontend/src/components/MainLayout.tsx`.
- The frontend calls `/api/v2` through the axios instance in `frontend/src/api/client.ts`.

### 3.1 Settings — `backend/app/core/config.py`

`HYPERTRADE_BASE_URL` (default `""`), `HYPERTRADE_SERVICE_TOKEN`,
`HYPERTRADE_APPROVAL_SIGNING_SECRET`. An empty base URL disables the console; the page must render a
clear "未配置" state rather than erroring.

### 3.2 Client — `backend/app/services/hypertrade_client.py`

Thin transport only. No business logic, no reshaping of ARC payloads, no caching of evidence.

```python
class HyperTradeClient:
    async def create_mission(self, **payload) -> dict
    async def list_missions(self, *, state: str | None, limit: int) -> dict
    async def get_evidence(self, mission_id: str) -> dict
    async def get_candidate(self, mission_id: str, attempt_id: str) -> dict
    async def get_live_approval(self, mission_id: str) -> dict
    async def decide(self, mission_id: str, *, decision: str, reason: str,
                     operator_id: str, idempotency_key: str) -> dict

def sign_operator_assertion(*, mission_id: str, decision: str, operator_id: str,
                            idempotency_key: str, issued_at: int, secret: str) -> str
```

`sign_operator_assertion` must produce exactly the format in section 2.2. It is the mirror of
HyperTrade's verifier and the two must be changed together.

Map HyperTrade's 401/403 to BitPro `fail("HYPERTRADE_UNAUTHORIZED", ...)` and connection failures to
`fail("HYPERTRADE_UNREACHABLE", ...)`; never surface a raw upstream traceback.

### 3.3 Endpoints — `backend/app/api/v2/endpoints/arc.py`

Registered with `prefix="/arc"`, `tags=["ARC v2"]`.

| BitPro route | Upstream | Notes |
|---|---|---|
| `GET /arc/config` | none | reports whether the console is configured |
| `POST /arc/missions` | `POST /api/v1/arc/missions` | the switch |
| `GET /arc/missions` | `GET /api/v1/arc/missions` | index |
| `GET /arc/missions/{id}/evidence` | same | the evidence table |
| `GET /arc/missions/{id}/candidates/{attempt_id}` | same | drill-down |
| `POST /arc/missions/{id}/decide` | `.../live-approval/decide` | signs the assertion |

The decide route is where the human identity is minted. Read it from `request.state.auth`, refuse
when `role != "admin"`, generate `issued_at` and an `idempotency_key` server-side, sign, and forward.
**The operator id must come from the verified session, never from the request body** — accepting it
from the client would reintroduce exactly the forgery this design exists to prevent.

### 3.4 Guest access — `backend/app/core/auth_middleware.py`

`guest_can_access` currently allows guests every `GET` under `/api/v2/` except `/api/v2/settings`.
Add `/api/v2/arc` to that same denial, because the evidence view exposes research output and the
drill-down exposes strategy source.

### 3.5 Frontend

- `frontend/src/pages/ArcConsole.tsx`, lazily imported and routed at `path="arc"` in `App.tsx`.
- A `navItems` entry: `{ path: '/arc', icon: Bot, label: '自主研究', allowedRoles: ['admin'] }`.
  Admin only, matching the middleware denial.
- API functions added to `frontend/src/api/client.ts` alongside the existing ones.

Page structure, three regions:

1. **启动区** — objective, symbol, timeframe, max candidates, then the switch. Disabled with an
   explanatory note when `GET /arc/config` reports unconfigured.
2. **任务列表** — one row per mission with state, progress bar from `candidates_used /
   max_candidates`, and a badge when `awaiting_approval`. Poll every 5 seconds while any mission is
   in a running state; stop polling when none are.
3. **证据与审批** — for the selected mission, the candidate table (family, direction, OOS Sharpe,
   trades, folds passed, rejection reason), a row click opening the drill-down with source and
   findings, and the approval card showing the package `status` and `unknowns`. The approve button
   is disabled whenever `unknowns` is non-empty, and each unknown is rendered as a readable line so
   the operator sees precisely what evidence is missing.

The approval card must show the promotion chain — BitPro validation id, strategy id, backtest id,
paper instance id, and the paper observation — because that is the evidence the human is being asked
to judge.

### 3.6 Tests

Backend: assertion signing matches a known vector; the decide route refuses a guest session; the
operator id in the forwarded assertion is the session user and not a body field; an unconfigured base
URL yields a clean disabled state rather than a 500.

Frontend: the approve button is disabled while `unknowns` is non-empty.

## 4. Implementation order

1. HyperTrade `arc/auth.py` plus settings, with tests. Everything downstream depends on the scope
   model, so its shape must settle first.
2. HyperTrade router rewiring to per-route scopes, keeping existing routes working.
3. HyperTrade `evidence_view.py` and the three new endpoints.
4. `./scripts/check.sh`, commit, push, deploy.
5. BitPro settings and `hypertrade_client.py`, with the signing vector test cross-checked against
   HyperTrade's verifier.
6. BitPro `arc.py` endpoints and the guest denial.
7. BitPro `ArcConsole.tsx`, routing, nav entry.

Steps 1 to 4 are the sprint-135 contract and are independently shippable: HyperTrade gains the
surface whether or not the console exists yet.

## 5. Invariants an implementer must not break

- No token scope grants approval. If a future requirement seems to need one, the requirement is
  wrong.
- The recorded approver identity is always derived from a verified session or a verified signature,
  never from a caller-supplied field.
- The evidence view is a pure projection of `ARCMissionProjection`. It never persists and never
  becomes a parallel store.
- BitPro holds no research state beyond the mission id. Any temptation to cache candidates or
  metrics in BitPro's database recreates the two-sources-of-truth problem this design avoids.
- Strategy source is drill-down only, never in a list response.

## 6. Open question that outranks this design

`arc/live_promote.py` sends neither `confirm_live_risk` nor
`confirmation="I_UNDERSTAND_REAL_TRADING_RISK"`, although BitPro's documented live-write rule
requires both and forbids an agent from supplying them. Either the product-level `live_promote` does
not require them, or that path has never run against a real BitPro.

This matters to the trust boundary. Signed assertions mean HyperTrade trusts BitPro's authentication
of the human, so a BitPro compromise could forge an ARC approval. That is acceptable only while the
live promote remains a second, independently confirmed hop. **Verify against a real BitPro before
enabling any live mandate.** If the confirmation fields are required, the right design is for the
operator to supply them in BitPro at the final hop, giving two human gates.
