import re
from pathlib import Path


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
