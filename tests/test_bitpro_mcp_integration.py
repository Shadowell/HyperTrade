from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from hypertrade.agent.kernel import AgentKernel
from hypertrade.bitpro import mcp as bitpro_mcp
from hypertrade.bitpro.mcp import (
    BitProMcpClient,
    BitProMcpError,
    BitProToolAdapter,
    bitpro_capabilities,
    clear_http_client_pool,
    clear_probe_cache,
)
from hypertrade.config import Settings
from hypertrade.db import AgentRun, Database, TraceEvent
from hypertrade.tools.registry import (
    ToolRegistry,
    read_only_runtime_tool_names,
)


@pytest.fixture(autouse=True)
def _reset_bitpro_module_caches() -> Iterator[None]:
    clear_http_client_pool()
    clear_probe_cache()
    yield
    clear_http_client_pool()
    clear_probe_cache()


def _make_settings(
    *,
    base_url: str = "http://bitpro.test/api/v2",
    api_token: str = "secret-token",
    timeout_seconds: float = 15.0,
) -> Settings:
    return Settings(
        _env_file=None,
        BITPRO_MCP_API_BASE=base_url,
        BITPRO_MCP_API_TOKEN=api_token,
        BITPRO_MCP_TIMEOUT_SECONDS=timeout_seconds,
    )


def _make_client(
    *,
    base_url: str = "http://bitpro.test/api/v2",
    api_token: str = "secret-token",
    timeout_seconds: float = 15.0,
    http_client: httpx.Client | None = None,
) -> BitProMcpClient:
    return BitProMcpClient(
        settings=_make_settings(
            base_url=base_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        ),
        http_client=http_client,
    )


def _make_mock_adapter(
    handler: Any,
    *,
    base_url: str = "http://bitpro.test/api/v2",
    api_token: str = "secret-token",
) -> tuple[BitProToolAdapter, httpx.Client]:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = _make_client(
        base_url=base_url,
        api_token=api_token,
        http_client=http_client,
    )
    return BitProToolAdapter(client), http_client


def test_http_client_pool_reuses_bounded_entries_and_isolates_explicit_mocks() -> None:
    c1 = _make_client(base_url="http://127.0.0.1:8889/api/v2", timeout_seconds=10.0)
    c2 = _make_client(base_url="http://127.0.0.1:8889/api/v2", timeout_seconds=10.0)
    c3 = _make_client(base_url="http://127.0.0.1:8889/api/v2", timeout_seconds=20.0)

    assert c1.http_client is c2.http_client
    assert c1._uses_pooled_http_client is True
    assert c3.http_client is not c1.http_client
    assert len(bitpro_mcp._HTTP_CLIENT_POOL) == 2

    explicit_client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"status": "ok"}))
    )
    injected = _make_client(
        base_url="http://127.0.0.1:8889/api/v2",
        http_client=explicit_client,
    )
    assert injected.http_client is explicit_client
    assert injected._uses_pooled_http_client is False
    assert len(bitpro_mcp._HTTP_CLIENT_POOL) == 2

    # Concurrent construction for the same pool key returns the exact same instance.
    def _build_same(_: int) -> httpx.Client:
        return _make_client(
            base_url="http://127.0.0.1:9991/api/v2",
            timeout_seconds=7.5,
        ).http_client

    with ThreadPoolExecutor(max_workers=6) as pool:
        concurrent_clients = list(pool.map(_build_same, range(12)))
    assert len({id(item) for item in concurrent_clients}) == 1

    # Exceeding max pool size evicts and closes the least recently used entry,
    # while leaving explicit injected clients untouched and open.
    clear_http_client_pool()
    pooled_clients: list[BitProMcpClient] = []
    for idx in range(bitpro_mcp._HTTP_CLIENT_POOL_MAX_SIZE):
        pooled_clients.append(
            _make_client(base_url=f"http://127.0.0.1:{8800 + idx}/api/v2")
        )
    assert len(bitpro_mcp._HTTP_CLIENT_POOL) == bitpro_mcp._HTTP_CLIENT_POOL_MAX_SIZE

    # Touch entry 0 so entry 1 becomes least recently used.
    refreshed_zero = _make_client(base_url="http://127.0.0.1:8800/api/v2")
    assert refreshed_zero.http_client is pooled_clients[0].http_client

    overflow = _make_client(base_url="http://127.0.0.1:8899/api/v2")
    assert overflow.http_client is not None
    assert len(bitpro_mcp._HTTP_CLIENT_POOL) == bitpro_mcp._HTTP_CLIENT_POOL_MAX_SIZE
    assert pooled_clients[1].http_client.is_closed is True
    assert pooled_clients[0].http_client.is_closed is False
    assert explicit_client.is_closed is False

    clear_http_client_pool()
    assert len(bitpro_mcp._HTTP_CLIENT_POOL) == 0
    assert explicit_client.is_closed is False
    explicit_client.close()


