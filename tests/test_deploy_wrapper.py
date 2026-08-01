from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "deploy" / "hypertrade-host-cli"


def test_host_cli_wrapper_runs_one_off_remote_client_container(tmp_path: Path) -> None:
    capture = tmp_path / "docker-argv.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$HYPERTRADE_TEST_DOCKER_ARGV"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HYPERTRADE_ROOT_DIR": str(tmp_path),
        "HYPERTRADE_TEST_DOCKER_ARGV": str(capture),
        "HYPERTRADE_RENDERER": "plain",
        "HYPERTRADE_TRACE": "full",
    }

    result = subprocess.run(
        ["bash", str(WRAPPER), "ask", "看下ETH行情"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = capture.read_text(encoding="utf-8").splitlines()
    assert argv[:4] == ["compose", "run", "--rm", "--no-deps"]
    assert "-e" in argv
    assert "HYPERTRADE_API_URL=http://api:3334" in argv
    assert "HYPERTRADE_RENDERER=plain" in argv
    assert "HYPERTRADE_TRACE=full" in argv
    assert argv[-4:] == ["api", "hypertrade", "ask", "看下ETH行情"]


def test_host_cli_wrapper_uses_optional_tui_image(tmp_path: Path) -> None:
    capture = tmp_path / "docker-argv.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$HYPERTRADE_TEST_DOCKER_ARGV"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HYPERTRADE_ROOT_DIR": str(tmp_path),
        "HYPERTRADE_TEST_DOCKER_ARGV": str(capture),
    }

    result = subprocess.run(
        ["bash", str(WRAPPER), "tui", "--session", "sess_1"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = capture.read_text(encoding="utf-8").splitlines()
    assert argv[-5:] == ["cli", "hypertrade", "tui", "--session", "sess_1"]
