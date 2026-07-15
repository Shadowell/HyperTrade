from __future__ import annotations

import ast
import difflib
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from uuid import uuid4

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hypertrade.db import AgentSandboxArtifact, AgentSandboxImportReview, AgentSandboxRun
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.sandbox import (
    ImportReviewFactV1,
    ImportReviewV1,
    PatchManifestV1,
    SandboxArtifactV1,
    SandboxCommandResultV1,
    SandboxCommandV1,
    SandboxRequestV1,
    SandboxRunV1,
    sandbox_hash,
)

_ALLOWED_SUFFIXES = {".py", ".json", ".yaml", ".yml"}
_ALLOWED_ROOTS = {"strategies", "tests"}
_FORBIDDEN_IMPORTS = {
    "socket",
    "subprocess",
    "requests",
    "httpx",
    "urllib",
    "ftplib",
    "telnetlib",
    "paramiko",
}
_MAX_WORKSPACE_BYTES = 262_144
_MAX_OUTPUT_BYTES = 16_384


class SandboxStore(Protocol):
    async def by_key(self, idempotency_key: str) -> SandboxRunV1 | None: ...

    async def save_run(self, run: SandboxRunV1) -> SandboxRunV1: ...

    async def runs(self, mission_id: str) -> Sequence[SandboxRunV1]: ...

    async def get(self, mission_id: str, run_id: str) -> SandboxRunV1: ...

    async def review(
        self, run: SandboxRunV1, review: ImportReviewV1, actor: str
    ) -> ImportReviewFactV1: ...

    async def reviews(self, mission_id: str) -> Sequence[ImportReviewFactV1]: ...


class SandboxRunner(Protocol):
    def execute(
        self, command: SandboxCommandV1, workspace: Path, guard: Path, timeout_seconds: float
    ) -> SandboxCommandResultV1: ...


class InMemorySandboxStore:
    def __init__(self) -> None:
        self._runs: dict[str, SandboxRunV1] = {}
        self._keys: dict[str, str] = {}
        self._reviews: dict[str, ImportReviewFactV1] = {}
        self._artifacts: dict[str, tuple[SandboxArtifactV1, ...]] = {}

    async def by_key(self, idempotency_key: str) -> SandboxRunV1 | None:
        run_id = self._keys.get(idempotency_key)
        return self._runs.get(run_id) if run_id else None

    async def save_run(self, run: SandboxRunV1) -> SandboxRunV1:
        existing_id = self._keys.get(run.idempotency_key)
        if existing_id:
            existing = self._runs[existing_id]
            if existing.request_hash != run.request_hash:
                raise ValueError("sandbox idempotency key is bound to different content")
            return existing
        self._runs[run.sandbox_run_id] = run
        self._keys[run.idempotency_key] = run.sandbox_run_id
        self._artifacts[run.sandbox_run_id] = run.artifacts
        return run

    async def runs(self, mission_id: str) -> Sequence[SandboxRunV1]:
        return [row for row in self._runs.values() if row.mission_id == mission_id]

    async def get(self, mission_id: str, run_id: str) -> SandboxRunV1:
        row = self._runs.get(run_id)
        if row is None or row.mission_id != mission_id:
            raise KeyError(run_id)
        return row

    async def review(
        self, run: SandboxRunV1, review: ImportReviewV1, actor: str
    ) -> ImportReviewFactV1:
        existing = self._reviews.get(review.idempotency_key)
        if existing:
            if _review_key(existing) != _review_key(review, run):
                raise ValueError("sandbox review idempotency key is bound to different content")
            return existing
        _validate_review(run, review)
        fact = _review_fact(run, review, actor)
        self._reviews[review.idempotency_key] = fact
        return fact

    async def reviews(self, mission_id: str) -> Sequence[ImportReviewFactV1]:
        return [row for row in self._reviews.values() if row.mission_id == mission_id]


