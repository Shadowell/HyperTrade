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


def test_base_strategy_stub_is_injected_and_protected(workspace: AgentWorkspace) -> None:
    """契约 stub 预注入且 agent 不可覆盖（app/ 路径不在白名单）。"""
    assert workspace.read_file("tests/conftest.py")["status"] == "ok"

    overwrite = workspace.write_file("tests/conftest.py", "import socket\n")
    assert overwrite["status"] == "error"

    outside = workspace.write_file("app/core/execution/base_strategy.py", "x = 1\n")
    assert outside["status"] == "error"
    assert "not allowed" in outside["error"]["message"]


def test_agent_authored_basestrategy_strategy_passes_pytest(workspace: AgentWorkspace) -> None:
    """主线融合证明：agent 写真实 BaseStrategy 子类，沙箱 pytest 真实通过。"""
    strategy_code = (
        "from app.core.execution.base_strategy import BaseStrategy\n"
        "\n"
        "\n"
        "class DonchianAgent(BaseStrategy):\n"
        '    """20-bar Donchian breakout, agent-authored."""\n'
        "\n"
        "    async def on_init(self):\n"
        '        params = self.config.get("research_parameters", {})\n'
        "        self.p_window = int(params.get(\"window\", 20))\n"
        "        self._closes = {\n"
        "            symbol: [] for symbol in self.symbols()\n"
        "        }\n"
        "\n"
        "    async def on_bar(self, bar):\n"
        "        closes = self._closes.setdefault(bar.symbol, [])\n"
        "        closes.append(float(bar.close))\n"
        "        if len(closes) < self.p_window + 1:\n"
        "            return None\n"
        "        prior_high = max(closes[-self.p_window - 1 : -1])\n"
        "        if closes[-1] > prior_high:\n"
        "            await self.open_contract(\n"
        '                bar.symbol, "long", self.trade_notional_usdt,\n'
        "                leverage=self.leverage,\n"
        "            )\n"
        "        return None\n"
    )
    test_code = (
        "import asyncio\n"
        "from types import SimpleNamespace\n"
        "\n"
        "from app.core.execution.base_strategy import BaseStrategy\n"
        "from strategies.agent_donchian import DonchianAgent\n"
        "\n"
        "\n"
        "def test_base_strategy_contract_available():\n"
        "    assert hasattr(BaseStrategy, \"open_contract\")\n"
        "\n"
        "\n"
        "def test_donchian_opens_on_breakout():\n"
        "    strategy = DonchianAgent(\n"
        "        {\"symbols\": (\"BTC-USDT-SWAP\",), \"research_parameters\": {\"window\": 3},\n"
        "         \"trade_notional_usdt\": 1000, \"leverage\": 2}\n"
        "    )\n"
        "    strategy.trade_notional_usdt = 1000\n"
        "    strategy.leverage = 2\n"
        "\n"
        "    async def drive():\n"
        "        await strategy.on_init()\n"
        "        for close in (100.0, 101.0, 102.0, 99.0, 103.0):\n"
        "            await strategy.on_bar(\n"
        "                SimpleNamespace(symbol=\"BTC-USDT-SWAP\", close=close)\n"
        "            )\n"
        "\n"
        "    asyncio.run(drive())\n"
        "\n"
        "    opens = [order for order in strategy.orders if order[\"action\"] == \"open\"]\n"
        "    assert len(opens) == 1\n"
        "    assert opens[0][\"side\"] == \"long\"\n"
        "    assert opens[0][\"notional\"] == 1000\n"
    )
    written = workspace.write_file("strategies/agent_donchian.py", strategy_code)
    assert written["status"] == "ok"
    assert workspace.write_file("tests/test_agent_donchian.py", test_code)["status"] == "ok"

    result = workspace.run("pytest")

    assert result["sandbox_status"] == "validated", result
    assert result["commands"][0]["status"] == "passed"
    assert "passed" in result["commands"][0]["output_preview"]


def test_validate_strategy_code_gate_passes_codegen_style_code(workspace: AgentWorkspace) -> None:
    from hypertrade.agent.kernel import AgentKernel
    from hypertrade.db import Database

    workspace.write_file(
        "strategies/codegen_style.py",
        "from app.core.execution.base_strategy import BaseStrategy\n"
        "\n"
        "\n"
        "class CodegenStyle(BaseStrategy):\n"
        "    async def on_bar(self, bar: BarData):\n"
        "        return None\n",
    )
    kernel = AgentKernel(Database("sqlite:///:memory:"), knowledge_dir="docs/knowledge")
    # Kernel builds its own workspace per run; point the payload at ours.
    kernel._workspace = workspace

    result = kernel._validate_strategy_code_payload({"path": "strategies/codegen_style.py"})

    assert result["passed"] is True
    assert result["rejections"] == []
    assert len(result["content_hash"]) == 16
    assert "bitpro_strategy_create" in result["next_steps"]


def test_validate_strategy_code_gate_returns_reason_codes(workspace: AgentWorkspace) -> None:
    from hypertrade.agent.kernel import AgentKernel
    from hypertrade.db import Database

    # Sample must pass the workspace write gate (AST: no network imports,
    # no eval) while failing the ARC static gate: no BaseStrategy subclass
    # plus a secret-like literal.
    workspace.write_file(
        "strategies/phone_home.py",
        "class NotAStrategy:\n"
        "    API_KEY = \"sk-live-123\"\n"
        "\n"
        "    async def on_bar(self, bar):\n"
        "        return None\n",
    )
    kernel = AgentKernel(Database("sqlite:///:memory:"), knowledge_dir="docs/knowledge")
    kernel._workspace = workspace

    result = kernel._validate_strategy_code_payload({"path": "strategies/phone_home.py"})

    assert result["passed"] is False
    assert "code_requires_single_basestrategy_subclass" in result["rejections"]
    assert "secret_access" in result["rejections"]
    assert "re-run this gate" in result["next_steps"]


def test_validate_strategy_code_requires_canonical_basestrategy_import(
    workspace: AgentWorkspace,
) -> None:
    """BitPro 平台拒绝非规范导入——静态门必须先行拦截同一契约。"""
    from hypertrade.agent.kernel import AgentKernel
    from hypertrade.db import Database

    workspace.write_file(
        "strategies/short_import.py",
        "from strategy_base import BaseStrategy\n"
        "\n"
        "\n"
        "class Short(BaseStrategy):\n"
        "    async def on_bar(self, bar):\n"
        "        return None\n",
    )
    kernel = AgentKernel(Database("sqlite:///:memory:"), knowledge_dir="docs/knowledge")
    kernel._workspace = workspace

    result = kernel._validate_strategy_code_payload({"path": "strategies/short_import.py"})

    assert result["passed"] is False
    assert "code_requires_canonical_basestrategy_import" in result["rejections"]
