from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.market.okx import parse_okx_candle
from hypertrade.memory.service import MemoryService
from hypertrade.strategy.evidence import (
    STRATEGY_EVIDENCE_SCHEMA_VERSION,
    StrategyEvidence,
    parse_strategy_evidence,
)


def _seed_strategy_evidence_memory(
    db: Database,
    *,
    experiment_id: str,
    memory_return: str,
    passed: bool,
    failure_reasons: list[str] | None = None,
) -> str:
    evidence = StrategyEvidence(
        strategy_key="momentum_breakout_v1",
        experiment_id=experiment_id,
        research_id=f"srch_{experiment_id}",
        backtest_id=f"bt_{experiment_id}",
        variant_id="fast" if passed else "baseline",
        variant_count=3,
        parameters={"sma_period": "3", "breakout_pct": "0.0"},
        metrics={
            "total_return_pct": memory_return,
            "max_drawdown_pct": "0.0" if passed else "6.5",
            "trade_count": "10" if passed else "4",
            "score": memory_return,
        },
        gate_results={
            "min_trade_count": True,
            "max_drawdown_pct": True,
            "require_non_negative_return": passed,
        },
        failure_reasons=failure_reasons or [],
        source_data={
            "source": "sample_candles",
            "inst_id": "ETH-USDT-SWAP",
            "bar": "1H",
            "candle_count": "100",
        },
        next_experiment="Reduce breakout_pct before retesting.",
        boundaries=["research_only", "no_bitpro_write", "no_live_or_testnet_order"],
        passed=passed,
    )
    item = MemoryService(db).write(
        content=evidence.to_memory_content(),
        kind="strategy_knowledge",
        source_run_id=experiment_id,
        source_tool="strategy.experiment",
        tags=[
            "strategy",
            "strategy_knowledge",
            "strategy_experiment",
            "evidence",
            "momentum_breakout_v1",
        ],
        importance=Decimal("0.82") if passed else Decimal("0.68"),
        confidence=Decimal("0.74"),
    )
    return item.id