class SqlSandboxStore(InMemorySandboxStore):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        self.engine = create_async_engine(async_database_url(database_url), pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def by_key(self, idempotency_key: str) -> SandboxRunV1 | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentSandboxRun).where(AgentSandboxRun.idempotency_key == idempotency_key)
            )
            if row is None:
                return None
            return _run_from_row(row, await self._artifacts_for(session, row.id))

    async def save_run(self, run: SandboxRunV1) -> SandboxRunV1:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentSandboxRun).where(
                    AgentSandboxRun.idempotency_key == run.idempotency_key
                )
            )
            if existing is not None:
                projected = _run_from_row(existing, await self._artifacts_for(session, existing.id))
                if projected.request_hash != run.request_hash:
                    raise ValueError("sandbox idempotency key is bound to different content")
                return projected
            session.add(
                AgentSandboxRun(
                    id=run.sandbox_run_id,
                    mission_id=run.mission_id,
                    assignment_ref=run.assignment_ref,
                    context_pack_refs_json=list(run.context_pack_refs),
                    source_artifact_refs_json=list(run.source_artifact_refs),
                    status=run.status,
                    patch_json=run.patch.model_dump(mode="json"),
                    commands_json=[item.model_dump(mode="json") for item in run.commands],
                    request_hash=run.request_hash,
                    artifact_hash=run.artifact_hash,
                    idempotency_key=run.idempotency_key,
                    created_at=run.created_at,
                )
            )
            session.add_all(_artifact_rows(run))
        return run

    async def runs(self, mission_id: str) -> Sequence[SandboxRunV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentSandboxRun)
                    .where(AgentSandboxRun.mission_id == mission_id)
                    .order_by(AgentSandboxRun.created_at)
                )
            ).all()
            return [_run_from_row(row, await self._artifacts_for(session, row.id)) for row in rows]

    async def get(self, mission_id: str, run_id: str) -> SandboxRunV1:
        async with self.sessions() as session:
            row = await session.get(AgentSandboxRun, run_id)
            if row is None or row.mission_id != mission_id:
                raise KeyError(run_id)
            return _run_from_row(row, await self._artifacts_for(session, row.id))

    async def _artifacts_for(self, session: Any, run_id: str) -> list[AgentSandboxArtifact]:
        return list(
            (
                await session.scalars(
                    select(AgentSandboxArtifact)
                    .where(AgentSandboxArtifact.sandbox_run_id == run_id)
                    .order_by(AgentSandboxArtifact.id)
                )
            ).all()
        )

    async def review(
        self, run: SandboxRunV1, review: ImportReviewV1, actor: str
    ) -> ImportReviewFactV1:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentSandboxImportReview).where(
                    AgentSandboxImportReview.idempotency_key == review.idempotency_key
                )
            )
            if existing is not None:
                projected = _review_from_row(existing)
                if _review_key(projected) != _review_key(review, run):
                    raise ValueError("sandbox review idempotency key is bound to different content")
                return projected
            _validate_review(run, review)
            fact = _review_fact(run, review, actor)
            session.add(
                AgentSandboxImportReview(
                    id=fact.review_id,
                    sandbox_run_id=fact.sandbox_run_id,
                    mission_id=fact.mission_id,
                    decision=fact.decision,
                    reason=fact.reason,
                    patch_hash=fact.patch_hash,
                    artifact_hash=fact.artifact_hash,
                    target_contract=fact.target_contract,
                    actor=fact.actor,
                    idempotency_key=fact.idempotency_key,
                    external_write_performed=False,
                    created_at=fact.created_at,
                )
            )
            return fact

    async def reviews(self, mission_id: str) -> Sequence[ImportReviewFactV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentSandboxImportReview)
                    .where(AgentSandboxImportReview.mission_id == mission_id)
                    .order_by(AgentSandboxImportReview.created_at)
                )
            ).all()
            return [_review_from_row(row) for row in rows]


