# Paper Trading Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automatic paper-trading runtime that uses existing OKX SWAP ticker snapshots, persists simulated orders/fills/positions, and exposes pause/resume plus runtime state in `/harness`.

**Architecture:** Add a focused `hypertrade.paper` domain with signal, execution, repository, and service modules. The worker owns autorun scheduling; FastAPI exposes status/control APIs; `/harness` consumes the same overview payload so the UI remains a single operational surface.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, pytest, React/Vite/TypeScript/Tailwind, Vitest.

---

## File Map

- Modify `backend/src/hypertrade/db.py`: add paper trading ORM models.
- Create `backend/alembic/versions/0002_paper_trading.py`: add production schema.
- Create `backend/src/hypertrade/paper/models.py`: dataclasses for signals, sizing, fills, and status DTOs.
- Create `backend/src/hypertrade/paper/repository.py`: persistence queries and mutations.
- Create `backend/src/hypertrade/paper/engine.py`: deterministic V1 signal, sizing, fee/slippage, and fill math.
- Create `backend/src/hypertrade/paper/service.py`: session bootstrap, tick execution, pause/resume, status assembly.
- Modify `backend/src/hypertrade/worker.py`: add `paper_trading_loop`.
- Modify `backend/src/hypertrade/main.py`: add `/api/paper/status`, `/api/paper/control`, and paper summary in `/api/harness/overview`.
- Modify `backend/src/hypertrade/config.py`: add paper runtime settings.
- Create `tests/test_paper_engine.py`: pure domain tests.
- Create `tests/test_paper_service.py`: SQLite-backed persistence/control tests.
- Modify `tests/test_api.py`: paper API and harness overview assertions.
- Modify `frontend/src/App.tsx`: paper runtime section and pause/resume actions.
- Modify `frontend/src/App.test.tsx`: render paper overview and control affordances.
- Modify `frontend/src/styles.css`: paper runtime visual states.
- Modify `docs/progress.md`: record Sprint 02 implementation/verification.

---

### Task 1: Paper Schema And Config

**Files:**
- Modify: `backend/src/hypertrade/config.py`
- Modify: `backend/src/hypertrade/db.py`
- Create: `backend/alembic/versions/0002_paper_trading.py`
- Test: `tests/test_paper_service.py`

- [ ] **Step 1: Write the failing schema smoke test**

Add `tests/test_paper_service.py`:

```python
from hypertrade.db import Database, PaperSession
from hypertrade.paper.service import PaperTradingService


def test_paper_service_bootstraps_default_session():
    db = Database("sqlite:///:memory:")
    db.create_all()

    session = PaperTradingService(db).ensure_default_session()

    assert session.id.startswith("paper_")
    assert session.status == "running"
    assert session.cash == "100000"
    with db.session() as db_session:
        assert db_session.get(PaperSession, session.id) is not None
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
uv run pytest tests/test_paper_service.py::test_paper_service_bootstraps_default_session -q
```

Expected: fail because `PaperSession` and `PaperTradingService` do not exist.

- [ ] **Step 3: Add config fields**

In `backend/src/hypertrade/config.py`, add:

```python
paper_enabled: bool = Field(default=True, alias="PAPER_ENABLED")
paper_loop_interval_seconds: int = Field(default=30, alias="PAPER_LOOP_INTERVAL_SECONDS")
paper_starting_equity_usdt: str = Field(default="100000", alias="PAPER_STARTING_EQUITY_USDT")
paper_max_positions: int = Field(default=10, alias="PAPER_MAX_POSITIONS")
paper_max_symbol_notional_pct: str = Field(default="0.20", alias="PAPER_MAX_SYMBOL_NOTIONAL_PCT")
paper_max_leverage: str = Field(default="5", alias="PAPER_MAX_LEVERAGE")
paper_taker_fee_bps: str = Field(default="5", alias="PAPER_TAKER_FEE_BPS")
paper_slippage_bps: str = Field(default="2", alias="PAPER_SLIPPAGE_BPS")
```

- [ ] **Step 4: Add ORM models**

In `backend/src/hypertrade/db.py`, add models:

```python
class PaperSession(Base, TimestampMixin):
    __tablename__ = "paper_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("paper"))
    name: Mapped[str] = mapped_column(String(128), default="Default Paper Session")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    equity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaperPosition(Base, TimestampMixin):
    __tablename__ = "paper_positions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pos"))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    mark_price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    notional: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)


class PaperOrder(Base, TimestampMixin):
    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ord"))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    target_notional: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class PaperFill(Base, TimestampMixin):
    __tablename__ = "paper_fills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("fill"))
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    inst_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    price: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    fee: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source_ticker_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperEvent(Base, TimestampMixin):
    __tablename__ = "paper_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pevt"))
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
```

- [ ] **Step 5: Add Alembic migration**

Create `backend/alembic/versions/0002_paper_trading.py` with matching `op.create_table` calls, indexes on `session_id`, `inst_id`, `status`, and a downgrade that drops paper tables in reverse order.

- [ ] **Step 6: Add minimal service bootstrap**

