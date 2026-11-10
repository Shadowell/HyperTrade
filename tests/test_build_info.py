"""Build identity: the stamp, its placeholder in git, and the endpoints that report it."""

import io
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.build_info import BuildInfo, get_build_info, read_sha
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app

PLACEHOLDER = "$Format:%H$"
SHA = "0123456789abcdef0123456789abcdef01234567"
STAMP = Path("backend/src/hypertrade/BUILD_INFO")
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

# Ignore the developer's global git configuration (hooks, signing, attribute files).
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(*args: str, cwd: Path | None = None, binary: bool = False) -> Any:
    import os

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        check=True,
    )
    return result.stdout if binary else result.stdout.decode().strip()


def test_read_sha_accepts_a_full_lowercase_sha_and_trims_whitespace(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD_INFO"
    stamp.write_text(f"  {SHA}\n\n", encoding="utf-8")
    assert read_sha(stamp) == SHA


@pytest.mark.parametrize(
    "content",
    ["", PLACEHOLDER, "abc123", SHA.upper(), SHA + "00", f"build {SHA}", "not a sha"],
)
def test_read_sha_rejects_unexpanded_or_malformed_stamps(tmp_path: Path, content: str) -> None:
    # An unexpanded placeholder is what a plain checkout contains; it must read as "unknown",
    # never as a commit the build is not.
    stamp = tmp_path / "BUILD_INFO"
    stamp.write_text(content, encoding="utf-8")
    assert read_sha(stamp) is None


def test_read_sha_of_a_missing_stamp_is_unknown(tmp_path: Path) -> None:
    assert read_sha(tmp_path / "does-not-exist") is None


def test_build_info_dict_reflects_whether_the_build_is_stamped() -> None:
    assert BuildInfo(version="1.2.3", sha=SHA).to_dict() == {
        "version": "1.2.3",
        "sha": SHA,
        "stamped": True,
    }
    assert BuildInfo(version="1.2.3", sha=None).to_dict() == {
        "version": "1.2.3",
        "sha": None,
        "stamped": False,
    }


def test_the_committed_stamp_is_the_placeholder_never_a_real_sha() -> None:
    # A real SHA committed here would make every development checkout claim to be that commit.
    assert STAMP.read_text(encoding="utf-8").strip() == PLACEHOLDER


@needs_git
def test_gitattributes_marks_the_stamp_for_archive_expansion() -> None:
    attr = _git("check-attr", "export-subst", "--", str(STAMP))
    assert attr.endswith("export-subst: set"), attr


@needs_git
def test_archive_of_a_bare_mirror_stamps_the_archived_commit(tmp_path: Path) -> None:
    # Reproduces what deploy/from-github.sh does: `git --git-dir=<bare mirror> archive <sha>`.
    # A bare repository has no working tree, so the export-subst rule must come from the
    # archived tree itself (.gitattributes is committed), not from anyone's checkout.
    source = tmp_path / "source"
    (source / STAMP.parent).mkdir(parents=True)
    shutil.copy(".gitattributes", source / ".gitattributes")
    shutil.copy(STAMP, source / STAMP)
    _git("init", "-q", cwd=source)
    _git("add", "-A", cwd=source)
    _git("commit", "-q", "-m", "release", cwd=source)
    commit = _git("rev-parse", "HEAD", cwd=source)
    mirror = tmp_path / "mirror.git"
    _git("clone", "-q", "--bare", str(source), str(mirror))

    archive = _git(f"--git-dir={mirror}", "archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        member = tar.extractfile(str(STAMP))
        assert member is not None
        stamped = member.read().decode()
    assert stamped.strip() == commit

    release = tmp_path / "release"
    release.mkdir()
    (release / "BUILD_INFO").write_text(stamped, encoding="utf-8")
    assert read_sha(release / "BUILD_INFO") == commit


def _client(monkeypatch: pytest.MonkeyPatch, info: BuildInfo) -> TestClient:
    monkeypatch.setattr("hypertrade.main.get_build_info", lambda: info)
    settings = Settings(
        ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", SESSION_SECRET="test-secret-123"
    )
    db = Database("sqlite:///:memory:")
    db.create_all()
    return TestClient(create_app(settings=settings, db=db))


@pytest.mark.parametrize("path", ["/version", "/api/version"])
def test_version_endpoint_reports_the_build_without_credentials(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    client = _client(monkeypatch, BuildInfo(version="0.2.0", sha=SHA))

    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {
        "service": "hypertrade-api",
        "version": "0.2.0",
        "sha": SHA,
        "stamped": True,
    }


def test_version_endpoint_says_unstamped_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, BuildInfo(version="0.2.0", sha=None))

    body = client.get("/api/version").json()

    assert body["sha"] is None and body["stamped"] is False


def test_healthz_carries_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, BuildInfo(version="0.2.0", sha=SHA))

    body = client.get("/healthz").json()

    assert body["build"] == {"version": "0.2.0", "sha": SHA, "stamped": True}


def test_the_running_checkout_reports_a_version_and_an_unforged_sha() -> None:
    info = get_build_info()
    assert info.version
    assert info.sha is None or len(info.sha) == 40