class StrategySandbox:
    """Ephemeral local/CI adapter; production remains flag-off without rootless isolation."""

    def __init__(
        self,
        store: SandboxStore,
        *,
        command_timeout_seconds: float = 20.0,
        production: bool = False,
        runner: SandboxRunner | None = None,
    ) -> None:
        self.store = store
        self.command_timeout_seconds = command_timeout_seconds
        self.production = production
        self.runner = runner

    async def run(self, mission_id: str, request: SandboxRequestV1) -> SandboxRunV1:
        if self.production and self.runner is None:
            raise RuntimeError(
                "strategy sandbox requires a configured rootless Docker adapter in production"
            )
        files = _validate_files(request.files)
        patch = _patch_manifest(files)
        request_hash = sandbox_hash(
            {
                "mission_id": mission_id,
                "assignment_ref": request.assignment_ref,
                "context_pack_refs": request.context_pack_refs,
                "source_artifact_refs": request.source_artifact_refs,
                "patch_hash": patch.patch_hash,
                "commands": [item.model_dump(mode="json") for item in request.commands],
            }
        )
        replay = await self.store.by_key(request.idempotency_key)
        if replay is not None:
            if replay.request_hash != request_hash:
                raise ValueError("sandbox idempotency key is bound to different content")
            return replay
        with tempfile.TemporaryDirectory(prefix="hypertrade-sandbox-") as temp:
            workspace = Path(temp) / "workspace"
            guard = Path(temp) / "guard"
            workspace.mkdir(mode=0o700)
            guard.mkdir(mode=0o700)
            _write_guard(guard)
            for relative, content in files.items():
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            results = []
            for command in request.commands:
                result = await anyio.to_thread.run_sync(
                    partial(self._execute, command, workspace, guard)
                )
                results.append(result)
                if result.status != "passed":
                    break
        status = (
            "validated"
            if len(results) == len(request.commands)
            and all(item.status == "passed" for item in results)
            else "failed"
        )
        sandbox_run_id = f"sbox_{uuid4().hex[:20]}"
        artifacts = _build_artifacts(sandbox_run_id, files, patch, results)
        artifact_hash = sandbox_hash(
            {
                "request_hash": request_hash,
                "patch": patch.model_dump(mode="json"),
                "commands": [item.model_dump(mode="json") for item in results],
                "status": status,
                # IDs bind rows to this run; content hash must remain stable
                # across equivalent runs and therefore excludes those IDs.
                "artifacts": [
                    {
                        "kind": item.kind,
                        "path": item.path,
                        "media_type": item.media_type,
                        "size_bytes": item.size_bytes,
                        "content_hash": item.content_hash,
                        "preview": item.preview,
                    }
                    for item in artifacts
                ],
            }
        )
        run = SandboxRunV1(
            sandbox_run_id=sandbox_run_id,
            mission_id=mission_id,
            assignment_ref=request.assignment_ref,
            context_pack_refs=request.context_pack_refs,
            source_artifact_refs=request.source_artifact_refs,
            status=status,
            patch=patch,
            commands=tuple(results),
            artifacts=tuple(artifacts),
            request_hash=request_hash,
            artifact_hash=artifact_hash,
            idempotency_key=request.idempotency_key,
        )
        return await self.store.save_run(run)

    def _execute(
        self, command: SandboxCommandV1, workspace: Path, guard: Path
    ) -> SandboxCommandResultV1:
        if self.runner is not None:
            return self.runner.execute(command, workspace, guard, self.command_timeout_seconds)
        argv = _command_argv(command, workspace, guard)
        started = time.monotonic()
        env = {
            "HOME": str(workspace / ".home"),
            "PATH": "",
            "PYTHONPATH": str(guard),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "HYPERTRADE_SANDBOX": "1",
            "NO_PROXY": "*",
        }
        output_file = tempfile.TemporaryFile()  # noqa: SIM115 - closed after bounded read below
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                preexec_fn=_resource_limits,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=self.command_timeout_seconds)
                status = "passed" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                exit_code = None
                status = "timeout"
                output_file.seek(0, os.SEEK_END)
                output_file.write(b"\n[TIMEOUT]")
        except (OSError, ValueError) as exc:
            if process is not None:
                _terminate_process_group(process)
            output_file.write(f"\n[DENIED] {exc}".encode())
            status = "denied"
            exit_code = None
        finally:
            output_file.seek(0, os.SEEK_END)
            output_bytes = output_file.tell()
            output_file.seek(0)
        output_hash = _hash_stream(output_file)
        output_file.seek(0)
        output = output_file.read(_MAX_OUTPUT_BYTES + 1)
        output_file.close()
        duration_ms = int((time.monotonic() - started) * 1_000)
        preview = output[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return SandboxCommandResultV1(
            name=command.name,
            argv=tuple(_public_argv(command)),
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            output_preview=preview,
            output_hash=output_hash,
            output_bytes=output_bytes,
            truncated=len(output) > _MAX_OUTPUT_BYTES,
        )


class DockerSandboxRunner:
    """Rootless Docker/OCI runner; no host Docker socket is mounted by this adapter."""

    def __init__(self, image: str) -> None:
        self.image = image.strip()

    def execute(
        self, command: SandboxCommandV1, workspace: Path, guard: Path, timeout_seconds: float
    ) -> SandboxCommandResultV1:
        docker = shutil.which("docker")
        if not docker or not self.image:
            raise RuntimeError("rootless Docker sandbox runner is unavailable")
        argv = [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--memory",
            "256m",
            "--cpus",
            "1",
            "--user",
            "65532:65532",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace,readonly",
            "--mount",
            f"type=bind,src={guard},dst=/guard,readonly",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONPATH=/guard",
            "--env",
            "HYPERTRADE_SANDBOX=1",
            self.image,
            *_container_argv(command, workspace),
        ]
        return _run_bounded_process(command, argv, timeout_seconds)


def _validate_files(files: dict[str, str]) -> dict[str, str]:
    total = 0
    validated: dict[str, str] = {}
    for raw_path, content in sorted(files.items()):
        path = PurePosixPath(raw_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] not in _ALLOWED_ROOTS
            or path.suffix not in _ALLOWED_SUFFIXES
        ):
            raise ValueError(f"sandbox path is not allowed: {raw_path}")
        if "\x00" in content:
            raise ValueError("sandbox file contains binary content")
        encoded = content.encode("utf-8")
        total += len(encoded)
        if total > _MAX_WORKSPACE_BYTES:
            raise ValueError("sandbox workspace exceeds 262144 bytes")
        if path.suffix == ".py":
            _validate_python(content, raw_path)
        validated[path.as_posix()] = content
    return validated


