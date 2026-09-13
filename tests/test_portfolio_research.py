from copy import deepcopy
from decimal import Decimal

import pytest
from hypertrade.db import Database
from hypertrade.portfolio.research import PortfolioFreezeRequest, PortfolioResearchService
from strategy_evidence_fixtures import canonical_hash, return_series_payload


def series(sid="7", equities=("100", "110", "100")):
    p = return_series_payload()
    p["source_id"] = sid
    p["symbols"] = ["BTC/USDT:USDT" if sid == "7" else "ETH/USDT:USDT"]
    p["points"] = [
        {
            "timestamp": f"2026-01-01T0{i}:00:00+00:00",
            "equity": e,
            "gross_return": None,
            "net_return": str(Decimal(e) / Decimal(equities[0]) - 1),
        }
        for i, e in enumerate(equities)
    ]
    p["window"]["end_at"] = p["points"][-1]["timestamp"]
    p["as_of"] = p["points"][-1]["timestamp"]
    p["pagination"]["total_points"] = len(equities)
    p["source_hash"] = canonical_hash(
        {
            k: p[k]
            for k in (
                "source_layer",
                "source_id",
                "strategy_id",
                "strategy_version",
                "config_version",
                "timeframe",
                "currency",
                "cost_model",
                "points",
            )
        }
    )
    p["content_hash"] = canonical_hash(
        {k: v for k, v in p.items() if k not in {"content_hash", "freshness", "recorded_at"}}
    )
    return p


class Reader:
    def __init__(self):
        self.payloads = {"7": series(), "8": series("8", ("100", "100", "110"))}
        self.calls = []

    def strategy_return_series(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.payloads[kwargs["source_id"]])


def request(**overrides):
    return PortfolioFreezeRequest.model_validate(
        {
            "members": [
                {"source_layer": "backtest", "source_id": "7", "weight": "3", "direction": "long"},
                {"source_layer": "backtest", "source_id": "8", "weight": "1", "direction": "both"},
            ],
            "start_at": "2026-01-01T00:00:00Z",
            "end_at": "2026-01-01T02:00:00Z",
            "initial_capital": "100",
            "rebalance_at": ["2026-01-01T01:00:00Z"],
            "rebalance_fee_bps": "5",
            "rebalance_slippage_bps": "1",
            **overrides,
        }
    )


@pytest.fixture
def svc(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/portfolio.db")
    service = PortfolioResearchService(db, Reader())
    db.create_all()
    return service


def test_manifest_canonical_weights_timezone_order_and_immutable_ledger(svc):
    a = svc.freeze(request(), actor="test")
    b = svc.freeze(
        request(
            members=[
                {"source_layer": "backtest", "source_id": "8", "weight": "10", "direction": "both"},
                {"source_layer": "backtest", "source_id": "7", "weight": "30", "direction": "long"},
            ],
            start_at="2026-01-01T08:00:00+08:00",
        ),
        actor="other",
    )
    assert a == b
    assert [m["weight"] for m in a["manifest"]["members"]] == ["0.75", "0.25"]
    assert svc.get(a["id"])["manifest"] == a["manifest"]
    assert "points" not in repr(a)


def test_replay_net_contribution_and_explicit_cost_gap(svc):
    frozen = svc.freeze(request(), actor="test")
    result = svc.compare(frozen["id"], actor="test")
    assert result == svc.compare(frozen["id"], actor="test")
    assert result["status"] == "needs_data"
    assert result["recommendation"] == "collect_evidence"
    assert result["execution_authorized"] is False
    c = result["candidate"]
    assert c["fees"] is None and c["turnover"] is None
    assert Decimal(c["rebalance_turnover"]) > 75  # initial deployment + actual rebalance
    assert Decimal(c["rebalance_fees"]) > 0
    assert sum(Decimal(x["net_pnl"]) for x in c["contributions"]) - Decimal(
        c["rebalance_fees"]
    ) == pytest.approx(Decimal(c["ending_equity"]) - 100)
    assert len(c["equity_curve"]) == 3
    assert "equity_curve" not in repr(svc.get(result["id"]))
    assert result["baseline"]["policy"] == "equal_weight_buy_and_hold.v1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("strategy_version", "sha256:" + "c" * 64),
        ("config_version", "sha256:" + "d" * 64),
        ("symbols", ["SOL/USDT:USDT"]),
    ],
)
def test_drift_invalidates_old_manifest_without_overwriting(svc, field, value):
    frozen = svc.freeze(request(), actor="test")
    old = deepcopy(frozen)
    svc.reader.payloads["7"][field] = value
    result = svc.compare(frozen["id"], actor="test")
    assert result["status"] == "needs_data"
    assert result["candidate"] is None
    assert svc.get(frozen["id"]) == old


