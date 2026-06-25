from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.market.repository import MarketRepository
from hypertrade.providers.deepseek import ChatResponse, ToolCallRequest


def _world_model_service_class() -> type:
    try:
        from hypertrade.world_model.service import WorldModelService
    except ModuleNotFoundError as exc:  # pragma: no cover - RED phase helper
        raise AssertionError("WorldModelService module should exist") from exc
    return WorldModelService


class ReplayChatProvider:
    name = "replay"
    model = "world-model-test"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        if not self._responses:
            raise AssertionError("No replay response left")
        return self._responses.pop(0)


def _settings() -> Settings:
    return Settings(
        DEEPSEEK_API_KEY="test-key",
        OKX_REST_URL="http://127.0.0.1:9",
        BITPRO_MCP_API_TOKEN="bp-secret-token",
    )


def _seed_market(db: Database) -> None:
    repository = MarketRepository(db)
    repository.upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("2000000"),
        change_utc0_pct=Decimal("-1.5"),
    )
    repository.upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("3500"),
        volume_ccy_24h=Decimal("1200000"),
        change_utc0_pct=Decimal("0.8"),
    )


def test_world_model_snapshot_reports_global_state_and_missing_cross_asset_sources() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)

    snapshot = _world_model_service_class()(db, settings=_settings()).snapshot()

    assert snapshot["schema_version"] == "world_state.v1"
    assert snapshot["global_market"]["risk_regime"] in {
        "risk_on",
        "risk_off",
        "mixed",
        "stress",
        "unknown",
    }
    assert snapshot["global_market"]["cross_asset_signal"] == "unknown"
    assert "global_market.us_equities_unavailable" in snapshot["missing_data"]
    assert snapshot["crypto_market"]["ticker_count"] == 2
    assert snapshot["strategy"]["status"] in {"unknown", "healthy", "degraded", "failing"}
    assert snapshot["execution"]["status"] in {"healthy", "watch", "degraded", "critical"}
    assert snapshot["tool_health"]["status"] in {"healthy", "watch", "degraded", "critical"}
    assert snapshot["deployment"]["api_health"] == "ok"
    assert {action["action_id"] for action in snapshot["candidate_actions"]} >= {
        "observe_more",
        "run_monitor",
        "inspect_trace",
        "request_human_confirmation",
    }
    assert "action_scenarios" in snapshot
    assert "decision" in snapshot
    assert snapshot["decision"]["selected_action_id"]
    assert all(action["level"] in {"L0", "L1"} for action in snapshot["candidate_actions"])
    assert snapshot["source_refs"]
    assert "bp-secret-token" not in repr(snapshot)


def test_api_exposes_read_only_world_model_snapshot() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)
    client = TestClient(create_app(settings=_settings(), db=db))

    response = client.get("/api/world-model/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "world_state.v1"
    assert set(body) >= {
        "global_market",
        "crypto_market",
        "strategy",
        "execution",
        "tool_health",
        "deployment",
        "missing_data",
        "candidate_actions",
        "action_scenarios",
        "decision",
        "source_refs",
    }
    assert "global_market.us_equities_unavailable" in body["missing_data"]
    assert all(action["level"] in {"L0", "L1"} for action in body["candidate_actions"])


def test_agent_can_call_world_model_snapshot_without_write_tools(monkeypatch) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_market(db)
    provider = ReplayChatProvider(
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_world",
                        name="world_model_snapshot",
                        arguments={},
                    )
                ],
            ),
            ChatResponse(content="全局世界模型快照已生成。", tool_calls=[]),
        ]
    )
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: provider,
    )
    client = TestClient(create_app(settings=_settings(), db=db))

    response = client.post("/api/agent/runs", json={"prompt": "现在全局状态怎么样"})

    assert response.status_code == 200
    body = response.json()
    names = [event["tool_name"] for event in body["trace_events"]]
    assert "world_model_snapshot" in names
    assert not any(
        name
        in {
            "bitpro_paper_start",
            "bitpro_paper_pause",
            "bitpro_paper_stop",
            "live_order_intent",
        }
        for name in names
    )
    world_event = next(
        event
        for event in body["trace_events"]
        if event["tool_name"] == "world_model_snapshot"
    )
    assert world_event["output_json"]["status"] == "completed"
    assert "global_market.us_equities_unavailable" in world_event["output_json"]["missing_data"]
    assert world_event["output_json"]["decision"]["selected_action_id"]
    assert "全局世界模型" in body["report_markdown"]
    assert "场景决策" in body["report_markdown"]