def _validate_python(content: str, path: str) -> None:
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError as exc:
        raise ValueError(f"invalid Python source: {path}") from exc
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        if set(names) & _FORBIDDEN_IMPORTS:
            raise ValueError(f"forbidden network/process import in {path}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec", "compile", "__import__"}
        ):
            raise ValueError(f"forbidden dynamic execution in {path}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"system", "popen", "spawn", "fork", "execv"}
        ):
            raise ValueError(f"forbidden process call in {path}")


def _patch_manifest(files: dict[str, str]) -> PatchManifestV1:
    diffs: list[str] = []
    file_hashes: dict[str, str] = {}
    total = 0
    for path, content in files.items():
        file_hashes[path] = sandbox_hash(content)
        total += len(content.encode("utf-8"))
        diffs.extend(
            difflib.unified_diff(
                [],
                content.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{path}",
            )
        )
    diff = "".join(diffs)
    patch_hash = sandbox_hash({"files": file_hashes, "diff": diff})
    return PatchManifestV1(
        patch_hash=patch_hash,
        diff_preview=diff[:65_536],
        file_hashes=file_hashes,
        total_bytes=total,
    )


def _command_argv(command: SandboxCommandV1, workspace: Path, guard: Path) -> list[str]:
    if command.name == "ruff":
        return [sys.executable, "-m", "ruff", "check", "strategies", "tests", *command.args]
    if command.name == "pytest":
        return [sys.executable, "-m", "pytest", "-q", "tests", *command.args]
    strategies = sorted((workspace / "strategies").glob("*.py"))
    if not strategies:
        raise ValueError("limited backtest requires a Python strategy file")
    return [sys.executable, str(guard / "limited_backtest.py"), str(strategies[0])]


def _container_argv(command: SandboxCommandV1, workspace: Path) -> list[str]:
    if command.name == "ruff":
        return [
            "python",
            "-m",
            "ruff",
            "check",
            "/workspace/strategies",
            "/workspace/tests",
            *command.args,
        ]
    if command.name == "pytest":
        return ["python", "-m", "pytest", "-q", "/workspace/tests", *command.args]
    strategies = sorted((workspace / "strategies").glob("*.py"))
    if not strategies:
        raise ValueError("limited backtest requires a Python strategy file")
    relative_path = strategies[0].relative_to(workspace)
    return ["python", "/guard/limited_backtest.py", f"/workspace/{relative_path}"]


