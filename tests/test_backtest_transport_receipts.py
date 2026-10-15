import httpx
from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter


def test_create_transmits_idempotency_and_preserves_frozen_hash():
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.path.endswith("/run_job"):
            return httpx.Response(
                200, json={"job_id": "j", "input_snapshot_hash": "sha256:" + "a" * 64}
            )
        return httpx.Response(200, json={})

    adapter = BitProToolAdapter(
        BitProMcpClient(http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    )
    result = adapter.backtest_start_job(
        strategy_id=7, start_date="2026-01-01", end_date="2026-02-01", idempotency_key="request-key"
    )
    request = next(r for r in seen if r.method == "POST")
    assert request.headers["Idempotency-Key"] == "request-key"
    assert result["job"]["input_snapshot_hash"] == "sha256:" + "a" * 64


def test_resume_targets_existing_job_and_keeps_hash():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "job_id": "j",
                "strategy_id": 7,
                "status": "pending",
                "strategy_input_snapshot": {"hash": "sha256:" + "a" * 64},
            },
        )

    adapter = BitProToolAdapter(
        BitProMcpClient(http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    )
    result = adapter.backtest_resume_job(job_id="j", idempotency_key="resume-key")
    request = next(r for r in seen if r.method == "POST")
    assert request.url.path.endswith("/backtest/job/j/resume")
    assert request.headers["Idempotency-Key"] == "resume-key"
    assert result["job"]["input_snapshot_hash"] == "sha256:" + "a" * 64


def test_runtime_revalidation_is_explicit_in_request_and_response():
    seen = []

    def respond(req):
        seen.append(req)
        return httpx.Response(
            200,
            json={
                "job_id": "new",
                "input_snapshot_hash": "sha256:" + "b" * 64,
                "recovery_of_job_id": "old",
            },
        )

    adapter = BitProToolAdapter(
        BitProMcpClient(http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    )
    result = adapter.backtest_start_job(
        strategy_id=7,
        start_date="2026-01-01",
        end_date="2026-02-01",
        idempotency_key="version1",
        recovery_of_job_id="old",
    )
    assert next(r for r in seen if r.method == "POST").headers["X-Backtest-Recovery-Of"] == "old"
    assert result["job"]["recovery_of_job_id"] == "old"
