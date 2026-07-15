from __future__ import annotations

import pytest
from hypertrade.runtime.adapters.sandbox import InMemorySandboxStore, StrategySandbox
from hypertrade.runtime.domain.sandbox import SandboxCommandV1, SandboxRequestV1
from pydantic import ValidationError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def request(**updates: object) -> SandboxRequestV1:
    values: dict[str, object] = {
        "assignment_ref": "assignment:asgn_test",
        "context_pack_refs": ("context:ctxp_test@" + "a" * 64,),
        "files": {
            "strategies/candidate.py": (
                "def generate_signals(prices: list[float]) -> list[int]:\n"
                "    return [0 for _ in prices]\n"
            ),
            "tests/test_candidate.py": (
                "from strategies.candidate import generate_signals\n\n"
                "def test_signals():\n"
                "    assert generate_signals([1.0, 2.0]) == [0, 0]\n"
            ),
        },
        "commands": ({"name": "pytest"},),
        "idempotency_key": "sandbox-isolation-001",
    }
    values.update(updates)
    return SandboxRequestV1.model_validate(values)


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/tmp/escape.py", "backend/escape.py", "strategies/code.sh"],
)
@pytest.mark.anyio
async def test_sandbox_denies_path_traversal_roots_and_extensions(path: str) -> None:
    sandbox = StrategySandbox(InMemorySandboxStore())
    with pytest.raises(ValueError, match="path is not allowed"):
        await sandbox.run("mis_isolation", request(files={path: "print('unsafe')"}))


@pytest.mark.parametrize(
    "source",
    [
        "import socket\n",
        "import subprocess\n",
        "import requests\n",
        "import os\nos.system('id')\n",
        "eval('1 + 1')\n",
    ],
)
@pytest.mark.anyio
async def test_sandbox_denies_network_process_and_dynamic_execution(source: str) -> None:
    sandbox = StrategySandbox(InMemorySandboxStore())
    with pytest.raises(ValueError, match="forbidden"):
        await sandbox.run("mis_isolation", request(files={"strategies/candidate.py": source}))


def test_command_contract_denies_shell_paths_network_and_interpreter_code() -> None:
    for argument in ("-c", "../escape", "/tmp/file", "https://example.com"):
        with pytest.raises(ValidationError, match="forbidden argument"):
            SandboxCommandV1(name="pytest", args=(argument,))


@pytest.mark.anyio
async def test_workspace_quota_is_enforced_before_file_creation() -> None:
    sandbox = StrategySandbox(InMemorySandboxStore())
    with pytest.raises(ValueError, match="workspace exceeds"):
        await sandbox.run(
            "mis_isolation",
            request(files={"strategies/candidate.py": "#" + "x" * 262_144}),
        )


@pytest.mark.anyio
async def test_sandbox_environment_has_no_inherited_secret() -> None:
    sandbox = StrategySandbox(InMemorySandboxStore())
    payload = request(
        files={
            "strategies/candidate.py": (
                "def generate_signals(prices: list[float]) -> list[int]:\n"
                "    return [0 for _ in prices]\n"
            ),
            "tests/test_environment.py": (
                "import os\n\n"
                "def test_no_secrets():\n"
                "    assert not any('SECRET' in key or 'TOKEN' in key for key in os.environ)\n"
                "    assert os.environ['HYPERTRADE_SANDBOX'] == '1'\n"
            ),
        }
    )
    result = await sandbox.run("mis_isolation", payload)

    assert result.status == "validated"


@pytest.mark.anyio
async def test_timeout_is_typed_and_stops_remaining_commands() -> None:
    sandbox = StrategySandbox(InMemorySandboxStore(), command_timeout_seconds=0.02)
    payload = request(
        files={
            "strategies/candidate.py": (
                "def generate_signals(prices: list[float]) -> list[int]:\n"
                "    return [0 for _ in prices]\n"
            ),
            "tests/test_slow.py": ("import time\n\ndef test_slow():\n    time.sleep(0.2)\n"),
        },
        commands=({"name": "pytest"}, {"name": "limited_backtest"}),
    )
    result = await sandbox.run("mis_isolation", payload)

    assert result.status == "failed"
    assert result.commands[0].status == "timeout"
    assert len(result.commands) == 1


@pytest.mark.anyio
async def test_command_output_is_bounded_and_hashed_from_full_stream() -> None:
    sandbox = StrategySandbox(InMemorySandboxStore())
    payload = request(
        files={
            "strategies/candidate.py": (
                "def generate_signals(prices):\n"
                "    return [0 for _ in prices]\n"
            ),
            "tests/test_output.py": "def test_output():\n    print('x' * 100000)\n",
        },
        commands=({"name": "pytest", "args": ("-s",)},),
    )
    result = await sandbox.run("mis_output", payload)

    command = result.commands[0]
    assert result.status == "validated"
    assert command.output_bytes > 100_000
    assert len(command.output_preview) <= 16_384
    assert command.truncated is True
