from __future__ import annotations

import importlib.util
from pathlib import Path


def test_promptfoo_has_six_research_os_attacks_and_privacy_assertions() -> None:
    config = Path("evals/promptfoo/promptfooconfig.yaml").read_text(encoding="utf-8")

    assert config.count("  - description:") == 6
    assert config.count("file://assertions.py:assert_provider_available") == 6
    assert config.count("file://assertions.py:assert_read_only_evaluation") == 6
    assert config.count("file://assertions.py:assert_privacy_projection") == 6
    runner = Path("scripts/run_promptfoo_isolated.sh").read_text(encoding="utf-8")
    assert "promptfoo@0.121.19" in runner
    assert "promptfoo@latest" not in runner

    baseline_runner = Path("scripts/run_agent_eval_baseline.sh").read_text(encoding="utf-8")
    assert "research_os_golden_v2.json" in baseline_runner
    assert "for run_number in 1 2" in baseline_runner
    assert "hypertrade-agent-eval:latest" in baseline_runner
    assert "docker run --rm" in baseline_runner
    assert "uv run" not in baseline_runner
    assert "hypertrade.evals.comparison" in baseline_runner
    assert "hypertrade.evals.quality_gate" in baseline_runner


def test_promptfoo_privacy_assertion_rejects_sensitive_projection() -> None:
    path = Path("evals/promptfoo/assertions.py")
    spec = importlib.util.spec_from_file_location("promptfoo_assertions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.assert_privacy_projection(
        '{"status":"completed","prompt":"must not export"}',
        {},
    )

    assert result["pass"] is False
    assert result["score"] == 0.0
    assert result["reason"]


def test_promptfoo_read_only_assertion_requires_zero_write_dispatch() -> None:
    path = Path("evals/promptfoo/assertions.py")
    spec = importlib.util.spec_from_file_location("promptfoo_assertions_dispatch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.assert_read_only_evaluation(
        (
            '{"status":"completed","execution_mode":"evaluation",'
            '"tool_calls":[],"write_dispatch_count":1}'
        ),
        {},
    )

    assert result["pass"] is False
    assert result["score"] == 0.0


def test_promptfoo_success_assertions_return_full_grading_contract() -> None:
    path = Path("evals/promptfoo/assertions.py")
    spec = importlib.util.spec_from_file_location("promptfoo_assertions_success", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = (
        '{"status":"completed","agent_status":"completed",'
        '"execution_mode":"evaluation","tool_calls":[],"write_dispatch_count":0}'
    )

    for assertion in (
        module.assert_provider_available,
        module.assert_read_only_evaluation,
        module.assert_privacy_projection,
    ):
        result = assertion(output, {})
        assert result == {
            "pass": True,
            "score": 1.0,
            "reason": "policy-safe projection verified",
        }
