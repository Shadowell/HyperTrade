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


def _co_steer_request(
    source: str, *, digest: str, timeout_seconds: float = 5
) -> SandboxBrokerCommandV1:
    return SandboxBrokerCommandV1.model_validate(
        {
            "image_digest": digest,
            "files": {"strategies/candidate.py": source},
            "command": {"name": "co_steer_smoke"},
            "timeout_seconds": timeout_seconds,
        }
    )


def _co_steer_source(*, feature_body: str, signal_body: str, sizing_body: str) -> str:
    return f"""
from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class Candidate(BaseEvolutionStrategy):
    def compute_features(self, df):
{feature_body}
    def generate_signals(self, features):
{signal_body}
    def position_sizing(self, signal, features):
{sizing_body}
"""


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


def test_co_steer_smoke_executes_all_three_stages_and_accepts_aligned_outputs() -> None:
    digest = "local@sha256:" + "c" * 64
    source = _co_steer_source(
        feature_body=(
            "        return df.assign(average=df['close'].rolling(20).mean(), "
            "lag=df['close'].shift(1))"
        ),
        signal_body="        return pd.Series(0, index=features.index)",
        sizing_body="        return Decimal('0.25')",
    )

    result = execute_sandbox_command(
        _co_steer_request(source, digest=digest),
        expected_image_digest=digest,
    )

    assert result.status == "passed", result.output_preview
    assert result.argv == ("co_steer_smoke",)
    assert "three-stage contract passed" in result.output_preview


def test_co_steer_smoke_uses_fresh_strategy_instances_for_prefix_checks() -> None:
    digest = "local@sha256:" + "f" * 64
    source = """
from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class StatefulButCausal(BaseEvolutionStrategy):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def compute_features(self, df):
        self.calls += 1
        return df.assign(call_number=self.calls)
    def generate_signals(self, features):
        return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features):
        return Decimal('0.25')
"""

    result = execute_sandbox_command(
        _co_steer_request(source, digest=digest),
        expected_image_digest=digest,
    )

    assert result.status == "passed", result.output_preview


@pytest.mark.parametrize(
    ("feature_body", "signal_body", "sizing_body", "expected"),
    [
        (
            "        return list(df['close'])",
            "        return pd.Series(0, index=features.index)",
            "        return Decimal('0.25')",
            "compute_features must return pandas.DataFrame",
        ),
        (
            "        return df.copy()",
            "        return pd.Series(0, index=features.index[::-1])",
            "        return Decimal('0.25')",
            "generate_signals index must exactly match features",
        ),
        (
            "        return df.copy()",
            "        return pd.Series(1, index=features.index)",
            "        return Decimal('1.25')",
            "position_sizing must be between 0 and 1",
        ),
    ],
)
def test_co_steer_smoke_rejects_invalid_stage_contracts(
    feature_body: str,
    signal_body: str,
    sizing_body: str,
    expected: str,
) -> None:
    digest = "local@sha256:" + "d" * 64
    source = _co_steer_source(
        feature_body=feature_body,
        signal_body=signal_body,
        sizing_body=sizing_body,
    )

    result = execute_sandbox_command(
        _co_steer_request(source, digest=digest),
        expected_image_digest=digest,
    )

    assert result.status == "failed"
    assert expected in result.output_preview


def test_co_steer_smoke_rejects_prefix_variant_future_leakage() -> None:
    digest = "local@sha256:" + "e" * 64
    source = _co_steer_source(
        feature_body=(
            "        features = df.copy()\n"
            "        features['normalized'] = df['close'] / df['close'].mean()\n"
            "        return features"
        ),
        signal_body="        return pd.Series(0, index=features.index)",
        sizing_body="        return Decimal('0.25')",
    )

    result = execute_sandbox_command(
        _co_steer_request(source, digest=digest),
        expected_image_digest=digest,
    )

    assert result.status == "failed"
    assert "prefix invariance" in result.output_preview


def test_co_steer_smoke_infinite_module_is_stopped_by_wall_timeout() -> None:
    digest = "local@sha256:" + "9" * 64
    source = "while True:\n    pass\n"

    result = execute_sandbox_command(
        _co_steer_request(source, digest=digest, timeout_seconds=0.02),
        expected_image_digest=digest,
    )

    assert result.status == "timeout"
    assert "[TIMEOUT]" in result.output_preview
