from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.agent.kernel import AgentKernel
from hypertrade.bitpro.mcp import BitProMcpError
from hypertrade.config import Settings
from hypertrade.db import AgentRun, Database
from hypertrade.main import create_app
from hypertrade.market.repository import MarketRepository
from hypertrade.providers.deepseek import ChatResponse, ToolCallRequest


class ReplayChatProvider:
    name = "replay"
    model = "api-test"

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


def _patch_replay_provider(
    monkeypatch,
    responses: list[ChatResponse],
) -> None:
    provider = ReplayChatProvider(responses)
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: provider,
    )


def _market_summary_replay(*, with_rag_memory: bool = False) -> list[ChatResponse]:
    tool_calls = [
        ToolCallRequest(
            id="call_market",
            name="market_summary",
            arguments={},
        )
    ]
    if with_rag_memory:
        tool_calls.extend(
            [
                ToolCallRequest(
                    id="call_rag",
                    name="rag_search",
                    arguments={"query": "market risk", "limit": 3},
                ),
                ToolCallRequest(
                    id="call_memory",
                    name="memory_write",
                    arguments={
                        "kind": "market_summary",
                        "content": "Latest market summary requested by user prompt.",
                    },
                ),
            ]
        )
    return [
        ChatResponse(content="", tool_calls=tool_calls),
        ChatResponse(content="已完成行情归纳。", tool_calls=[]),
    ]