def _run_bounded_process(
    command: SandboxCommandV1, argv: list[str], timeout_seconds: float
) -> SandboxCommandResultV1:
    started = time.monotonic()
    output_file = tempfile.TemporaryFile()  # noqa: SIM115 - closed after bounded read below
    process: subprocess.Popen[bytes] | None = None
    status: str
    exit_code: int | None
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            status = "passed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            status = "timeout"
            exit_code = None
            output_file.write(b"\n[TIMEOUT]")
    except (OSError, ValueError) as exc:
        if process is not None:
            _terminate_process_group(process)
        output_file.write(f"\n[DENIED] {exc}".encode())
        status = "denied"
        exit_code = None
    output_file.seek(0)
    output_bytes = output_file.seek(0, os.SEEK_END)
    output_file.seek(0)
    output_hash = _hash_stream(output_file)
    output_file.seek(0)
    output = output_file.read(_MAX_OUTPUT_BYTES + 1)
    output_file.close()
    return SandboxCommandResultV1(
        name=command.name,
        argv=tuple(_public_argv(command)),
        status=status,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1_000),
        output_preview=output[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        output_hash=output_hash,
        output_bytes=output_bytes,
        truncated=len(output) > _MAX_OUTPUT_BYTES,
    )


def _public_argv(command: SandboxCommandV1) -> list[str]:
    return [command.name, *command.args]


def _write_guard(guard: Path) -> None:
    (guard / "sitecustomize.py").write_text(
        """import os, socket, subprocess
for key in list(os.environ):
    if any(token in key.upper() for token in ('SECRET','TOKEN','PASSWORD','API_KEY','SSH')):
        os.environ.pop(key, None)
def denied(*args, **kwargs):
    raise PermissionError('sandbox network/process creation denied')
class DeniedSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        raise PermissionError('sandbox network access denied')
socket.socket = DeniedSocket
socket.create_connection = denied
subprocess.Popen = denied
""",
        encoding="utf-8",
    )
    (guard / "limited_backtest.py").write_text(
        """import importlib.util, sys
path = sys.argv[1]
spec = importlib.util.spec_from_file_location('candidate_strategy', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fn = getattr(module, 'generate_signals', None)
if not callable(fn):
    raise SystemExit('strategy must define generate_signals(prices)')
prices = [100.0, 101.0, 99.0, 102.0, 103.0]
signals = fn(prices)
if not isinstance(signals, list) or len(signals) != len(prices):
    raise SystemExit('signals must be a list aligned to prices')
if any(item not in (-1, 0, 1) for item in signals):
    raise SystemExit('signals must contain only -1, 0, 1')
print('limited_backtest: contract passed; no orders dispatched')
""",
        encoding="utf-8",
    )