def test_diagnostic_error_hints_for_connection_timeout_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(bitpro_mcp, "_running_in_docker", lambda: False)
    non_docker_adapter, c_non_docker = _make_mock_adapter(
        _raise_connect_error,
        base_url="http://127.0.0.1:8889/api/v2",
    )
    with pytest.raises(BitProMcpError) as non_docker_exc:
        non_docker_adapter.health()
    assert non_docker_exc.value.hint is not None
    assert "[hint:" in str(non_docker_exc.value)
    assert "host.docker.internal" not in non_docker_exc.value.hint
    c_non_docker.close()

    monkeypatch.setattr(bitpro_mcp, "_running_in_docker", lambda: True)
    docker_adapter, c_docker = _make_mock_adapter(
        _raise_connect_error,
        base_url="http://127.0.0.1:8889/api/v2",
    )
    with pytest.raises(BitProMcpError) as docker_exc:
        docker_adapter.health()
    assert docker_exc.value.hint is not None
    assert "http://host.docker.internal:8889/api/v2" in docker_exc.value.hint
    assert "http://host.docker.internal:8889/api/v2" in str(docker_exc.value)
    c_docker.close()

    def _raise_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    timeout_adapter, c_timeout = _make_mock_adapter(_raise_timeout)
    with pytest.raises(BitProMcpError) as timeout_exc:
        timeout_adapter.health()
    assert timeout_exc.value.hint is not None
    assert "timed out" in str(timeout_exc.value).lower()
    assert "[hint:" in str(timeout_exc.value)
    c_timeout.close()

    def _return_401(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthorized"})

    missing_token_adapter, c_missing = _make_mock_adapter(_return_401, api_token="")
    with pytest.raises(BitProMcpError) as missing_exc:
        missing_token_adapter.health()
    assert missing_exc.value.status_code == 401
    assert missing_exc.value.hint is not None
    assert "BITPRO_MCP_API_TOKEN" in missing_exc.value.hint
    assert "X-BitPro-MCP-Token" in missing_exc.value.hint
    assert "[hint:" in str(missing_exc.value)
    c_missing.close()

    def _return_403(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    forbidden_adapter, c_forbidden = _make_mock_adapter(_return_403, api_token="wrong-token")
    with pytest.raises(BitProMcpError) as forbidden_exc:
        forbidden_adapter.health()
    assert forbidden_exc.value.status_code == 403
    assert forbidden_exc.value.hint is not None
    assert "BITPRO_MCP_API_TOKEN" in forbidden_exc.value.hint
    assert "X-BitPro-MCP-Token" in str(forbidden_exc.value)
    c_forbidden.close()


def test_adapter_settings_and_probe_connectivity_ttl_and_classifications() -> None:
    settings = _make_settings(
        base_url="http://bitpro.custom:9876/api/v2",
        api_token="custom-token",
        timeout_seconds=12.0,
    )
    settings_adapter = BitProToolAdapter(settings=settings)
    assert settings_adapter.client.base_url == "http://bitpro.custom:9876/api/v2"
    assert settings_adapter.client.auth_token == "custom-token"
    assert settings_adapter.client.settings.bitpro_mcp_timeout_seconds == 12.0

    health_calls = 0

    def _healthy_handler(request: httpx.Request) -> httpx.Response:
        nonlocal health_calls
        health_calls += 1
        assert request.url.path == "/api/v2/system/health"
        return httpx.Response(200, json={"status": "healthy"})

    adapter, http_client = _make_mock_adapter(_healthy_handler)
    first = adapter.probe_connectivity(ttl_seconds=15.0)
    second = adapter.probe_connectivity(ttl_seconds=15.0)
    assert first == second
    assert health_calls == 1
    assert first["reachable"] is True
    assert first["authenticated"] is True
    assert first["status"] == "healthy"
    assert isinstance(first["latency_ms"], float)
    assert first["api_base"] == "http://bitpro.test/api/v2"
    assert first["token_configured"] is True
    assert first["error"] is None
    assert first["hint"] is None

    clear_probe_cache()
    adapter.probe_connectivity(ttl_seconds=15.0)
    assert health_calls == 2
    adapter.probe_connectivity(ttl_seconds=0.0)
    assert health_calls == 3
    http_client.close()

    auth_adapter, c_auth = _make_mock_adapter(
        lambda _: httpx.Response(401, json={"detail": "bad token"}),
        base_url="http://bitpro-auth.test/api/v2",
        api_token="",
    )
    auth_probe = auth_adapter.probe_connectivity(ttl_seconds=0.0)
    assert auth_probe["reachable"] is True
    assert auth_probe["authenticated"] is False
    assert auth_probe["status"] == "unauthorized"
    assert auth_probe["token_configured"] is False
    assert auth_probe["error"]
    assert auth_probe["hint"] and "BITPRO_MCP_API_TOKEN" in auth_probe["hint"]
    c_auth.close()

    forbidden_adapter, c_forbidden = _make_mock_adapter(
        lambda _: httpx.Response(403, json={"detail": "forbidden"}),
        base_url="http://bitpro-forbid.test/api/v2",
        api_token="wrong-token",
    )
    forbidden_probe = forbidden_adapter.probe_connectivity(ttl_seconds=0.0)
    assert forbidden_probe["reachable"] is True
    assert forbidden_probe["authenticated"] is False
    assert forbidden_probe["status"] == "forbidden"
    c_forbidden.close()

    def _connect_fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    down_adapter, c_down = _make_mock_adapter(
        _connect_fail,
        base_url="http://bitpro-down.test/api/v2",
    )
    down_probe = down_adapter.probe_connectivity(ttl_seconds=0.0)
    assert down_probe["reachable"] is False
    assert down_probe["authenticated"] is False
    assert down_probe["status"] == "unreachable"
    assert down_probe["error"]
    assert down_probe["hint"]
    c_down.close()


def test_new_bitpro_mcp_v1_endpoints_and_capabilities() -> None:
    recorded: list[dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        recorded.append(
            {
                "method": request.method,
                "path": request.url.path,
                "params": dict(request.url.params),
                "body": body,
                "token": request.headers.get("X-BitPro-MCP-Token"),
            }
        )
        path = request.url.path
        if path == "/api/v2/system/health":
            return httpx.Response(200, json={"status": "healthy"})
        if path == "/api/v2/research/collaboration/snapshot":
            return httpx.Response(200, json={"project_id": "proj-1", "events": [], "cursor": 4})
        if path == "/api/v2/research/collaboration/events" and request.method == "GET":
            return httpx.Response(200, json={"events": [{"id": 5}], "next_cursor": 5})
        if path == "/api/v2/research/collaboration/events" and request.method == "POST":
            return httpx.Response(200, json={"event_id": "evt-99", "cursor": 6})
        if path == "/api/v2/research/collaboration/checkpoints/bot-alpha":
            return httpx.Response(200, json={"bot_id": "bot-alpha", "cursor": 6})
        if path == "/api/v2/review/summary":
            return httpx.Response(200, json={"window": "24h", "net_pnl": 125.5})
        if path == "/api/v2/monitor/active_strategies":
            return httpx.Response(200, json=[{"id": 1, "name": "Momentum"}])
        if path == "/api/v2/onchain/summary":
            return httpx.Response(200, json={"signals": 3, "compact": True})
        if path == "/api/v2/factorlab/studio/operators":
            return httpx.Response(200, json={"operators": ["ts_rank", "ts_mean"]})
        if path == "/api/v2/factorlab/studio/alphas":
            return httpx.Response(200, json={"items": [{"id": 11, "grade": "EXCELLENT"}]})
        if path == "/api/v2/factorlab/studio/matrix":
            return httpx.Response(200, json={"ready": True, "symbols": ["BTC", "ETH"]})
        if path == "/api/v2/factorlab/studio/runner/status":
            return httpx.Response(200, json={"running": False, "queued": 0})
        if path == "/api/v2/factorlab/studio/simulate":
            return httpx.Response(200, json={"sharpe": 2.4, "grade": "GOOD"})
        if path == "/api/v2/factorlab/studio/simulate/batch":
            return httpx.Response(200, json={"results": [{"sharpe": 2.1}], "count": 1})
        return httpx.Response(404, json={"detail": f"unexpected path: {path}"})

    adapter, http_client = _make_mock_adapter(_handler)

    snap = adapter.research_context_snapshot(project_id="proj-1", limit=25, topics=["regime"])
    assert snap["cursor"] == 4
    delta = adapter.research_context_delta(
        project_id="proj-1",
        after_cursor=4,
        limit=10,
        topics=["regime"],
        event_types=["observation"],
        include_expired=True,
    )
    assert delta["next_cursor"] == 5
    pub = adapter.research_publish_event(
        project_id="proj-1",
        bot_id="bot-alpha",
        squad_id="hypertrade",
        event_type="hypothesis",
        topic="btc_trend",
        payload={"bias": "bullish"},
        idempotency_key="idem-pub-1",
        symbol="BTC",
        confidence=0.82,
        source_ref="run-1",
    )
    assert pub["event_id"] == "evt-99"
    ckpt = adapter.research_bot_checkpoint(
        project_id="proj-1",
        bot_id="bot-alpha",
        cursor=6,
        idempotency_key="idem-ckpt-1",
    )
    assert ckpt["cursor"] == 6
    ckpt_read = adapter.research_get_checkpoint(project_id="proj-1", bot_id="bot-alpha")
    assert ckpt_read["bot_id"] == "bot-alpha"

    review = adapter.review_summary(window="24h", bucket="1h", include_stopped=True)
    assert review["net_pnl"] == 125.5
    mon = adapter.monitor_active_strategies(include_paused=True)
    assert mon["count"] == 1
    assert mon["strategies"][0]["name"] == "Momentum"
    assert adapter.onchain_summary(compact=True)["signals"] == 3

    assert adapter.factorlab_get_operators()["operators"] == ["ts_rank", "ts_mean"]
    alphas = adapter.factorlab_list_alphas(grade="EXCELLENT", query="rank", limit=15, offset=5)
    assert alphas["items"][0]["id"] == 11
    assert adapter.factorlab_matrix_check()["ready"] is True
    assert adapter.factorlab_runner_status()["queued"] == 0
    assert adapter.factorlab_simulate(expression="ts_rank(close, 10)", idempotency_key="idem-sim")[
        "sharpe"
    ] == 2.4
    batch = adapter.factorlab_batch_simulate(
        alphas=[{"expression": "ts_rank(close, 10)", "name": "a1"}],
        auto_save_excellent=True,
        idempotency_key="idem-batch",
    )
    assert batch["count"] == 1

    # Verify exact HTTP routes & key query/body parameters (excluding preflight /system/health).
    non_health = [item for item in recorded if item["path"] != "/api/v2/system/health"]
    assert [(item["method"], item["path"]) for item in non_health] == [
        ("GET", "/api/v2/research/collaboration/snapshot"),
        ("GET", "/api/v2/research/collaboration/events"),
        ("POST", "/api/v2/research/collaboration/events"),
        ("PUT", "/api/v2/research/collaboration/checkpoints/bot-alpha"),
        ("GET", "/api/v2/research/collaboration/checkpoints/bot-alpha"),
        ("GET", "/api/v2/review/summary"),
        ("GET", "/api/v2/monitor/active_strategies"),
        ("GET", "/api/v2/onchain/summary"),
        ("GET", "/api/v2/factorlab/studio/operators"),
        ("GET", "/api/v2/factorlab/studio/alphas"),
        ("GET", "/api/v2/factorlab/studio/matrix"),
        ("GET", "/api/v2/factorlab/studio/runner/status"),
        ("POST", "/api/v2/factorlab/studio/simulate"),
        ("POST", "/api/v2/factorlab/studio/simulate/batch"),
    ]
    assert non_health[2]["body"]["idempotency_key"] == "idem-pub-1"
    assert non_health[3]["body"]["idempotency_key"] == "idem-ckpt-1"
    assert non_health[9]["params"]["q"] == "rank"
    assert non_health[13]["body"]["auto_save_excellent"] is True
    assert all(item["token"] == "secret-token" for item in non_health)

    caps = bitpro_capabilities()
    expected_read = {
        "research_context_snapshot",
        "research_context_delta",
        "research_get_checkpoint",
        "review_summary",
        "monitor_active_strategies",
        "onchain_summary",
        "factorlab_get_operators",
        "factorlab_list_alphas",
        "factorlab_matrix_check",
        "factorlab_runner_status",
    }
    expected_write = {
        "research_publish_event",
        "research_bot_checkpoint",
        "factorlab_simulate",
        "factorlab_batch_simulate",
    }
    assert expected_read.issubset(set(caps["tool_groups"]["read"]))
    assert expected_write.issubset(set(caps["tool_groups"]["research_backtest_paper_mutation"]))
    assert expected_write.issubset(set(caps["agent_auth"]["idempotency"]["required_tools"]))
    assert expected_read.issubset(set(caps["tool_endpoints"]))
    assert expected_write.issubset(set(caps["tool_endpoints"]))
    http_client.close()


def test_registry_and_kernel_dispatch_and_paper_stop_continuity_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry.default()
    expected_mappings = {
        "bitpro_variant_policy": ("bitpro.variant_policy", "read", "not_required"),
        "bitpro_relay_plans": ("bitpro.relay_plans", "read", "not_required"),
        "bitpro_research_context_snapshot": (
            "bitpro.research_context_snapshot",
            "read",
            "not_required",
        ),
        "bitpro_research_publish_event": (
            "bitpro.research_publish_event",
            "research_write",
            "required",
        ),
        "arc_evolution_status": ("arc.evolution_status", "read", "not_required"),
    }
    for runtime_name, (registry_name, scope, idempotency) in expected_mappings.items():
        definition = registry.get_for_runtime_name(runtime_name)
        assert definition.name == registry_name
        assert definition.policy.scope == scope
        assert definition.policy.idempotency == idempotency
        assert definition.policy.approval == "none"

    ro_names = read_only_runtime_tool_names()
    assert {
        "bitpro_variant_policy",
        "bitpro_relay_plans",
        "bitpro_research_context_snapshot",
        "arc_evolution_status",
    }.issubset(ro_names)
    assert "bitpro_research_publish_event" not in ro_names

    captured_requests: list[dict[str, Any]] = []

    def _kernel_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        captured_requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "params": dict(request.url.params),
                "body": body,
            }
        )
        path = request.url.path
        if path == "/api/v2/system/health":
            return httpx.Response(200, json={"status": "healthy"})
        if path == "/api/v2/live/stop":
            return httpx.Response(
                200,
                json={"status": "stopped", "paper": {"instance_id": "p-7", "status": "stopped"}},
            )
        if path == "/api/v2/strategies/12/research-variant-policy":
            return httpx.Response(
                200,
                json={
                    "contract_version": "strategy_research_variant_policy.v1",
                    "parent_strategy_id": 12,
                    "authorized_parameters": ["lookback"],
                    "parent_manifest_sha256": "a" * 64,
                    "parent_execution_identity_sha256": "b" * 64,
                    "max_variants": 5,
                },
            )
        if path == "/api/v2/strategies/relay-plans":
            return httpx.Response(
                200,
                json=[{"plan_id": "relay-1", "status": "active"}],
            )
        if path == "/api/v2/research/collaboration/snapshot":
            return httpx.Response(
                200,
                json={"project_id": "default", "events": [{"topic": "regime"}], "cursor": 9},
            )
        if path == "/api/v2/research/collaboration/events" and request.method == "POST":
            return httpx.Response(
                200,
                json={"event_id": "evt-kernel-1", "cursor": 10},
            )
        return httpx.Response(404, json={"detail": f"unexpected path: {path}"})

    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        session.add(AgentRun(id="run-int-1", prompt="bitpro integration test", status="running"))
        session.commit()
    settings = _make_settings(
        base_url="http://bitpro.kernel.test/api/v2",
        api_token="kernel-token",
    )
    kernel = AgentKernel(db, settings=settings, knowledge_dir="docs/knowledge")
    adapter, http_client = _make_mock_adapter(
        _kernel_handler,
        base_url="http://bitpro.kernel.test/api/v2",
        api_token="kernel-token",
    )
    monkeypatch.setattr(kernel, "_bitpro_adapter", lambda: adapter)

    executor = kernel._build_executor("run-int-1")

    # Planner executor keeps bitpro_paper_stop blocked by governance.
    blocked_stop = executor(
        "bitpro_paper_stop",
        {"strategy_id": 12, "clear_metrics": True, "idempotency_key": "idem-stop-blocked"},
    )
    assert blocked_stop["status"] == "denied"
    assert [item for item in captured_requests if item["path"] == "/api/v2/live/stop"] == []

    # Direct kernel dispatch of bitpro_paper_stop enforces BitPro Core Rule #7:
    # force clear_metrics=False and attach a continuity note even if True was passed.
    stop_res = kernel._dispatch_tool(
        "bitpro_paper_stop",
        {"strategy_id": 12, "clear_metrics": True},
        run_id="run-int-1",
        policy=registry.get_for_runtime_name("bitpro_paper_stop").policy,
    )
    assert stop_res["status"] == "ok"
    assert stop_res["clear_metrics_enforced"] is False
    assert stop_res["clear_metrics_requested"] is True
    assert "continuity_guard" in stop_res["continuity_note"]
    stop_reqs = [item for item in captured_requests if item["path"] == "/api/v2/live/stop"]
    assert len(stop_reqs) == 1
    assert stop_reqs[0]["body"]["instance_id"] == 12
    assert stop_reqs[0]["body"]["clear_metrics"] is False

    # Newly wired read tools via kernel executor.
    policy_res = executor("bitpro_variant_policy", {"strategy_id": 12})
    assert policy_res["parent_strategy_id"] == 12
    assert policy_res["max_variants"] == 5

    relay_res = executor("bitpro_relay_plans", {})
    assert relay_res["status"] == "ok"
    assert relay_res["count"] == 1
    assert relay_res["plans"][0]["plan_id"] == "relay-1"

    snap_res = executor(
        "bitpro_research_context_snapshot",
        {"project_id": "default", "limit": 20, "topics": ["regime"]},
    )
    assert snap_res["cursor"] == 9

    # Governance enforces idempotency_key for bitpro_research_publish_event.
    denied_pub = executor(
        "bitpro_research_publish_event",
        {
            "bot_id": "hypertrade-researcher",
            "event_type": "observation",
            "topic": "btc_vol",
            "payload": {"atr_pct": 2.3},
        },
    )
    assert denied_pub["status"] == "denied"
    assert denied_pub["denial_reason"] == "missing required field: idempotency_key"

    allowed_pub = executor(
        "bitpro_research_publish_event",
        {
            "bot_id": "hypertrade-researcher",
            "event_type": "observation",
            "topic": "btc_vol",
            "payload": {"atr_pct": 2.3},
            "idempotency_key": "idem-pub-kernel-1",
            "symbol": "BTC",
            "confidence": 0.9,
            "source_ref": "kernel-test",
        },
    )
    assert allowed_pub["event_id"] == "evt-kernel-1"
    pub_reqs = [
        item
        for item in captured_requests
        if item["path"] == "/api/v2/research/collaboration/events" and item["method"] == "POST"
    ]
    assert len(pub_reqs) == 1
    assert pub_reqs[0]["body"]["idempotency_key"] == "idem-pub-kernel-1"
    assert pub_reqs[0]["body"]["symbol"] == "BTC"

    evo_res = executor("arc_evolution_status", {"compact": True, "cycles_limit": 5})
    assert {"config", "budget", "revision", "cycles", "continuations"}.issubset(set(evo_res))

    with db.session() as session:
        traced_tools = {row.tool_name for row in session.query(TraceEvent).all()}
    assert {
        "bitpro.paper_stop",
        "bitpro.variant_policy",
        "bitpro.relay_plans",
        "bitpro.research_context_snapshot",
        "bitpro.research_publish_event",
    }.issubset(traced_tools)

    http_client.close()