def test_api_exposes_health_harness_and_agent_run(monkeypatch, tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("20000"),
        change_utc0_pct=Decimal("4.2"),
    )
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "risk.md").write_text(
        "Risk control comes before signal strength.",
        encoding="utf-8",
    )
    _patch_replay_provider(monkeypatch, _market_summary_replay(with_rag_memory=True))

    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="test-key",
            OKX_REST_URL="http://127.0.0.1:9",
            BITPRO_MCP_API_TOKEN="api-secret-token",
        ),
        db=db,
    )
    client = TestClient(app)

    assert client.get("/api/health").json()["status"] == "ok"
    login_response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert login_response.status_code == 200
    assert "secure" not in login_response.headers["set-cookie"].lower()
    tools = client.get("/api/harness/tools").json()["tools"]
    assert tools[-1]["requires_approval"] is True
    market_summary = next(tool for tool in tools if tool["name"] == "market.summary")
    assert market_summary["policy"] == {
        "scope": "read",
        "approval": "none",
        "idempotency": "not_required",
        "source_of_truth": "okx_rest",
        "timeout_class": "standard",
        "safe_sample_limit": 10,
        "failure_behavior": "return_unavailable",
    }
    assert client.get("/api/harness/providers").json()["providers"][0]["name"] == "deepseek"

    response = client.post("/api/agent/runs", json={"prompt": "请做行情归纳"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert (
        "BTC-USDT-SWAP" in body["report_markdown"]
        or "当前无法获取实时 OKX 行情" in body["report_markdown"]
    )
    if "当前无法获取实时 OKX 行情" in body["report_markdown"]:
        assert body["report_json"]["data_source"] == "unavailable"
    trace_names = [event["tool_name"] for event in body["trace_events"]]
    assert trace_names[0] == "graph.intent_classify"
    assert "graph.plan_tools" in trace_names
    assert "graph.reflect" in trace_names
    assert "graph.final_report" in trace_names
    assert "market_summary" in trace_names
    assert body["run_state_json"]["current_node"] == "final_report"

    overview = client.get("/api/harness/overview").json()

    assert overview["market"]["ticker_count"] == 1
    assert overview["market"]["top_movers"][0]["inst_id"] == "BTC-USDT-SWAP"
    assert overview["agent_runs"]["total_count"] == 1
    assert overview["rag"]["document_count"] == 1
    assert overview["memory"]["active_count"] == 1
    assert overview["trace"]["total_count"] >= 9
    assert overview["providers"][0]["name"] == "deepseek"
    assert overview["tools"][-1]["requires_approval"] is True
    live_intent = next(tool for tool in overview["tools"] if tool["name"] == "live.order_intent")
    assert live_intent["policy"]["scope"] == "testnet_write"
    assert live_intent["policy"]["approval"] == "required"
    assert live_intent["policy"]["idempotency"] == "required"
    bitpro_tool = next(tool for tool in overview["tools"] if tool["name"] == "bitpro.market_klines")
    assert bitpro_tool["connector_origin"] == {
        "connector_id": "bitpro",
        "tool": "market_klines",
    }
    assert overview["connectors"]["bitpro"]["auth"]["configured"] is True
    assert "api-secret-token" not in repr(overview["connectors"])
    assert overview["paper"]["session"]["status"] == "running"

    connectors = client.get("/api/connectors/capabilities").json()
    assert connectors["connectors"]["bitpro"]["display_name"] == "BitPro MCP"
    assert connectors["connectors"]["bitpro"]["auth"]["secret_redacted"] is True
    assert "api-secret-token" not in repr(connectors)

    rag_hits = client.get("/api/rag/search?query=risk").json()["hits"]
    assert rag_hits[0]["title"] == "risk"
    assert "api_key" not in rag_hits[0]
    memory_hits = client.get("/api/memory?query=market").json()["items"]
    assert memory_hits[0]["tags"]
    assert memory_hits[0]["usage_count"] >= 1

    paper_status = client.get("/api/paper/status").json()
    assert paper_status["session"]["status"] == "running"

    evals = client.get("/api/evals/status").json()
    assert evals["status"] == "passed"
    expected_eval_cases = {
        "tool_selection",
        "rag_citation",
        "memory_behavior",
        "risk_refusal",
        "testnet_order_safety",
        "strategy_library_history_source",
        "bitpro_backtest_page_parity",
        "missing_artifact_disclosure",
        "paper_monitor_read_only",
        "compact_report_rendering",
        "live_order_history_source",
        "live_strategy_performance_source",
    }
    assert expected_eval_cases == {
        case["name"] for case in evals["cases"]
    }

    pause = client.post("/api/paper/control", json={"action": "pause"}).json()
    assert pause["session"]["status"] == "paused"
    reset = client.post("/api/paper/control", json={"action": "reset"}).json()
    assert reset["session"]["status"] == "running"
    close = client.post("/api/paper/control", json={"action": "close", "symbol": "BTC"}).json()
    assert close["closed_count"] == 0

    intent = client.post(
        "/api/live/order-intents",
        json={"symbol": "ETH", "side": "buy", "size": "0.01", "reason": "api smoke"},
    ).json()
    assert intent["status"] == "pending_approval"
    assert intent["inst_id"] == "ETH-USDT-SWAP"
    assert client.get("/api/live/order-intents").json()["items"][0]["id"] == intent["id"]
    approved = client.post(
        f"/api/live/order-intents/{intent['id']}/approve",
        json={"reason": "checked"},
    ).json()
    assert approved["status"] == "approved"
    duplicate_approval = client.post(
        f"/api/live/order-intents/{intent['id']}/approve",
        json={"reason": "again"},
    )
    assert duplicate_approval.status_code == 400
    executed = client.post(f"/api/live/order-intents/{intent['id']}/execute").json()
    assert executed["status"] == "execution_failed"
    assert executed["risk_status"] == "allowed"
    assert executed["execution"]["request"]["api_key"] == ""

    paused_overview = client.get("/api/harness/overview").json()
    assert paused_overview["paper"]["session"]["status"] == "running"
    assert paused_overview["live_orders"]["total_count"] == 1


def test_api_market_heat_prompt_returns_summary(monkeypatch, tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    repository = MarketRepository(db)
    repository.upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("62479.1"),
        volume_ccy_24h=Decimal("109556.77"),
        change_utc0_pct=Decimal("-2.367"),
    )
    repository.upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("1659.6"),
        volume_ccy_24h=Decimal("4852653.03"),
        change_utc0_pct=Decimal("-3.924"),
    )
    repository.upsert_ticker_snapshot(
        inst_id="SOL-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("68.9"),
        volume_ccy_24h=Decimal("12600982.08"),
        change_utc0_pct=Decimal("-4.172"),
    )
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    _patch_replay_provider(monkeypatch, _market_summary_replay())
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="test-key",
            OKX_REST_URL="http://127.0.0.1:9",
        ),
        db=db,
    )
    client = TestClient(app)

    response = client.post("/api/agent/runs", json={"prompt": "看下目前市场的热度怎么样"})

    assert response.status_code == 200
    body = response.json()
    assert "市场热度总结" in body["report_markdown"]
    assert "结论:" in body["report_markdown"]
    assert "样本:" in body["report_markdown"]
    assert body["report_json"]["heat_summary"]["sample_count"] == 3
    assert body["report_json"]["heat_summary"]["decliners_count"] == 3