Create `backend/src/hypertrade/paper/service.py` with `ensure_default_session()` returning a DTO with `id`, `status`, `cash`, and `equity`.

- [ ] **Step 7: Run the focused test**

Run:

```bash
uv run pytest tests/test_paper_service.py::test_paper_service_bootstraps_default_session -q
```

Expected: pass.

---

### Task 2: Signal And Execution Engine

**Files:**
- Create: `backend/src/hypertrade/paper/models.py`
- Create: `backend/src/hypertrade/paper/engine.py`
- Test: `tests/test_paper_engine.py`

- [ ] **Step 1: Write engine tests**

Add tests for:

```python
from decimal import Decimal

from hypertrade.paper.engine import PaperExecutionEngine, PaperSignalEngine
from hypertrade.paper.models import PaperTicker


def test_signal_engine_picks_positive_and_negative_movers():
    tickers = [
        PaperTicker("AAA-USDT-SWAP", Decimal("10"), Decimal("1000"), Decimal("4.2")),
        PaperTicker("BBB-USDT-SWAP", Decimal("20"), Decimal("900"), Decimal("-4.5")),
        PaperTicker("CCC-USDT-SWAP", Decimal("30"), Decimal("800"), Decimal("1.0")),
    ]

    signals = PaperSignalEngine().generate(tickers, max_signals=10)

    assert [(signal.inst_id, signal.side) for signal in signals] == [
        ("BBB-USDT-SWAP", "short"),
        ("AAA-USDT-SWAP", "long"),
    ]


def test_execution_engine_applies_fee_and_slippage():
    fill = PaperExecutionEngine(
        taker_fee_bps=Decimal("5"),
        slippage_bps=Decimal("2"),
    ).simulate_fill(
        inst_id="AAA-USDT-SWAP",
        side="long",
        target_notional=Decimal("1000"),
        last_price=Decimal("10"),
    )

    assert fill.price == Decimal("10.002")
    assert fill.quantity == Decimal("99.980003999200")
    assert fill.fee == Decimal("0.500000000000")
```

- [ ] **Step 2: Implement dataclasses**

Create `PaperTicker`, `PaperSignal`, and `SimulatedFill` dataclasses with `Decimal` fields and string `side` values `"long"`/`"short"`.

- [ ] **Step 3: Implement signal rules**

Rules:

- ignore tickers with `last <= 0` or `volume_ccy_24h <= 0`
- long when `change_utc0_pct >= 3`
- short when `change_utc0_pct <= -3`
- sort by absolute change descending, then volume descending
- cap at `max_signals`

- [ ] **Step 4: Implement fill math**

Rules:

- long fill price = `last_price * (1 + slippage_bps / 10000)`
- short fill price = `last_price * (1 - slippage_bps / 10000)`
- quantity = `target_notional / fill_price`
- fee = `target_notional * taker_fee_bps / 10000`
- quantize money values to `Decimal("0.000000000001")`

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/test_paper_engine.py -q
```

Expected: pass.

---

### Task 3: Paper Service Tick Loop

**Files:**
- Create: `backend/src/hypertrade/paper/repository.py`
- Modify: `backend/src/hypertrade/paper/service.py`
- Test: `tests/test_paper_service.py`

- [ ] **Step 1: Write service tick tests**

Add tests asserting:

- `run_once()` creates orders/fills/positions from seeded `MarketTicker` rows.
- `pause()` changes session status to `paused`.
- `run_once()` does not trade when paused.
- position count never exceeds configured `max_positions`.

- [ ] **Step 2: Implement repository**

Methods:

- `get_or_create_default_session(config_json)`
- `latest_tickers(limit)`
- `open_positions(session_id)`
- `create_order(...)`
- `create_fill(...)`
- `upsert_position_from_fill(...)`
- `record_event(session_id, kind, message, payload)`
- `status_snapshot(session_id)`
- `set_session_status(session_id, status)`

- [ ] **Step 3: Implement service**

`PaperTradingService.run_once()` flow:

1. Ensure default session.
2. Return skipped status if session is paused.
3. Load latest tickers.
4. Generate signals.
5. Skip symbols already open.
6. Size target notional as `min(equity * 0.20, equity * 5 / max_positions)`.
7. Simulate fills.
8. Persist orders, fills, positions, events.
9. Recalculate equity from cash, realized PnL, and open unrealized PnL.

- [ ] **Step 4: Run service tests**

Run:

```bash
uv run pytest tests/test_paper_service.py -q
```

Expected: pass.

---

### Task 4: API And Harness Overview

**Files:**
- Modify: `backend/src/hypertrade/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write API tests**

Add assertions:

```python
paper_status = client.get("/api/paper/status").json()
assert paper_status["session"]["status"] == "running"

pause = client.post("/api/paper/control", json={"action": "pause"}).json()
assert pause["session"]["status"] == "paused"

overview = client.get("/api/harness/overview").json()
assert overview["paper"]["session"]["status"] == "paused"
```

- [ ] **Step 2: Add payload model**

In `main.py`:

