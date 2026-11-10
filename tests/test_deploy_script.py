"""Run the real deploy/deploy.sh against fake binaries to pin how it reacts to the BitPro check.

deploy.sh needs root, Docker, nginx and /opt/hypertrade, so the script is copied with its three
host path prefixes pointed into tmp_path and every external command is a shim that only logs its
arguments. What is exercised is the script's own control flow: which exit status of
`bitpro_host_route.py --check-running` still aborts the deploy, and which does not.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / "deploy"

_spec = importlib.util.spec_from_file_location("host_route", DEPLOY_DIR / "bitpro_host_route.py")
route = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(route)

# Every absolute host path deploy.sh touches, and where the sandbox puts it instead.
HOST_PATHS = {
    "/opt/hypertrade": "opt/hypertrade",
    "/usr/local/bin": "usr/local/bin",
    "/etc/nginx": "etc/nginx",
}

SHIM = '#!/usr/bin/env bash\nprintf \'%s %s\\n\' "$(basename "$0")" "$*" >> "$CALLS_LOG"\n'
DOCKER_SHIM = SHIM + '[ "$1 $2" = "image inspect" ] && echo "sha256:fake"\nexit 0\n'
FAKE_ROUTE = """\
import os
import sys

with open(os.environ["CALLS_LOG"], "a") as log:
    log.write("bitpro_host_route " + " ".join(sys.argv[1:]) + "\\n")
if "--check-running" in sys.argv:
    sys.exit(int(os.environ["FAKE_CHECK_RUNNING_EXIT"]))
"""


def _run_deploy(tmp_path: Path, check_running_exit: int) -> tuple[subprocess.CompletedProcess, str]:
    script = (DEPLOY_DIR / "deploy.sh").read_text(encoding="utf-8")
    stray = {
        path
        for path in re.findall(
            r"(?<![\w$.{}:/-])/(?:opt|etc|usr|var|srv|home|root|run)\b[\w./-]*",
            script.split("\n", 1)[1],  # the shebang is not a path the script touches
        )
        if not path.startswith(tuple(HOST_PATHS))
    }
    assert not stray, f"deploy.sh now touches {sorted(stray)}: map them in HOST_PATHS"
    for host, local in HOST_PATHS.items():
        script = script.replace(host, str(tmp_path / local))

    root = tmp_path / HOST_PATHS["/opt/hypertrade"]
    (root / "deploy").mkdir(parents=True)
    (root / ".env").write_text("EXISTING=1\n", encoding="utf-8")
    for name in ("hypertrade-host-cli", "hypertrade.nginx"):
        (root / "deploy" / name).write_bytes((DEPLOY_DIR / name).read_bytes())
    (root / "deploy" / "bitpro_host_route.py").write_text(FAKE_ROUTE, encoding="utf-8")
    for host_dir in ("usr/local/bin", "etc/nginx/sites-available", "etc/nginx/sites-enabled"):
        (tmp_path / host_dir).mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "nginx", "systemctl", "chown", "curl"):
        shim = bin_dir / name
        shim.write_text(DOCKER_SHIM if name == "docker" else SHIM, encoding="utf-8")
        shim.chmod(0o755)
    runner = tmp_path / "deploy.sh"
    runner.write_text(script, encoding="utf-8")

    calls_log = tmp_path / "calls.log"
    calls_log.touch()
    result = subprocess.run(
        ["bash", str(runner)],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CALLS_LOG": str(calls_log),
            "FAKE_CHECK_RUNNING_EXIT": str(check_running_exit),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    return result, calls_log.read_text(encoding="utf-8")


def _later_steps_ran(tmp_path: Path, calls: str) -> bool:
    host_cli = tmp_path / "usr/local/bin/hypertrade"
    nginx_reloaded = "systemctl reload nginx" in calls
    assert host_cli.exists() == nginx_reloaded, "host CLI and nginx steps go together"
    return nginx_reloaded


def test_a_healthy_bitpro_runs_every_step_without_a_warning(tmp_path: Path) -> None:
    result, calls = _run_deploy(tmp_path, 0)

    assert result.returncode == 0, result.stderr
    assert _later_steps_ran(tmp_path, calls)
    assert "[deploy] health ok" in result.stdout
    assert "::warning" not in result.stdout
    assert "bitpro_host_route --check-running" in calls


def test_bitpro_unavailable_warns_and_still_finishes_the_deploy(tmp_path: Path) -> None:
    # The 75 comes from the helper itself, so a drift between its constant and the script's
    # `case` shows up here as a failed deploy instead of passing silently.
    result, calls = _run_deploy(tmp_path, route.EXIT_BITPRO_UNAVAILABLE)

    assert result.returncode == 0, result.stderr
    assert _later_steps_ran(tmp_path, calls)
    assert "[deploy] health ok" in result.stdout
    warning = result.stdout.index("::warning title=BitPro not ready after deploy::")
    assert warning < result.stdout.index("[deploy] installing host cli wrapper")


@pytest.mark.parametrize("status", [1, 2, 127])
def test_a_route_defect_still_aborts_before_the_later_steps(tmp_path: Path, status: int) -> None:
    result, calls = _run_deploy(tmp_path, status)

    assert result.returncode == status
    assert not _later_steps_ran(tmp_path, calls)
    assert "[deploy] health ok" not in result.stdout
    assert "::warning" not in result.stdout