def test_public_workbench_can_read_observability_without_login(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("20000"),
        change_utc0_pct=Decimal("4.2"),
    )
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "risk.md").write_text(
        "Risk control comes before signal strength.",
        encoding="utf-8",
    )
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="",
            OKX_REST_URL="http://127.0.0.1:9",
        ),
        db=db,
    )
    client = TestClient(app)

    run_response = client.post("/api/agent/runs", json={"prompt": "请做行情归纳"})

    assert run_response.status_code == 200
    run_id = run_response.json()["id"]
    overview = client.get("/api/harness/overview")
    assert overview.status_code == 200
    overview_body = overview.json()
    assert overview_body["agent_runs"]["total_count"] == 1
    assert overview_body["trace"]["total_count"] >= 1
    assert overview_body["agent_runs"]["recent"][0]["id"] == run_id

    runs = client.get("/api/agent/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["id"] == run_id

    run_detail = client.get(f"/api/agent/runs/{run_id}")
    assert run_detail.status_code == 200
    assert run_detail.json()["trace_events"]

    assert client.get("/api/memory").status_code == 200
    assert client.get("/api/rag/search?query=risk").status_code == 200
    assert client.post(
        "/api/harness/provider-selection",
        json={"provider": "deepseek"},
    ).status_code == 401
    assert client.post("/api/paper/control", json={"action": "pause"}).status_code == 401


def test_api_streams_agent_run_events(monkeypatch, tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    _patch_replay_provider(monkeypatch, _market_summary_replay())
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="test-key",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    with client.stream(
        "POST",
        "/api/agent/runs/stream",
        json={"prompt": "请做行情归纳"},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run_started" in body
    assert "event: tool_started" in body
    assert "event: tool_completed" in body
    assert "event: run_completed" in body


def test_api_can_cancel_running_agent_run(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        run = AgentRun(prompt="long running prompt", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    canceled = client.post(f"/api/agent/runs/{run_id}/cancel")

    assert canceled.status_code == 200
    body = canceled.json()
    assert body["status"] == "canceled"
    assert body["report_json"]["error"] == {
        "type": "run_canceled",
        "message": "canceled_by_operator",
        "retryable": False,
    }
    detail = client.get(f"/api/agent/runs/{run_id}").json()
    assert detail["status"] == "canceled"
    assert detail["report_markdown"] == "Agent run canceled: canceled_by_operator"


def test_api_can_switch_active_provider_without_exposing_keys(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="",
            OPENROUTER_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    switched = client.post(
        "/api/harness/provider-selection",
        json={"provider": "openrouter"},
    )

    assert switched.status_code == 200
    body = switched.json()
    assert body["default_provider"] == "openrouter"
    assert all("api_key" not in provider for provider in body["providers"])
    selected = next(provider for provider in body["providers"] if provider["name"] == "openrouter")
    assert selected["default"] is True
    assert selected["key_status"] == "missing"
    run = client.post("/api/agent/runs", json={"prompt": "请做行情归纳"}).json()
    assert run["status"] == "completed"
    assert run["report_json"]["status"] == "provider_unavailable"
    assert run["report_json"]["tool_calls"] == []


def test_api_can_select_codex_provider_model_without_exposing_keys(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="",
            CODEX_API_KEY="codex-secret-token",
            CODEX_MODEL="gpt-5.4",
            CODEX_MODEL_OPTIONS="gpt-5.4,gpt-5.4-mini",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    switched = client.post(
        "/api/harness/provider-selection",
        json={"provider": "codex", "model": "gpt-5.4-mini"},
    )

    assert switched.status_code == 200
    body = switched.json()
    assert body["default_provider"] == "codex"
    assert body["model"] == "gpt-5.4-mini"
    assert "codex-secret-token" not in str(body)
    selected = next(provider for provider in body["providers"] if provider["name"] == "codex")
    assert selected["model"] == "gpt-5.4-mini"
    assert selected["model_options"] == ["gpt-5.4", "gpt-5.4-mini"]

    overview = client.get("/api/harness/overview").json()
    overview_selected = next(
        provider for provider in overview["providers"] if provider["name"] == "codex"
    )
    assert overview_selected["model"] == "gpt-5.4-mini"

    invalid = client.post(
        "/api/harness/provider-selection",
        json={"provider": "codex", "model": "not-a-codex-model"},
    )

    assert invalid.status_code == 400


def test_api_exposes_deterministic_market_shortcuts(monkeypatch, tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("3500"),
        volume_ccy_24h=Decimal("987654"),
        change_utc0_pct=Decimal("1.23"),
    )
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    monkeypatch.setattr(
        AgentKernel,
        "_market_candles_payload",
        lambda self, *, symbol, bar, limit: {
            "found": True,
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "bar": bar,
            "candle_count": limit,
            "return_pct": "2.400000",
            "data_source": "okx_rest",
        },
    )
    monkeypatch.setattr(
        AgentKernel,
        "_market_compare_payload",
        lambda self, *, symbols, bar, limit: {
            "found": True,
            "symbols": symbols,
            "bar": bar,
            "limit": limit,
            "leader": "ETH-USDT-SWAP",
            "rankings": [{"rank": 1, "inst_id": "ETH-USDT-SWAP"}],
            "data_source": "okx_rest",
        },
    )

    ticker = client.get("/api/market/ticker/ETH").json()
    candles = client.get("/api/market/candles/ETH?bar=1H&limit=50").json()
    compare = client.post(
        "/api/market/compare",
        json={"symbols": ["ETH", "SOL"], "bar": "4H", "limit": 100},
    ).json()

    assert ticker["inst_id"] == "ETH-USDT-SWAP"
    assert ticker["found"] is True
    assert candles == {
        "found": True,
        "inst_id": "ETH-USDT-SWAP",
        "bar": "1H",
        "candle_count": 50,
        "return_pct": "2.400000",
        "data_source": "okx_rest",
    }
    assert compare["leader"] == "ETH-USDT-SWAP"
    assert compare["symbols"] == ["ETH", "SOL"]


def test_api_exposes_bitpro_mcp_read_adapter(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
        bitpro_adapter=ApiFakeBitProAdapter(),
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    overview = client.get("/api/harness/overview").json()
    assert overview["bitpro"]["adapter"] == "mcp_non_live_lifecycle"
    assert overview["bitpro"]["configured"] is True
    assert overview["bitpro"]["live_write_enabled"] is False
    assert overview["bitpro"]["live_write_scope"] == "hypertrade_mcp_live_write_gate"
    assert "not BitPro runtime mode" in overview["bitpro"]["live_write_note"]
    assert "write/order tools" in overview["bitpro"]["live_write_note"]
    assert "strategy_create" in overview["bitpro"]["tools"]
    assert "strategy_update" in overview["bitpro"]["tools"]
    assert "paper_start" in overview["bitpro"]["tools"]
    assert overview["bitpro"]["token_source"] == "bitpro_settings_agent_token_or_server_env"
    assert overview["bitpro"]["remote_mcp"]["path_default"] == "/api/v2/mcp/"
    assert overview["bitpro"]["agent_auth"]["auth_header_default"] == "X-BitPro-MCP-Token"
    assert overview["bitpro"]["agent_auth"]["token_management"]["settings_routes"] == {
        "list": "GET /api/v2/settings/mcp-agent-tokens",
        "create": "POST /api/v2/settings/mcp-agent-tokens",
        "revoke": "DELETE /api/v2/settings/mcp-agent-tokens/{token_id}",
    }
    assert overview["bitpro"]["agent_auth"]["scope_classes"]["L"]["tool_group"] == "live_diagnostic"
    assert "backtest_start_job" in overview["bitpro"]["agent_auth"]["idempotency"]["required_tools"]
    assert "live_diagnostic" in overview["bitpro"]["tool_groups"]

    health = client.get("/api/bitpro/health").json()
    klines = client.get("/api/bitpro/market/klines/ETH?timeframe=1H&limit=12").json()
    paper = client.get("/api/bitpro/paper/dashboard").json()
    positions = client.get("/api/bitpro/live/positions?symbol=ETH").json()

    assert health["tool_calls"][0]["tool"] == "bitpro_capabilities"
    assert klines["market"]["symbol"] == "ETH/USDT:USDT"
    assert klines["market"]["timeframe"] == "1h"
    assert len(klines["candles"]) == 12
    assert paper["dashboard"]["session_count"] == 1
    assert positions["positions"][0]["symbol"] == "ETH/USDT:USDT"


def test_api_returns_structured_bitpro_gateway_errors(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
        bitpro_adapter=FailingBitProAdapter(),
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    response = client.get("/api/bitpro/health")

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "status": "unavailable",
        "service": "bitpro_mcp",
        "message": "BitPro MCP unavailable",
        "status_code": None,
        "tool_calls": [{"tool": "bitpro_health", "status": "failed"}],
    }


def test_login_cookie_secure_flag_is_configurable():
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_PASSWORD="secret", COOKIE_SECURE=True),
        db=db,
    )
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


class ApiFakeBitProAdapter:
    def health(self):
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "health": {"status": "healthy"},
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
            ],
        }

    def market_klines(self, *, symbol: str, timeframe: str, limit: int):
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "health": {"status": "healthy"},
            "market": {
                "exchange": "okx",
                "symbol": "ETH/USDT:USDT",
                "timeframe": timeframe.lower(),
                "limit": limit,
            },
            "candles": [
                {
                    "timestamp": 1_780_272_000_000 + index * 3_600_000,
                    "open": 100 + index,
                    "high": 101 + index,
                    "low": 99 + index,
                    "close": 100 + index,
                    "volume": 1000 + index,
                }
                for index in range(limit)
            ],
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {"tool": "market_klines", "status": "success", "parameters": {}},
            ],
        }

    def paper_dashboard(self):
        return {
            "status": "ok",
            "dashboard": {"session_count": 1},
            "tool_calls": [],
        }

    def live_positions(self, *, exchange: str = "okx", symbol: str | None = None):
        return {
            "status": "ok",
            "positions": [{"exchange": exchange, "symbol": "ETH/USDT:USDT"}],
            "tool_calls": [],
        }


class FailingBitProAdapter:
    last_tool_calls = [{"tool": "bitpro_health", "status": "failed"}]

    def health(self):
        raise BitProMcpError("BitPro MCP unavailable")

    def market_klines(self, *, symbol: str, timeframe: str, limit: int):
        raise BitProMcpError("BitPro MCP unavailable")

    def paper_dashboard(self):
        raise BitProMcpError("BitPro MCP unavailable")

    def live_positions(self, *, exchange: str = "okx", symbol: str | None = None):
        raise BitProMcpError("BitPro MCP unavailable")
