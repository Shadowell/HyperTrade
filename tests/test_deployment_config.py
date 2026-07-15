import re
from pathlib import Path

from hypertrade.config import Settings


def test_docker_compose_maps_host_gateway_for_bitpro_mcp() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert compose.count("host.docker.internal:host-gateway") >= 2
    for service in ("api", "worker"):
        match = re.search(
            rf"(?ms)^  {service}:\n(?P<section>.*?)(?=^  [a-zA-Z0-9_-]+:\n|^networks:|\Z)",
            compose,
        )
        assert match is not None
        section = match.group("section")
        assert "extra_hosts:" in section
        assert "host.docker.internal:host-gateway" in section


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
