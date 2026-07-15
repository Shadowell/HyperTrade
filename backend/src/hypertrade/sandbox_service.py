"""Dedicated Unix-socket process for production strategy sandbox commands.

The Compose service running this module has no network, Docker socket, provider
credentials or BitPro mount. It receives an already validated file map over a
local UDS, validates it again, then creates one disposable workspace per fixed
command. The API process never executes candidate code in production.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import Field

from hypertrade.runtime.adapters.sandbox import (
    _execute_local_command,
    _validate_files,
    _write_guard,
)
from hypertrade.runtime.domain.models import StrictModel
from hypertrade.runtime.domain.sandbox import SandboxCommandResultV1, SandboxCommandV1

_DEFAULT_SOCKET = "/run/hypertrade-sandbox/runner.sock"
_MAX_TIMEOUT_SECONDS = 60.0


class SandboxBrokerCommandV1(StrictModel):
    """One IPC command; the image digest binds API and isolated service."""

    image_digest: str = Field(min_length=16, max_length=256)
    files: dict[str, str] = Field(min_length=1, max_length=32)
    command: SandboxCommandV1
    timeout_seconds: float = Field(gt=0, le=_MAX_TIMEOUT_SECONDS)


def execute_sandbox_command(
    request: SandboxBrokerCommandV1,
    *,
    expected_image_digest: str,
) -> SandboxCommandResultV1:
    """Revalidate and run one fixed command in a new non-persistent workspace."""

    if not expected_image_digest or request.image_digest != expected_image_digest:
        raise ValueError("sandbox image digest does not match the reviewed service")
    files = _validate_files(request.files)
    with tempfile.TemporaryDirectory(prefix="hypertrade-sandbox-", dir="/tmp") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        guard = root / "guard"
        workspace.mkdir(mode=0o700)
        guard.mkdir(mode=0o700)
        _write_guard(guard)
        for relative, content in files.items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return _execute_local_command(request.command, workspace, guard, request.timeout_seconds)


def create_sandbox_app(*, expected_image_digest: str) -> FastAPI:
    app = FastAPI(title="HyperTrade Isolated Sandbox", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "hypertrade-sandbox"}

    @app.post("/v1/commands")
    def run_command(request: SandboxBrokerCommandV1) -> dict[str, object]:
        try:
            result = execute_sandbox_command(
                request,
                expected_image_digest=expected_image_digest,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    return app


def main() -> None:
    socket_path = Path(os.getenv("SANDBOX_SOCKET_PATH", _DEFAULT_SOCKET))
    socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        mode = socket_path.lstat().st_mode
        if not stat.S_ISSOCK(mode):
            raise RuntimeError("sandbox socket path is not a socket")
        socket_path.unlink()
    expected_image_digest = os.getenv("SANDBOX_IMAGE_DIGEST", "").strip()
    if not expected_image_digest:
        raise RuntimeError("SANDBOX_IMAGE_DIGEST must be configured")
    uvicorn.run(
        create_sandbox_app(expected_image_digest=expected_image_digest),
        uds=str(socket_path),
        log_level="info",
    )


if __name__ == "__main__":
    main()