def test_strategy_research_and_backtest_api(tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    research = client.post(
        "/api/strategy/research",
        json={"prompt": "研究一个趋势突破策略"},
    ).json()

    assert research["strategy_key"] == "momentum_breakout_v1"
    assert "趋势" in research["report_markdown"]

    backtest = client.post(
        "/api/backtests",
        json={"research_id": research["id"]},
    ).json()

    assert backtest["status"] == "completed"
    assert backtest["strategy_key"] == "momentum_breakout_v1"
    assert backtest["metrics"]["trade_count"] >= 1

    overview = client.get("/api/harness/overview").json()
    assert overview["strategy_lab"]["latest_research"]["id"] == research["id"]
    assert overview["strategy_lab"]["latest_backtest"]["id"] == backtest["id"]


def test_strategy_experiment_workflow_api(tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    experiment = client.post(
        "/api/strategy/experiments",
        json={"prompt": "研究ETH趋势突破，给出回测和改进建议"},
    ).json()
    experiments = client.get("/api/strategy/experiments").json()["items"]
    overview = client.get("/api/harness/overview").json()

    assert experiment["id"].startswith("exp_")
    assert experiment["status"] == "completed"
    assert experiment["research_id"].startswith("srch_")
    assert experiment["backtest_id"].startswith("bt_")
    assert "critique" in experiment["report_json"]
    variants = experiment["report_json"]["variants"]
    winner = experiment["report_json"]["winner"]
    gates = experiment["report_json"]["evidence_gates"]
    assert len(variants) >= 3
    assert all(item["backtest_id"].startswith("bt_") for item in variants)
    assert all(item["metrics"]["trade_count"] >= 0 for item in variants)
    assert {item["variant_id"] for item in variants} >= {
        "baseline",
        "fast",
        "conservative",
    }
    assert winner["variant_id"] in {item["variant_id"] for item in variants}
    assert winner["backtest_id"] == experiment["backtest_id"]
    assert gates == {
        "min_trade_count": 1,
        "max_drawdown_pct": "20",
        "require_non_negative_return": True,
    }
    assert "## 候选版本对比" in experiment["report_markdown"]
    assert "## 胜出版本" in experiment["report_markdown"]
    assert "不构成投资建议" in experiment["report_markdown"]
    backtests = client.get("/api/backtests").json()["items"]
    assert len(backtests) >= 3
    assert experiments[0]["id"] == experiment["id"]
    assert overview["strategy_lab"]["latest_experiment"]["id"] == experiment["id"]

    knowledge_items = client.get(
        "/api/memory",
        params={"kind": "strategy_knowledge", "tag": "strategy"},
    ).json()["items"]
    assert len(knowledge_items) == 1
    knowledge = knowledge_items[0]
    assert knowledge["source_run_id"] == experiment["id"]
    assert knowledge["source_tool"] == "strategy.experiment"
    evidence = parse_strategy_evidence(knowledge["content"])
    assert evidence is not None
    assert evidence.schema_version == STRATEGY_EVIDENCE_SCHEMA_VERSION
    assert evidence.strategy_key == "momentum_breakout_v1"
    assert evidence.experiment_id == experiment["id"]
    assert evidence.research_id == experiment["research_id"]
    assert evidence.backtest_id == winner["backtest_id"]
    assert evidence.variant_id == winner["variant_id"]
    assert evidence.variant_count == 3
    assert evidence.metrics["total_return_pct"] == str(winner["metrics"]["total_return_pct"])
    assert evidence.metrics["max_drawdown_pct"] == str(winner["metrics"]["max_drawdown_pct"])
    assert evidence.gate_results == winner["gate_results"]
    assert evidence.source_data["source"] == "sample_candles"
    assert evidence.boundaries == [
        "research_only",
        "no_bitpro_write",
        "no_live_or_testnet_order",
    ]
    assert {
        "strategy",
        "strategy_knowledge",
        "strategy_experiment",
        "evidence",
        "momentum_breakout_v1",
        f"winner:{winner['variant_id']}",
    } <= set(knowledge["tags"])
    hits = client.get(
        "/api/memory",
        params={"kind": "strategy_knowledge", "query": winner["variant_id"]},
    ).json()["items"]
    assert hits[0]["id"] == knowledge["id"]

    library = client.get("/api/strategy/library", params={"query": winner["variant_id"]}).json()
    assert library["source"] == "memory.strategy_knowledge"
    assert library["memory_count"] == 1
    assert library["items"][0]["strategy_key"] == "momentum_breakout_v1"
    assert library["items"][0]["evidence_count"] == 1
    assert library["items"][0]["best"]["backtest_id"] == winner["backtest_id"]
    assert library["items"][0]["best"]["variant_id"] == winner["variant_id"]
    assert library["items"][0]["best"]["schema_version"] == STRATEGY_EVIDENCE_SCHEMA_VERSION
    assert library["items"][0]["source_memory_ids"] == [knowledge["id"]]


def test_strategy_iteration_workflow_uses_prior_evidence_and_refuses_worse_claim(
    tmp_path,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    failed_memory_id = _seed_strategy_evidence_memory(
        db,
        experiment_id="exp_failed_prior",
        memory_return="-4.2",
        passed=False,
        failure_reasons=["require_non_negative_return"],
    )
    best_memory_id = _seed_strategy_evidence_memory(
        db,
        experiment_id="exp_best_prior",
        memory_return="99.0",
        passed=True,
    )
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)

    response = client.post(
        "/api/strategy/experiments/iterate",
        json={"prompt": "继续优化 momentum_breakout_v1"},
    )

    assert response.status_code == 200
    experiment = response.json()
    report_json = experiment["report_json"]
    prior = report_json["prior_evidence"]
    assert set(prior["source_memory_ids"]) == {failed_memory_id, best_memory_id}
    assert prior["best"]["memory_id"] == best_memory_id
    assert report_json["variant_plan"]["mode"] == "evidence_driven"
    assert all(item["reason"] for item in report_json["variant_plan"]["variants"])
    assert any(
        best_memory_id == item["source_memory_id"]
        for item in report_json["variant_plan"]["variants"]
    )
    comparison = report_json["result_comparison"]
    assert comparison["claim"] == "not_improved"
    assert comparison["can_claim_improvement"] is False
    assert comparison["prior_best"]["memory_id"] == best_memory_id
    assert "## Prior Evidence" in experiment["report_markdown"]
    assert best_memory_id in experiment["report_markdown"]
    assert "未声称改进" in experiment["report_markdown"]

    new_memory = client.get(
        "/api/memory",
        params={"kind": "strategy_knowledge", "query": experiment["id"]},
    ).json()["items"][0]
    assert new_memory["source_run_id"] == experiment["id"]
    library = client.get(
        "/api/strategy/library",
        params={"strategy_key": "momentum_breakout_v1"},
    ).json()
    item = library["items"][0]
    assert item["evidence_count"] == 3
    assert new_memory["id"] in item["source_memory_ids"]


def test_backtest_api_accepts_live_okx_candle_options(monkeypatch, tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    captured: dict[str, object] = {}

    def fake_fetch(self, inst_id: str, bar: str, limit: int):
        captured.update({"inst_id": inst_id, "bar": bar, "limit": limit})
        return [
            parse_okx_candle(
                [
                    str(1764200000000 + index * 3600000),
                    str(100 + index),
                    str(101 + index),
                    str(99 + index),
                    str(100 + index),
                    "1000",
                    "1000",
                    "100000",
                    "1",
                ]
            )
            for index in range(24)
        ]

    monkeypatch.setattr(
        "hypertrade.backtest.service.BacktestService._fetch_okx_candles",
        fake_fetch,
    )

    response = client.post(
        "/api/backtests",
        json={
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": True,
            "symbol": "ETH",
            "bar": "1H",
            "candle_limit": 24,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert captured == {"inst_id": "ETH-USDT-SWAP", "bar": "1H", "limit": 24}
    assert body["report_json"]["data_source"] == "okx_rest_candles"
