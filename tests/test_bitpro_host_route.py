import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "host_route", Path(__file__).parents[1] / "deploy/bitpro_host_route.py"
)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def test_observed_network_gateway_and_invalid_docker_placeholder():
    assert (
        route.gateway_from_network(
            [{"IPAM": {"Config": [{"Gateway": "invalid IP"}, {"Gateway": "172.18.0.1"}]}}]
        )
        == "172.18.0.1"
    )
    with pytest.raises(ValueError):
        route.gateway_from_network([{"IPAM": {"Config": [{"Gateway": "invalid IP"}]}}])


def test_alias_repair_preserves_other_hosts_and_is_idempotent():
    original = "127.0.0.1 localhost\ninvalid IP\thost.docker.internal\n172.18.0.3 worker\n"
    fixed = route.replace_alias(original, "172.18.0.1")
    assert "invalid IP" not in fixed
    assert "172.18.0.3 worker" in fixed
    assert route.replace_alias(fixed, "172.18.0.1") == fixed


def test_env_update_changes_only_gateway_and_preserves_permissions(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EXAMPLE=unchanged\nBITPRO_DOCKER_HOST_GATEWAY=host-gateway\n")
    env.chmod(0o600)
    route.write_gateway_env(env, "172.18.0.1")
    assert env.read_text() == "EXAMPLE=unchanged\nBITPRO_DOCKER_HOST_GATEWAY=172.18.0.1\n"
    assert env.stat().st_mode & 0o777 == 0o600