def _resource_limits() -> None:
    limits: tuple[tuple[int, int], ...] = (
        (resource.RLIMIT_CPU, 10),
        (resource.RLIMIT_FSIZE, 1_048_576),
        (resource.RLIMIT_NOFILE, 32),
    )
    if hasattr(resource, "RLIMIT_NPROC"):
        limits += ((resource.RLIMIT_NPROC, 32),)
    for kind, requested in limits:
        try:
            _, hard = resource.getrlimit(kind)
            bounded = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(kind, (bounded, hard))
        except (OSError, ValueError):
            # Platform kernels differ; wall timeout/output/workspace limits remain mandatory.
            continue


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Kill the whole command group so timed-out descendants cannot linger."""

    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
    with suppress(OSError, subprocess.TimeoutExpired):
        process.wait(timeout=1)


def _hash_stream(stream: Any) -> str:
    digest = sha256()
    while chunk := stream.read(65_536):
        digest.update(chunk)
    return digest.hexdigest()


def _build_artifacts(
    sandbox_run_id: str,
    files: dict[str, str],
    patch: PatchManifestV1,
    commands: Sequence[SandboxCommandResultV1],
) -> list[SandboxArtifactV1]:
    artifacts: list[SandboxArtifactV1] = []

    def add(
        kind: str, path: str, media_type: str, size: int, content_hash: str, preview: str = ""
    ) -> None:
        artifact_key = {"run": sandbox_run_id, "kind": kind, "path": path, "hash": content_hash}
        artifact_id = f"sart_{sandbox_hash(artifact_key)[:20]}"
        artifacts.append(
            SandboxArtifactV1(
                artifact_id=artifact_id,
                sandbox_run_id=sandbox_run_id,
                kind=kind,
                path=path,
                media_type=media_type,
                size_bytes=size,
                content_hash=content_hash,
                preview=preview,
            )
        )

    for path, content in sorted(files.items()):
        add(
            "source_file",
            path,
            "text/plain" if not path.endswith(".py") else "text/x-python",
            len(content.encode()),
            sandbox_hash(content),
            content[:16_384],
        )
    add(
        "patch",
        "patch.diff",
        "text/x-diff",
        patch.total_bytes,
        patch.patch_hash,
        patch.diff_preview,
    )
    for index, command in enumerate(commands):
        add(
            "command_output",
            f"command/{index}/{command.name}.log",
            "text/plain",
            command.output_bytes,
            command.output_hash,
            command.output_preview,
        )
    manifest_hash = sandbox_hash(
        {
            "patch": patch.model_dump(mode="json"),
            "commands": [c.model_dump(mode="json") for c in commands],
        }
    )
    add("manifest", "manifest.json", "application/json", 0, manifest_hash)
    return artifacts


def _artifact_rows(run: SandboxRunV1) -> list[AgentSandboxArtifact]:
    return [
        AgentSandboxArtifact(
            id=artifact.artifact_id,
            sandbox_run_id=run.sandbox_run_id,
            mission_id=run.mission_id,
            kind=artifact.kind,
            path=artifact.path,
            media_type=artifact.media_type,
            size_bytes=artifact.size_bytes,
            content_hash=artifact.content_hash,
            preview=artifact.preview,
        )
        for artifact in run.artifacts
    ]


def _validate_review(run: SandboxRunV1, review: ImportReviewV1) -> None:
    if run.status != "validated" and review.decision == "accept":
        raise ValueError("only a validated sandbox run can be accepted")
    if review.patch_hash != run.patch.patch_hash or review.artifact_hash != run.artifact_hash:
        raise ValueError("import review hash mismatch")


def _review_fact(run: SandboxRunV1, review: ImportReviewV1, actor: str) -> ImportReviewFactV1:
    return ImportReviewFactV1(
        review_id=f"srev_{uuid4().hex[:20]}",
        sandbox_run_id=run.sandbox_run_id,
        mission_id=run.mission_id,
        decision=review.decision,
        reason=review.reason,
        patch_hash=review.patch_hash,
        artifact_hash=review.artifact_hash,
        target_contract=review.target_contract,
        actor=actor,
        idempotency_key=review.idempotency_key,
        external_write_performed=False,
    )


def _run_from_row(
    row: AgentSandboxRun, artifacts: Sequence[AgentSandboxArtifact] = ()
) -> SandboxRunV1:
    return SandboxRunV1(
        sandbox_run_id=row.id,
        mission_id=row.mission_id,
        assignment_ref=row.assignment_ref,
        context_pack_refs=tuple(row.context_pack_refs_json),
        source_artifact_refs=tuple(row.source_artifact_refs_json),
        status=row.status,
        patch=PatchManifestV1.model_validate(row.patch_json),
        commands=tuple(SandboxCommandResultV1.model_validate(item) for item in row.commands_json),
        artifacts=tuple(
            SandboxArtifactV1(
                artifact_id=item.id,
                sandbox_run_id=item.sandbox_run_id,
                kind=item.kind,
                path=item.path,
                media_type=item.media_type,
                size_bytes=item.size_bytes,
                content_hash=item.content_hash,
                preview=item.preview,
            )
            for item in artifacts
        ),
        request_hash=row.request_hash,
        artifact_hash=row.artifact_hash,
        idempotency_key=row.idempotency_key,
        created_at=_aware(row.created_at),
    )


def _review_from_row(row: AgentSandboxImportReview) -> ImportReviewFactV1:
    return ImportReviewFactV1(
        review_id=row.id,
        sandbox_run_id=row.sandbox_run_id,
        mission_id=row.mission_id,
        decision=row.decision,
        reason=row.reason,
        patch_hash=row.patch_hash,
        artifact_hash=row.artifact_hash,
        target_contract=row.target_contract,
        actor=row.actor,
        idempotency_key=row.idempotency_key,
        external_write_performed=False,
        created_at=_aware(row.created_at),
    )


def _review_key(
    value: ImportReviewFactV1 | ImportReviewV1, run: SandboxRunV1 | None = None
) -> tuple[str, ...]:
    if isinstance(value, ImportReviewFactV1):
        return (
            value.sandbox_run_id,
            value.mission_id,
            value.decision,
            value.reason,
            value.patch_hash,
            value.artifact_hash,
            value.target_contract,
        )
    if run is None:
        raise ValueError("sandbox review run is required")
    return (
        run.sandbox_run_id,
        run.mission_id,
        value.decision,
        value.reason,
        value.patch_hash,
        value.artifact_hash,
        value.target_contract,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