@pytest.mark.parametrize(
    "changes",
    [
        {"initial_capital": "NaN"},
        {"cash_weight": "-1"},
        {"rebalance_at": ["2026-01-01T00:30:00Z"]},
        {"start_at": "2026-01-01T00:00:00"},
        {"rebalance_at": ["2026-01-01T02:00:00Z"]},
        {"end_at": "2028-01-01T00:00:00Z"},
        {"members": [], "cash_weight": "0"},
        {"initial_capital": True},
    ],
)
def test_invalid_request(changes):
    with pytest.raises(ValueError):
        request(**changes)


def test_cash_only_is_complete_and_has_no_source_reads(svc):
    f = svc.freeze(request(members=[], cash_weight="1", rebalance_at=[]), actor="test")
    r = svc.compare(f["id"], actor="test")
    assert r["status"] == "available"
    assert r["candidate"]["ending_equity"] == "100"
    assert r["candidate"]["fees"] == "0"
    assert svc.reader.calls == []


def test_empty_missing_boundary_and_incompatible_costs_fail_closed(svc):
    svc.reader.payloads["7"]["points"] = []
    assert svc.freeze(request(), actor="test")["status"] == "needs_data"
    svc.reader.payloads["7"] = series(equities=("100", "100"))
    assert svc.freeze(request(), actor="test")["status"] == "needs_data"
    svc.reader.payloads["7"] = series()
    svc.reader.payloads["8"]["cost_model"]["fees"]["taker_fee_bps"] = 10
    assert svc.freeze(request(), actor="test")["status"] == "needs_data"


def test_recover_after_interrupted_read_and_concurrent_freeze(svc):
    from concurrent.futures import ThreadPoolExecutor

    original = svc.reader.strategy_return_series
    svc.reader.strategy_return_series = lambda **kw: (_ for _ in ()).throw(TimeoutError())
    assert svc.freeze(request(), actor="test")["status"] == "needs_data"
    svc.reader.strategy_return_series = original
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: svc.freeze(request(), actor="test"), range(4)))
    assert len({x["id"] for x in results}) == 1
    recovered = PortfolioResearchService(svc.db, svc.reader)
    assert recovered.compare(results[0]["id"], actor="test") == svc.compare(
        results[0]["id"], actor="test"
    )


def test_admin_api_freeze_compare_and_record(svc):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.testclient import TestClient
    from hypertrade.portfolio.research_api import build_portfolio_research_router

    def auth(req: Request):
        if req.headers.get("Authorization") != "test-admin":
            raise HTTPException(401)
        return "test"

    app = FastAPI()
    app.include_router(build_portfolio_research_router(svc, auth))
    with TestClient(app) as client:
        data = request().model_dump(mode="json")
        assert client.post("/api/portfolio/research/freeze", json=data).status_code == 401
        headers = {"Authorization": "test-admin"}
        frozen = client.post("/api/portfolio/research/freeze", json=data, headers=headers).json()
        compared = client.post("/api/portfolio/research/compare/" + frozen["id"], headers=headers)
        assert compared.status_code == 200
        assert compared.json()["status"] == "needs_data"
        result = client.get(
            "/api/portfolio/research/records/" + compared.json()["id"], headers=headers
        )
        assert result.status_code == 200
        assert "equity_curve" not in repr(result.json())
        assert (
            client.get("/api/portfolio/research/records/missing", headers=headers).status_code
            == 404
        )


def test_rebalance_has_no_lookahead_and_is_self_financing(svc):
    f = svc.freeze(request(rebalance_fee_bps="0", rebalance_slippage_bps="0"), actor="test")
    r = svc.compare(f["id"], actor="test")["candidate"]
    assert Decimal(r["ending_equity"]) == pytest.approx(Decimal("102.8579545454545454545"))
    assert Decimal(r["equity_curve"][1]["equity"]) == pytest.approx(Decimal("107.5"))
    assert Decimal(r["rebalance_fees"]) == 0


def test_decimal_context_does_not_change_replay(svc):
    from decimal import localcontext

    f = svc.freeze(request(), actor="test")
    r = svc.compare(f["id"], actor="test")
    with localcontext() as ctx:
        ctx.prec = 12
        assert svc.compare(f["id"], actor="test") == r


def rehash_series(p):
    p["source_hash"] = canonical_hash(
        {
            k: p[k]
            for k in (
                "source_layer",
                "source_id",
                "strategy_id",
                "strategy_version",
                "config_version",
                "timeframe",
                "currency",
                "cost_model",
                "points",
            )
        }
    )
    p["content_hash"] = canonical_hash(
        {k: v for k, v in p.items() if k not in {"content_hash", "freshness", "recorded_at"}}
    )


def test_validly_hashed_version_and_output_drift_are_rejected(svc):
    f = svc.freeze(request(), actor="test")
    svc.reader.payloads["7"]["strategy_version"] = "sha256:" + "c" * 64
    rehash_series(svc.reader.payloads["7"])
    assert svc.compare(f["id"], actor="test")["data_gaps"] == ["member_version_or_output_drift"]
    svc.reader.payloads["7"] = series(equities=("100", "120", "100"))
    assert svc.compare(f["id"], actor="test")["data_gaps"] == ["member_version_or_output_drift"]


