import re
import stat
import subprocess
from pathlib import Path

from hypertrade.config import Settings


def test_docker_compose_maps_host_gateway_for_bitpro_mcp() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    mapping = "host.docker.internal:${BITPRO_DOCKER_HOST_GATEWAY:-host-gateway}"
    assert compose.count(mapping) >= 2
    for service in ("api", "worker"):
        match = re.search(
            rf"(?ms)^  {service}:\n(?P<section>.*?)(?=^  [a-zA-Z0-9_-]+:\n|^networks:|\Z)",
            compose,
        )
        assert match is not None
        section = match.group("section")
        assert "extra_hosts:" in section
        assert mapping in section
    deploy = Path("deploy/deploy.sh").read_text()
    assert deploy.index("--write-env") < deploy.index("docker compose run --rm api")
    # api 走 `--wait` 健康门控（sandbox/worker 先起），两者都必须早于 --check-running 这次调用
    # （不是注释里对它的提及）。
    check_running_at = deploy.index('bitpro_host_route.py" --check-running')
    assert deploy.index("docker compose up -d sandbox worker") < check_running_at
    assert deploy.index("docker compose up -d --wait --wait-timeout 90 api") < check_running_at


def test_production_trigger_feature_is_disabled_by_default() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert Settings.model_fields["research_triggers_enabled"].default is False
    assert "RESEARCH_TRIGGERS_ENABLED=false" in env_example


def test_production_compose_mounts_codex_auth_as_an_optional_read_only_secret() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "file: ${CODEX_AUTH_SOURCE_PATH:-/dev/null}" in compose
    assert compose.count("target: hypertrade_codex_auth") == 2
    assert compose.count("CODEX_AUTH_JSON: /run/secrets/hypertrade_codex_auth") == 2
    assert "CODEX_AUTH_SOURCE_PATH=" in env_example


def test_hosted_deploy_entrypoint_is_committed_executable() -> None:
    # sshd runs this file directly as the forced command, so a 644 copy fails with
    # "Permission denied" (exit 126) before a single line of the script runs.
    script = Path("deploy/from-github.sh")
    assert script.stat().st_mode & stat.S_IXUSR, "deploy/from-github.sh must be executable"

    try:
        listed = subprocess.run(
            ["git", "ls-files", "-s", str(script)], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:  # no git binary: the filesystem check above still applies
        return
    if listed.returncode == 0 and listed.stdout.strip():
        assert listed.stdout.startswith("100755"), "commit deploy/from-github.sh as mode 100755"


def _rsync_excludes(text: str) -> set[str]:
    """Exclude patterns of the release-sync `rsync -a --delete` (the one with a filter list)."""
    block = re.search(
        r"rsync -a --delete \\\n(?P<body>(?:[ \t]*--exclude '[^']+' \\\n)+)[ \t]*\./ ", text
    )
    assert block is not None, "release-sync rsync with --exclude filters not found"
    return set(re.findall(r"--exclude '([^']+)'", block.group("body")))


def test_both_deploy_engines_share_one_rsync_protect_list() -> None:
    # `rsync --delete` removes anything on the host that is not in the repo. The hosted
    # engine's trusted mirror, lock file and root-owned entrypoint live only on the host,
    # so the self-hosted engine must protect exactly what the hosted engine protects.
    workflow = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
    hosted_script = Path("deploy/from-github.sh").read_text(encoding="utf-8")

    server_excludes = _rsync_excludes(workflow)
    hosted_excludes = _rsync_excludes(hosted_script)

    assert {
        "deploy/from-github.sh",
        "deploy/from-github.lock",
        "deploy/github.git/",
        "deploy/last_deployed_sha",
        ".env",
        "data",
    } <= server_excludes
    assert server_excludes == hosted_excludes


def test_both_deploy_engines_verify_the_running_build_against_the_shipped_commit() -> None:
    # A green deploy step only proves the host script exited 0. Asking the running API which
    # commit it serves is what catches a deploy that did not actually replace the build.
    workflow = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
    steps = re.findall(
        r"- name: Verify the deployed build\n(?P<body>(?:(?!      - name:).*\n)+)", workflow
    )
    assert len(steps) == 2, "expected one verification step per deploy engine"
    for body in steps:
        assert "EXPECTED_SHA: ${{ github.sha }}" in body
        assert "/api/version" in body and '.get("sha")' in body
        assert "exit 1" in body, "a mismatch must fail the job"


def test_self_hosted_engine_stamps_ships_verifies_and_only_then_records_the_sha() -> None:
    workflow = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
    stamp = workflow.index("- name: Stamp build identity")
    sync = workflow.index("- name: Sync release to /opt/hypertrade")
    deploy = workflow.index("- name: Deploy\n")
    verify = workflow.index("- name: Verify the deployed build")
    record = workflow.index("- name: Record deployed SHA")

    # The stamp must be in the tree before it is synced and baked into the image, and the SHA is
    # recorded as deployed only after the running API confirmed it (a mismatch is retried).
    assert stamp < sync < deploy < verify < record
    assert "backend/src/hypertrade/BUILD_INFO" in workflow[stamp:sync]
