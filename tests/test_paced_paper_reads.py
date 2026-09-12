import httpx
import pytest
from hypertrade.bitpro.paced_reads import PacedReadClient
from hypertrade.config import Settings


def test_read_pacing_health_cache_and_no_mutation(monkeypatch):
    now = [100.0]
    calls = []
    monkeypatch.setattr("hypertrade.bitpro.paced_reads.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "hypertrade.bitpro.paced_reads.time.sleep",
        lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    def handler(request):
        calls.append((request.url.path, now[0]))
        return httpx.Response(200, json={"status": "healthy"})

    client = PacedReadClient(
        settings=Settings(BITPRO_MCP_API_BASE="http://test/api/v2"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.call_tool("bitpro_health")
    client.call_tool("bitpro_health")
    client.call_tool("paper_snapshot", {"strategy_id": 501})
    assert len(calls) == 2
    assert calls[1][1] - calls[0][1] >= 1.09
    with pytest.raises(PermissionError):
        client.call_tool("paper_start", {"strategy_id": 501})
    assert len(calls) == 2


def test_429_read_is_retried_with_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "hypertrade.bitpro.paced_reads.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            429 if len(calls) == 1 else 200,
            json={"detail": "rate limited"} if len(calls) == 1 else {"status": "ok"},
        )

    client = PacedReadClient(
        settings=Settings(BITPRO_MCP_API_BASE="http://test/api/v2"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.call_tool("paper_snapshot", {"strategy_id": 501})["status"] == "ok"
    assert len(calls) == 2
    assert 5 in sleeps