def test_validly_hashed_cost_mismatch_is_not_compared(svc):
    svc.reader.payloads["8"]["cost_model"]["fees"]["taker_fee_bps"] = 10
    rehash_series(svc.reader.payloads["8"])
    assert svc.freeze(request(), actor="test")["data_gaps"] == ["incompatible_member_costs"]


def test_direction_is_metadata_never_inverts_strategy_pnl(svc):
    a = svc.freeze(
        request(
            members=[
                {"source_layer": "backtest", "source_id": "8", "weight": "1", "direction": "short"}
            ]
        ),
        actor="test",
    )
    r = svc.compare(a["id"], actor="test")
    assert Decimal(r["candidate"]["net_return"]) > 0


def test_concurrent_compare_and_summary_integrity(svc):
    from concurrent.futures import ThreadPoolExecutor

    from hypertrade.portfolio.research import PortfolioResearchRecord

    f = svc.freeze(request(), actor="test")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: svc.compare(f["id"], actor="test"), range(4)))
    assert len({x["id"] for x in results}) == 1
    with svc.db.session() as session:
        row = session.get(PortfolioResearchRecord, f["id"])
        row.payload = {**row.payload, "status": "changed"}
    with pytest.raises(ValueError, match="integrity"):
        svc.get(f["id"])


def test_reallocation_costs_reconcile_without_leverage():
    from decimal import localcontext

    from hypertrade.portfolio.research import rebalance

    with localcontext() as ctx:
        ctx.prec = 60
        holdings, cash, turnover, fee = rebalance(
            [Decimal(0), Decimal(0)], Decimal(100), [Decimal(".75"), Decimal(".25")], Decimal(".01")
        )
        assert sum(holdings, cash) + fee == pytest.approx(Decimal(100))
        assert fee == turnover * Decimal(".01")
        assert abs(cash) < Decimal("1e-40")
        assert fee == pytest.approx(Decimal(100) / 101)


def test_main_mount_is_authenticated_without_touching_bitpro(monkeypatch):
    import hypertrade.main as main
    from fastapi.testclient import TestClient
    from hypertrade.config import Settings

    closed = []

    class HttpClient:
        def close(self):
            closed.append(True)

    class ReadClient:
        def __init__(self, **_kwargs):
            self.http_client = HttpClient()

        def call_tool(self, *_args, **_kwargs):
            raise AssertionError("unauthenticated request must not read BitPro")

    monkeypatch.setattr(main, "PacedReadClient", ReadClient)

    settings = Settings(DATABASE_URL="sqlite:///:memory:")
    app = main.create_app(settings=settings, db=Database("sqlite:///:memory:"))
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/portfolio/research/freeze", json=request().model_dump(mode="json")
            ).status_code
            == 401
        )
    assert closed == [True]


def test_frozen_baseline_and_zero_weight_denominator(svc):
    f = svc.freeze(request(), actor="test")
    assert f["manifest"]["baseline"]["weights"] == ["0.5", "0.5"]
    assert f["manifest"]["baseline"]["rebalance_at"] == []
    f2 = svc.freeze(
        request(
            members=[
                {"source_layer": "backtest", "source_id": "7", "weight": "0", "direction": "both"}
            ],
            cash_weight="1",
        ),
        actor="test",
    )
    assert len(f2["manifest"]["members"]) == 1
    r = svc.compare(f2["id"], actor="test")
    assert r["status"] == "needs_data"
    assert Decimal(r["candidate"]["ending_equity"]) == 100


@pytest.mark.parametrize("value", ["1e99999", "0.000000000000000000001"])
def test_amount_bounds(value):
    with pytest.raises(ValueError):
        request(initial_capital=value)


@pytest.mark.parametrize("bad", [-1, True, "NaN"])
def test_invalid_source_costs_are_never_frozen(svc, bad):
    for page in svc.reader.payloads.values():
        page["cost_model"]["fees"]["maker_fee_bps"] = bad
        rehash_series(page)
    assert svc.freeze(request(), actor="test")["status"] == "needs_data"


def test_asset_contributions_sum_to_member_contributions(svc):
    f = svc.freeze(request(), actor="test")
    c = svc.compare(f["id"], actor="test")["candidate"]
    assert sum(Decimal(x["net_pnl"]) for x in c["asset_contributions"]) == sum(
        Decimal(x["net_pnl"]) for x in c["contributions"]
    )


def test_backtest_observed_identity_is_not_original_run_proof(svc):
    f = svc.freeze(request(), actor="test")
    assert f["manifest"]["identity_semantics"] == "observed_source_identity"
    r = svc.compare(f["id"], actor="test")
    assert "member_run_provenance_unverified" in r["data_gaps"]
