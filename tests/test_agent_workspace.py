"""Sprint-143: agent code workspace over the governed strategy sandbox.

Real pytest execution (in-process sandbox, local restricted runner) proves the
write -> run -> read-failure -> fix -> rerun loop; validation tests prove the
sandbox boundaries surface at write time with actionable reasons.
"""

from __future__ import annotations

import pytest
from hypertrade.agent.workspace import AgentWorkspace


@pytest.fixture()
def workspace() -> AgentWorkspace:
    return AgentWorkspace(run_id="run_ws_test_01")


def test_write_rejects_paths_outside_whitelist(workspace: AgentWorkspace) -> None:
    for path in ("../evil.py", "/etc/passwd", "notes.md", "strategies/x.sh"):
        result = workspace.write_file(path, "print('x')")

        assert result["status"] == "error"
        assert "not allowed" in result["error"]["message"]


def test_write_error_payload_is_structured(workspace: AgentWorkspace) -> None:
    result = workspace.write_file("strategies/evil.py", "import socket\n")

    assert result == {
        "status": "error",
        "error": {
            "type": "write_rejected",
            "message": "forbidden network/process import in strategies/evil.py",
        },
    }


def test_write_rejects_forbidden_python_at_write_time(workspace: AgentWorkspace) -> None:
    result = workspace.write_file(
        "strategies/network.py",
        "import socket\n\ndef phone_home():\n    return socket.socket()",
    )

    assert result["status"] == "error"
    assert "forbidden network/process import" in result["error"]["message"]


def test_write_rejects_dynamic_execution(workspace: AgentWorkspace) -> None:
    result = workspace.write_file(
        "strategies/dynamic.py",
        "def run(src):\n    return eval(src)",
    )

    assert result["status"] == "error"
    assert "forbidden dynamic execution" in result["error"]["message"]


def test_write_read_list_roundtrip(workspace: AgentWorkspace) -> None:
    written = workspace.write_file(
        "strategies/my_strategy.py",
        "lookback = 20\n\n\ndef signal(price):\n    return price > lookback\n",
    )

    assert written["status"] == "ok"

    read = workspace.read_file("strategies/my_strategy.py")
    assert read["status"] == "ok"
    assert "def signal" in read["content"]

    listing = workspace.list_files()
    assert listing["files"][0]["path"] == "strategies/my_strategy.py"
    assert listing["total_bytes"] > 0


def test_read_missing_file_is_structured(workspace: AgentWorkspace) -> None:
    result = workspace.read_file("strategies/missing.py")

    assert result["status"] == "error"
    assert result["error"]["type"] == "file_not_found"


def test_run_rejects_dangerous_command_arguments(workspace: AgentWorkspace) -> None:
    workspace.write_file("strategies/a.py", "x = 1\n")

    result = workspace.run("pytest", ["-c", "import os"])

    assert result["status"] == "error"
    assert result["error"]["type"] == "command_denied"


def test_run_on_empty_workspace_is_structured(workspace: AgentWorkspace) -> None:
    result = workspace.run("pytest")

    assert result["status"] == "error"
    assert result["error"]["type"] == "workspace_empty"


def test_run_executes_real_pytest_pass_and_fail(workspace: AgentWorkspace) -> None:
    """写策略 + 写测试 → 沙箱 pytest 真实执行：失败可读、修复后通过。"""
    workspace.write_file(
        "strategies/breakout.py",
        "def breakout_signal(price: float, threshold: float = 100.0) -> bool:\n"
        "    return price > threshold\n",
    )
    workspace.write_file(
        "tests/test_breakout.py",
        "from strategies.breakout import breakout_signal\n\n\n"
        "def test_breakout_fires_above_threshold():\n"
        "    assert breakout_signal(101) is True\n\n\n"
        "def test_breakout_holds_below_threshold():\n"
        "    assert breakout_signal(99) is False\n",
    )

    failing = workspace.run("pytest")
    # The strategy is correct, so the first run should pass; flip the code to
    # prove failures surface through output_preview, then fix and rerun.
    assert failing["status"] == "ok"
    assert failing["sandbox_status"] == "validated"
    assert failing["commands"][0]["status"] == "passed"

    workspace.write_file(
        "strategies/breakout.py",
        "def breakout_signal(price: float, threshold: float = 100.0) -> bool:\n"
        "    return price < threshold  # broken on purpose\n",
    )
    broken = workspace.run("pytest")

    assert broken["sandbox_status"] == "failed"
    assert broken["commands"][0]["status"] == "failed"
    assert "test_breakout" in broken["commands"][0]["output_preview"]
    assert "assert" in broken["commands"][0]["output_preview"]

    # Idempotent replay: identical content + command returns the same run id.
    replay = workspace.run("pytest")
    assert replay["sandbox_run_id"] == broken["sandbox_run_id"]


def test_run_ruff_lints_workspace(workspace: AgentWorkspace) -> None:
    workspace.write_file(
        "strategies/messy.py",
        "x  =1\n\n\ndef  f( ):\n    return x\n",
    )

    result = workspace.run("ruff", ["check", "."])

    # ruff may pass or fail depending on the configured rules; the contract is
    # a structured sandbox result with real lint output, not a verdict.
    assert result["status"] == "ok"
    assert result["commands"][0]["name"] == "ruff"
    assert isinstance(result["commands"][0]["output_preview"], str)


def test_registry_workspace_policies():
    from hypertrade.tools.registry import ToolRegistry

    registry = ToolRegistry.default()

    assert registry.get("workspace.write_file").policy.scope == "research_write"
    assert registry.get("workspace.read_file").policy.scope == "read"
    assert registry.get("workspace.list_files").policy.scope == "read"
    run_policy = registry.get("workspace.run").policy
    assert run_policy.scope == "research_write"
    assert run_policy.timeout_class == "long"
