from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_eval_compose_has_a_separate_runtime_boundary() -> None:
    compose = (REPO_ROOT / "docker-compose.eval.yml").read_text(encoding="utf-8")

    assert "name: hypertrade-eval" in compose
    assert "hypertrade-eval-postgres" in compose
    assert "hypertrade-eval-api" in compose
    assert "hypertrade-eval-worker" in compose
    assert "name: hypertrade-eval" in compose
    assert "/opt/hypertrade-eval/data/postgres" in compose
    assert '"127.0.0.1:${HYPERTRADE_EVAL_PORT:-4334}:3334"' in compose
    assert "profiles: [\"background\"]" in compose
    assert "host.docker.internal" not in compose
    assert "/bitpro-data" not in compose
    assert "/opt/hypertrade/data/postgres" not in compose


def test_eval_compose_disables_production_write_paths_and_uses_a_secret() -> None:
    compose = (REPO_ROOT / "docker-compose.eval.yml").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / "deploy" / "hypertrade-eval.env.example").read_text(
        encoding="utf-8"
    )

    assert 'PAPER_ENABLED: "false"' in compose
    assert 'MONITOR_SCHEDULER_ENABLED: "false"' in compose
    assert "BITPRO_MCP_API_BASE: http://127.0.0.1:9/api/v2" in compose
    assert "CODEX_AUTH_SOURCE_PATH" in compose
    assert "CODEX_AUTH_JSON=/run/secrets/hypertrade_eval_codex_auth" in env_example
    assert "ACTIVE_CHAT_PROVIDER=codex" in env_example
    assert "PAPER_ENABLED=false" in env_example
    assert "MONITOR_SCHEDULER_ENABLED=false" in env_example
    assert "BITPRO_MCP_API_BASE=http://127.0.0.1:9/api/v2" in env_example


def test_eval_deploy_script_only_manages_the_isolated_project() -> None:
    deploy = (REPO_ROOT / "deploy" / "deploy-eval.sh").read_text(encoding="utf-8")

    assert 'ROOT_DIR="${HYPERTRADE_EVAL_ROOT:-/opt/hypertrade-eval}"' in deploy
    assert "--project-name hypertrade-eval" in deploy
    assert "up -d postgres" in deploy
    assert "up -d --force-recreate api" in deploy
    assert "worker profile remains disabled" in deploy
    assert "http://127.0.0.1:${eval_port}/api/health" in deploy
    assert "--target agent-eval" in deploy
    assert (
        'EVAL_RUNNER_IMAGE="${HYPERTRADE_EVAL_RUNNER_IMAGE:-hypertrade-agent-eval:latest}"'
        in deploy
    )


def test_agent_eval_runner_is_a_separate_docker_target() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM runtime AS agent-eval" in dockerfile
    assert "RUN uv sync --frozen --no-dev --extra agent-evals" in dockerfile
    assert "FROM runtime AS production" in dockerfile