```python
class PaperControlPayload(BaseModel):
    action: Literal["pause", "resume"]
```

- [ ] **Step 3: Add endpoints**

Endpoints:

- `GET /api/paper/status`
- `POST /api/paper/control`

Both require admin auth.

- [ ] **Step 4: Extend overview**

Add:

```python
"paper": PaperTradingService(database, settings=app_settings).status()
```

- [ ] **Step 5: Run API tests**

Run:

```bash
uv run pytest tests/test_api.py -q
```

Expected: pass.

---

### Task 5: Worker Autorun

**Files:**
- Modify: `backend/src/hypertrade/worker.py`
- Test: `tests/test_paper_service.py`

- [ ] **Step 1: Add loop function**

In `worker.py`:

```python
async def paper_trading_loop(db: Database) -> None:
    settings = get_settings()
    service = PaperTradingService(db, settings=settings)
    while True:
        try:
            result = service.run_once()
            logger.info("paper_trading tick status=%s fills=%s", result.status, result.fill_count)
        except Exception:
            logger.exception("paper_trading failed")
        await asyncio.sleep(settings.paper_loop_interval_seconds)
```

- [ ] **Step 2: Add to gather only when enabled**

Build task list in `main()`:

```python
tasks = [
    rag_scanner_loop(db),
    market_ingestion_loop(db),
    market_rest_supplement_loop(db),
]
if settings.paper_enabled:
    tasks.append(paper_trading_loop(db))
await asyncio.gather(*tasks)
```

- [ ] **Step 3: Run backend tests**

Run:

```bash
uv run pytest tests/test_paper_service.py tests/test_api.py -q
```

Expected: pass.

---

### Task 6: Frontend Paper Runtime

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Extend frontend overview types**

Add `paper` to `HarnessOverview`:

```ts
paper: {
  session: {
    id: string;
    status: string;
    cash: string;
    equity: string;
    realized_pnl: string;
  };
  positions: Array<{
    inst_id: string;
    side: string;
    quantity: string;
    mark_price: string;
    unrealized_pnl: string;
  }>;
  recent_fills: Array<{
    inst_id: string;
    side: string;
    quantity: string;
    price: string;
    fee: string;
  }>;
};
```

- [ ] **Step 2: Add paper UI test fixture**

In `App.test.tsx`, add `paper` to the mocked overview and assert:

```ts
expect(await screen.findByText("Paper Runtime")).toBeInTheDocument();
expect(screen.getByText("running")).toBeInTheDocument();
expect(screen.getByText("AAA-USDT-SWAP")).toBeInTheDocument();
```

- [ ] **Step 3: Add pause/resume handler**

Add:

```ts
async function handlePaperControl(action: "pause" | "resume") {
  const response = await fetch("/api/paper/control", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action })
  });
  if (response.ok) {
    await refreshOverview();
  }
}
```

- [ ] **Step 4: Add UI section**

Add a `Paper Runtime` panel below market/run panels with:

- session status
- equity/cash/realized PnL
- pause/resume segmented buttons
- positions table
- recent fills table

- [ ] **Step 5: Run frontend tests**

Run:

```bash
npm exec --yes pnpm@10 -- -C frontend test
```

Expected: pass.

---

### Task 7: Verification, Docs, And Deploy

**Files:**
- Modify: `docs/progress.md`
- Optional Modify: `docs/architecture/08-paper-backtest-live-roadmap.md`

- [ ] **Step 1: Run full check**

Run:

```bash
./scripts/check.sh
```

Expected: all frontend/backend checks pass.

- [ ] **Step 2: Update docs**

Record:

- Sprint 02 implemented.
- Paper runtime enabled by default.
- Verification commands and results.
- Known limitations: deterministic rules, simulated fills only, no live orders.

- [ ] **Step 3: Commit**

Run:

```bash
git add backend frontend tests docs .env.example
git commit -m "feat: add automatic paper trading runtime"
```

- [ ] **Step 4: Push and deploy to server**

Run:

```bash
git push origin main
ssh root@47.79.36.92 'set -euo pipefail; cd /opt/hypertrade; git fetch origin main; git reset --hard origin/main; npm exec --yes pnpm@10 -- -C frontend install --frozen-lockfile; npm exec --yes pnpm@10 -- -C frontend build; ./deploy/deploy.sh; git rev-parse HEAD > deploy/last_deployed_sha'
```

- [ ] **Step 5: Server smoke**

Run:

```bash
curl -fsS http://47.79.36.92:3333/api/health
ssh root@47.79.36.92 'cd /opt/hypertrade && docker compose ps'
```

Then authenticate through Nginx and verify `/api/paper/status` returns running or paused state without exposing secrets.

---

## Self-Review

- Spec coverage: schema, engine, worker, API, frontend, tests, docs, and deploy are covered.
- Placeholder scan: no placeholder markers or unspecified implementation steps remain.
- Type consistency: plan uses `PaperSession`, `PaperPosition`, `PaperOrder`, `PaperFill`, `PaperEvent`, `PaperTradingService`, `PaperSignalEngine`, and `PaperExecutionEngine` consistently.
