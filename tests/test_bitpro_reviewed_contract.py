"""Lock HyperTrade's reviewed Paper wire contract against BitPro's mirror models.

The fake BitPro below validates configure/start bodies with the same pydantic
models BitPro uses, so a field HyperTrade adds (or a response shape it wrongly
expects) fails here instead of as an HTTP 422 against production.
"""

import hashlib
import json
from typing import Any

import httpx
import pytest
from hypertrade.arc.contracts import ARCCandidateAttemptV1, PaperPreauthorizationV1
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.bitpro.mcp import (
    REVIEWED_CONFIGURE_FIELDS,
    REVIEWED_START_FIELDS,
    BitProMcpClient,
    BitProMcpError,
    BitProToolAdapter,
)
from hypertrade.config import Settings
from pydantic import BaseModel, ConfigDict, Field

STRATEGY_CODE = "class X(BaseStrategy):\n    pass\n"
STRATEGY_ID = 42
CONFIG_VERSION = "sha256:" + "c" * 64


# Mirrors BitPro backend/app/services/reviewed_paper.py; changes must land on both sides.
class _BitProReviewedPaperStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128, exclude=True)
    strategy_id: int = Field(ge=1)
    instance_id: str = Field(min_length=1)
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_version: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class _BitProReviewedPaperConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    idempotency_key: str = Field(min_length=1, max_length=128, exclude=True)
    strategy_id: int = Field(ge=1)
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    initial_equity: float = Field(gt=0, le=10000)
    exchange: str = "okx"
    symbols: list[str] = Field(min_length=1, max_length=200)
    timeframe: str = Field(pattern=r"^[1-9][0-9]*[mMhHdDwW]$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution_policy: dict[str, Any] = Field(default_factory=dict)


def _strategy_version(code: str) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {"script_content": code},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )


def _mirror_handler(
    requests: list[tuple[str, str, dict[str, Any] | None]], *, strategy_code: str
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path.endswith("/system/health"):
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.method == "GET" and request.url.path == f"/api/v2/strategies/{STRATEGY_ID}":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": STRATEGY_ID,
                        "script_content": strategy_code,
                        "config": {},
                        "status": "stopped",
                    },
                },
            )
        if request.url.path == "/api/v2/live/reviewed/configure":
            try:
                configuration = _BitProReviewedPaperConfiguration.model_validate(body)
            except Exception as exc:
                return httpx.Response(422, json={"detail": str(exc)})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "configured": True,
                        "guard_version": "paper_review_binding.v1",
                        "strategy_id": configuration.strategy_id,
                        "instance_id": "paper_contract",
                        "strategy_version": _strategy_version(strategy_code),
                        "config_version": CONFIG_VERSION,
                        "review_hash": configuration.review_hash,
                        "code_sha256": configuration.code_sha256,
                        "configured_at": "2026-11-01T00:00:00+00:00",
                    },
                },
            )
        if request.url.path == "/api/v2/live/reviewed/start":
            try:
                start = _BitProReviewedPaperStart.model_validate(body)
            except Exception as exc:
                return httpx.Response(422, json={"detail": str(exc)})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        **start.model_dump(),
                        "started": True,
                        "guard_version": "paper_review_binding.v1",
                    },
                },
            )
        raise AssertionError(f"unexpected BitPro request: {request.method} {request.url.path}")

    return handler


def _adapter(
    requests: list[tuple[str, str, dict[str, Any] | None]], *, strategy_code: str = STRATEGY_CODE
) -> BitProToolAdapter:
    return BitProToolAdapter(
        BitProMcpClient(
            settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    _mirror_handler(requests, strategy_code=strategy_code)
                )
            ),
        )
    )


def _validated_attempt() -> ARCCandidateAttemptV1:
    return ARCCandidateAttemptV1(
        attempt_id="att_contract",
        candidate_id="cand_contract",
        state="validated",
        hypothesis="contract probe",
        strategy_code=STRATEGY_CODE,
        bitpro_strategy_id=str(STRATEGY_ID),
    )


def test_incubation_end_to_end_against_bitpro_mirror_models() -> None:
    requests: list[tuple[str, str, dict[str, Any] | None]] = []
    receipts: list[tuple[str, dict[str, Any]]] = []
    resolver = ARCPaperIncubationResolver(
        _adapter(requests),
        on_receipt=lambda kind, payload: receipts.append((kind, payload)),
    )
    ok, instance, _, message = resolver.resolve_and_provision_paper_trading(
        _validated_attempt(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"], policy_hash="a" * 64),
    )
    assert ok is True, message
    assert instance == "paper_contract"

    posts = [(path, body) for _, path, body in requests if body is not None]
    assert [path for path, _ in posts] == [
        "/api/v2/live/reviewed/configure",
        "/api/v2/live/reviewed/start",
    ]
    start_body = posts[1][1]
    assert set(start_body or {}) == {
        "strategy_id",
        "instance_id",
        "code_sha256",
        "review_hash",
        "config_version",
        "idempotency_key",
    }

    configured = [payload for kind, payload in receipts if kind == "paper_review_configured"]
    started = [payload for kind, payload in receipts if kind == "paper_review_started"]
    assert len(configured) == 1 and len(started) == 1
    assert started[0]["strategy_version"] == configured[0]["strategy_version"]
    assert started[0]["strategy_version"] == _strategy_version(STRATEGY_CODE)


def test_adapter_rejects_unexpected_fields_before_any_network_call() -> None:
    requests: list[tuple[str, str, dict[str, Any] | None]] = []
    adapter = _adapter(requests)

    with pytest.raises(BitProMcpError) as start_error:
        adapter.paper_start_reviewed(
            strategy_id=STRATEGY_ID,
            instance_id="paper_x",
            code_sha256="a" * 64,
            review_hash="b" * 64,
            config_version=CONFIG_VERSION,
            strategy_version="sha256:" + "d" * 64,
            idempotency_key="k",
        )
    assert "paper_start_reviewed_contract_mismatch" in str(start_error.value)
    assert "strategy_version" in str(start_error.value)
    assert requests == []

    with pytest.raises(BitProMcpError) as configure_error:
        adapter.paper_configure_reviewed(
            strategy_id=STRATEGY_ID,
            code_sha256="a" * 64,
            review_hash="b" * 64,
            idempotency_key="k",
            bogus=1,
        )
    assert "paper_configure_reviewed_contract_mismatch" in str(configure_error.value)
    assert "bogus" in str(configure_error.value)
    assert requests == []


def test_mirror_models_match_adapter_field_sets() -> None:
    assert set(_BitProReviewedPaperStart.model_fields) == REVIEWED_START_FIELDS
    assert set(_BitProReviewedPaperConfiguration.model_fields) == REVIEWED_CONFIGURE_FIELDS
