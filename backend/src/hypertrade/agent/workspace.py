"""Agent code workspace backed by the governed strategy sandbox.

The workspace gives the planner OpenCode-style iteration: write strategy code
and tests file by file, read them back, list the tree, and run whitelisted
commands (ruff/pytest) inside the real sandbox with structured results.

Trust boundaries are inherited from the sandbox, not redefined here:
- Paths are whitelisted to ``strategies/`` and ``tests/`` with bounded
  extensions and a 256KB total quota; traversal and absolute paths are
  rejected at write time so the agent gets immediate feedback.
- Python sources pass the sandbox AST gate at write time (no network or
  process imports, no eval/exec/dynamic import).
- Execution always goes through :class:`StrategySandbox` — the accumulated
  workspace is the request's file set, the command allowlist and resource
  limits are the sandbox's, and identical content+command replays return the
  same persisted run instead of re-executing.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from hypertrade.runtime.adapters.sandbox import (
    InMemorySandboxStore,
    SandboxRunner,
    StrategySandbox,
    _validate_files,
)
from hypertrade.runtime.domain.sandbox import (
    SandboxCommandV1,
    SandboxRequestV1,
)

# BitPro BaseStrategy contract stub, auto-injected as tests/conftest.py so
# agent-authored strategies can `from app.core.execution.base_strategy import
# BaseStrategy` under pytest. The stub registers itself in sys.modules under
# the BitPro dotted path (keeping every bootstrap file inside the whitelisted
# tests/ root) and records orders in memory for behavior unit tests; real
# performance verdicts still come from BitPro backtests. System-injected
# content: workspace_write_file cannot see or overwrite tests/conftest.py.
_WORKSPACE_BOOTSTRAP_FILES: tuple[tuple[str, str], ...] = (
    (
        "tests/conftest.py",
        "import importlib\n"
        "import os\n"
        "import sys\n"
        "import types\n"
        "from pathlib import Path\n"
        "\n"
        "# Make the workspace root importable so strategy modules resolve.\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "\n"
        "# The sandbox guard denies every socket construction; asyncio's event\n"
        "# loop needs a self-pipe socketpair to wake up. Provide an os.pipe-based\n"
        "# socketpair shim so async strategy tests run while AF_INET network\n"
        "# access stays denied (socket.socket construction remains blocked).\n"
        "socket = importlib.import_module(\"socket\")\n"
        "if not hasattr(socket, '_sandbox_socketpair'):\n"
        "    class _PipeSocket:\n"
        "        def __init__(self, fd):\n"
        "            self._fd = fd\n"
        "\n"
        "        def fileno(self):\n"
        "            return self._fd\n"
        "\n"
        "        def setblocking(self, flag):\n"
        "            os.set_blocking(self._fd, flag)\n"
        "\n"
        "        def settimeout(self, value):\n"
        "            return None\n"
        "\n"
        "        def recv(self, limit):\n"
        "            return os.read(self._fd, limit)\n"
        "\n"
        "        def send(self, data):\n"
        "            return os.write(self._fd, data)\n"
        "\n"
        "        def close(self):\n"
        "            try:\n"
        "                os.close(self._fd)\n"
        "            except OSError:\n"
        "                pass\n"
        "\n"
        "    def _sandbox_socketpair(family=None, type=None, proto=None):\n"
        "        read_fd, write_fd = os.pipe()\n"
        "        return _PipeSocket(read_fd), _PipeSocket(write_fd)\n"
        "\n"
        "    socket.socketpair = _sandbox_socketpair\n"
        "\n"
        '# Register the BitPro BaseStrategy contract stub under its dotted path\n'
        '# so strategy code can import it exactly like on the BitPro platform.\n'
        '_stub = types.ModuleType("app.core.execution.base_strategy")\n'
        "\n"
        "\n"
        "class BarData:\n"
        "        def __init__(self, symbol: str = '', close: float = 0.0):\n"
        "            self.symbol = symbol\n"
        "            self.close = close\n"
        "\n"
        "        \n"
        "class BaseStrategy:\n"
        '    """In-memory contract stub: orders are recorded, not matched."""\n'
        "\n"
        "    def __init__(self, config=None):\n"
        "        self.config = dict(config or {})\n"
        "        self.orders = []\n"
        "\n"
        "    def symbols(self):\n"
        '        return tuple(self.config.get("symbols", ()))\n'
        "\n"
        "    async def open_contract(self, symbol, side, notional, leverage=1.0):\n"
        "        self.orders.append(\n"
        "            {\n"
        '                "action": "open",\n'
        '                "symbol": symbol,\n'
        '                "side": side,\n'
        '                "notional": float(notional),\n'
        '                "leverage": float(leverage),\n'
        "            }\n"
        "        )\n"
        "\n"
        "    async def close_contract(self, symbol, side=None):\n"
        '        self.orders.append({"action": "close", "symbol": symbol, "side": side})\n'
        "\n"
        "    async def on_init(self):\n"
        "        raise NotImplementedError\n"
        "\n"
        "    async def on_bar(self, bar: BarData):\n"
        "        raise NotImplementedError\n"
        "\n"
        "\n"
        "_stub.BaseStrategy = BaseStrategy\n"
        "_stub.BarData = BarData\n"
        'sys.modules["app.core.execution.base_strategy"] = _stub\n'
        "# BitPro's execution environment provides BarData globally; mirror that\n"
        "# so annotated strategy definitions resolve without imports.\n"
        "import builtins\n"
        "\n"
        "builtins.BarData = BarData\n"
    ),
)


class AgentWorkspace:
    """Per-run persistent file area with sandbox-gated execution."""

    def __init__(
        self,
        *,
        run_id: str,
        sandbox: StrategySandbox | None = None,
        runner: SandboxRunner | None = None,
        command_timeout_seconds: float = 20.0,
    ) -> None:
        self._run_id = run_id
        # System-injected contract files live outside the agent-writable
        # whitelist; write_file can never see or overwrite them.
        self._files: dict[str, str] = dict(_WORKSPACE_BOOTSTRAP_FILES)
        self._sandbox = sandbox or StrategySandbox(
            InMemorySandboxStore(),
            command_timeout_seconds=command_timeout_seconds,
            runner=runner,
        )

    # ------------------------------------------------------------------
    # File operations (validated at write time for immediate feedback)
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        # Only agent-authored files pass the sandbox gate: the bootstrap
        # conftest is trusted system content whose socket shim deliberately
        # uses runtime imports the AST gate would otherwise flag. Bootstrap
        # entries always win, so write_file can never touch them.
        bootstrap_paths = {bootstrap_path for bootstrap_path, _ in _WORKSPACE_BOOTSTRAP_FILES}
        if str(path) in bootstrap_paths:
            return {
                "status": "error",
                "error": {
                    "type": "write_rejected",
                    "message": f"{path} is a system file and cannot be modified",
                },
            }
        agent_files = {
            agent_path: agent_content
            for agent_path, agent_content in self._files.items()
            if agent_path not in bootstrap_paths
        }
        agent_files[str(path)] = str(content)
        try:
            validated = _validate_files(agent_files)
        except ValueError as exc:
            return {
                "status": "error",
                "error": {"type": "write_rejected", "message": str(exc)[:300]},
            }
        self._files = {**validated, **dict(_WORKSPACE_BOOTSTRAP_FILES)}
        return {
            "status": "ok",
            "path": path,
            "bytes": len(content.encode("utf-8")),
            "workspace_files": len(self._files),
        }

    def read_file(self, path: str) -> dict[str, Any]:
        path = str(path)
        if path not in self._files:
            return {
                "status": "error",
                "error": {
                    "type": "file_not_found",
                    "message": f"{path} is not in the workspace",
                },
            }
        content = self._files[path]
        return {
            "status": "ok",
            "path": path,
            "bytes": len(content.encode("utf-8")),
            "content": content[:16_000],
            "truncated": len(content) > 16_000,
        }

    def list_files(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "files": [
                {
                    "path": path,
                    "bytes": len(content.encode("utf-8")),
                    "content_hash": sha256(content.encode("utf-8")).hexdigest()[:16],
                }
                for path, content in sorted(self._files.items())
            ],
            "total_bytes": sum(len(c.encode("utf-8")) for c in self._files.values()),
        }

    # ------------------------------------------------------------------
    # Execution (always through the governed sandbox)
    # ------------------------------------------------------------------

    def run(self, command: str, args: list[str] | None = None) -> dict[str, Any]:
        bootstrap_paths = {bootstrap_path for bootstrap_path, _ in _WORKSPACE_BOOTSTRAP_FILES}
        agent_files = [
            path for path in self._files if path not in bootstrap_paths
        ]
        if not agent_files:
            return {
                "status": "error",
                "error": {
                    "type": "workspace_empty",
                    "message": (
                        "write at least one file under strategies/ or tests/ "
                        "before running a command"
                    ),
                },
            }
        try:
            sandbox_command = SandboxCommandV1(
                name=str(command),
                args=tuple(str(item) for item in (args or ())),
            )
        except ValueError as exc:
            return {
                "status": "error",
                "error": {
                    "type": "command_denied",
                    "message": str(exc)[:300],
                },
            }
        idempotency_key = "wsrun_" + sha256(
            (
                sha256(
                    "\n".join(
                        f"{path}:{content}" for path, content in sorted(self._files.items())
                    ).encode("utf-8")
                ).hexdigest()
                + f":{sandbox_command.name}:{sorted(sandbox_command.args)}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        request = SandboxRequestV1(
            assignment_ref=f"agent-workspace:{self._run_id}"[:300],
            context_pack_refs=(f"workspace:{self._run_id}",),
            files=dict(self._files),
            commands=(sandbox_command,),
            idempotency_key=idempotency_key,
        )
        from hypertrade.connectors.mcp_client import run_async

        try:
            sandbox_run = run_async(self._sandbox.run(self._run_id, request))
        except ValueError as exc:
            return {
                "status": "error",
                "error": {"type": "sandbox_rejected", "message": str(exc)[:300]},
            }
        command_results = [
            {
                "name": item.name,
                "status": item.status,
                "exit_code": item.exit_code,
                "duration_ms": item.duration_ms,
                "output_preview": item.output_preview[:4_000],
                "truncated": item.truncated,
            }
            for item in sandbox_run.commands
        ]
        return {
            "status": "ok",
            "sandbox_run_id": sandbox_run.sandbox_run_id,
            "sandbox_status": sandbox_run.status,
            "commands": command_results,
            "artifacts": [
                {"kind": item.kind, "path": item.path, "content_hash": item.content_hash[:16]}
                for item in sandbox_run.artifacts[:16]
            ],
            "note": (
                "Executed inside the governed sandbox: no network, whitelisted "
                "commands, resource limits; identical content replays the same run."
            ),
        }
