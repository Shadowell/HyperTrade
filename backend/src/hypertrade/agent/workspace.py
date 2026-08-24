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
        self._files: dict[str, str] = {}
        self._sandbox = sandbox or StrategySandbox(
            InMemorySandboxStore(),
            command_timeout_seconds=command_timeout_seconds,
            runner=runner,
        )

    # ------------------------------------------------------------------
    # File operations (validated at write time for immediate feedback)
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        candidate = dict(self._files)
        candidate[str(path)] = str(content)
        # Full-workspace validation keeps quota and cross-file invariants honest;
        # rejections surface as structured errors so the agent can fix inline.
        try:
            validated = _validate_files(candidate)
        except ValueError as exc:
            return {
                "status": "error",
                "error": {"type": "write_rejected", "message": str(exc)[:300]},
            }
        self._files = validated
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
        if not self._files:
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
