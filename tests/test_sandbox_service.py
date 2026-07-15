from __future__ import annotations

import pytest
from hypertrade.sandbox_service import (
    SandboxBrokerCommandV1,
    execute_sandbox_command,
)


def _request(*, digest: str) -> SandboxBrokerCommandV1:
    return SandboxBrokerCommandV1.model_validate(
        {
            "image_digest": digest,
            "files": {
                "strategies/candidate.py": (
                    "def generate_signals(prices: list[float]) -> list[int]:\n"
                    "    return [0 for _ in prices]\n"
                )
            },
            "command": {"name": "limited_backtest"},
            "timeout_seconds": 5,
        }
    )


def test_sandbox_service_executes_only_matching_digest_in_disposable_workspace() -> None:
    digest = "local@sha256:" + "a" * 64

    result = execute_sandbox_command(_request(digest=digest), expected_image_digest=digest)

    assert result.status == "passed"
    assert result.argv == ("limited_backtest",)
    assert "no orders dispatched" in result.output_preview


def test_sandbox_service_rejects_a_mismatched_image_digest() -> None:
    digest = "local@sha256:" + "a" * 64

    with pytest.raises(ValueError, match="image digest"):
        execute_sandbox_command(
            _request(digest=digest),
            expected_image_digest="local@sha256:" + "b" * 64,
        )
