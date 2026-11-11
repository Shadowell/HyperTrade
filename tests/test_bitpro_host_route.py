import importlib.util
import json
import socket
import subprocess
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

import hypertrade.config as app_config
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


SOFT = route.EXIT_BITPRO_UNAVAILABLE
GATEWAY = "172.18.0.1"


def _run_main(monkeypatch, capsys, probe_status):
    """Run `--check-running` against a fake docker; `probe_status` maps container -> exit code."""
    calls = []

    def check_output(argv, **_):
        calls.append(list(argv))
        if argv[:3] == ["docker", "network", "inspect"]:
            return json.dumps([{"IPAM": {"Config": [{"Gateway": GATEWAY}]}}])
        return f"127.0.0.1 localhost\n{GATEWAY}\thost.docker.internal\n"  # cat /etc/hosts

    def run(argv, **_):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, probe_status[argv[2]])

    monkeypatch.setattr(route.subprocess, "check_output", check_output)
    monkeypatch.setattr(route.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["bitpro_host_route.py", "--check-running"])
    return calls


def _probed(calls):
    return [call[2] for call in calls if call[:2] == ["docker", "exec"] and "-c" in call]


def test_check_running_passes_when_bitpro_answers(monkeypatch, capsys):
    _run_main(monkeypatch, capsys, {"hypertrade-api": 0, "hypertrade-worker": 0})
    route.main()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(row["container"], row["bitpro"]) for row in rows] == [
        ("hypertrade-api", "ok"),
        ("hypertrade-worker", "ok"),
    ]


def test_bitpro_unavailable_is_the_soft_status_and_never_skips_the_other_container(
    monkeypatch, capsys
):
    # The api container reports BitPro unavailable; the worker still has to get its alias check,
    # so the soft status is raised only after every container was probed.
    calls = _run_main(monkeypatch, capsys, {"hypertrade-api": SOFT, "hypertrade-worker": 0})
    with pytest.raises(SystemExit) as exit_info:
        route.main()
    assert exit_info.value.code == SOFT
    assert _probed(calls) == ["hypertrade-api", "hypertrade-worker"]
    captured = capsys.readouterr()
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert [(row["container"], row["bitpro"]) for row in rows] == [
        ("hypertrade-api", "unavailable"),
        ("hypertrade-worker", "ok"),
    ]
    assert "hypertrade-api" in captured.err


def test_alias_failure_stays_fatal_even_after_a_soft_failure(monkeypatch, capsys):
    _run_main(monkeypatch, capsys, {"hypertrade-api": SOFT, "hypertrade-worker": 1})
    with pytest.raises(subprocess.CalledProcessError) as error:
        route.main()
    assert error.value.returncode == 1


def test_alias_failure_in_the_first_container_is_fatal(monkeypatch, capsys):
    _run_main(monkeypatch, capsys, {"hypertrade-api": 1, "hypertrade-worker": 0})
    with pytest.raises(subprocess.CalledProcessError):
        route.main()


def test_probe_is_told_the_gateway_and_which_exit_status_means_bitpro_unavailable(
    monkeypatch, capsys
):
    calls = _run_main(monkeypatch, capsys, {"hypertrade-api": 0, "hypertrade-worker": 0})
    route.main()
    probes = [call for call in calls if "-c" in call and call[:2] == ["docker", "exec"]]
    assert probes
    for call in probes:
        assert call[-3:] == [route.CONTAINER_PROBE, GATEWAY, str(SOFT)]


class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _probe(monkeypatch, *, resolved, outcomes):
    """Prepare CONTAINER_PROBE to run in-process with the network and the clock faked out.

    `outcomes` is consumed one per urlopen call: an int is an HTTP status, an exception is raised.
    """
    queue = list(outcomes)
    state = types.SimpleNamespace(requests=[], sleeps=[], run=None)

    def urlopen(request, timeout):
        state.requests.append(request)
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)

    def settings():
        return types.SimpleNamespace(
            bitpro_mcp_api_base="http://host.docker.internal:8889/api/v2/",
            bitpro_mcp_auth_header="X-BitPro-MCP-Token",
            bitpro_mcp_api_token="test-token",
        )

    monkeypatch.setattr(app_config, "get_settings", settings)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", (ip, port)) for ip in resolved]
    )
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(time, "sleep", state.sleeps.append)
    monkeypatch.setattr(sys, "argv", ["-c", GATEWAY, str(SOFT)])
    code = compile(route.CONTAINER_PROBE, "<container-probe>", "exec")
    state.run = lambda: exec(code, {"__name__": "__probe__"})
    return state


def test_probe_stops_retrying_at_the_first_healthy_answer(monkeypatch, capsys):
    probe = _probe(monkeypatch, resolved=[GATEWAY], outcomes=[200])
    probe.run()
    assert len(probe.requests) == 1 and probe.sleeps == []
    assert probe.requests[0].full_url == "http://host.docker.internal:8889/api/v2/system/health"
    assert "verified" in capsys.readouterr().out


def test_probe_rides_out_a_bitpro_restart(monkeypatch, capsys):
    refused = OSError(111, "Connection refused")
    probe = _probe(monkeypatch, resolved=[GATEWAY], outcomes=[refused, refused, 503, 200])
    probe.run()
    assert len(probe.requests) == 4 and probe.sleeps == [2, 2, 2]


@pytest.mark.parametrize(
    "failure",
    [
        OSError(111, "Connection refused"),
        urllib.error.HTTPError("http://bitpro/system/health", 503, "warming up", {}, None),
        urllib.error.HTTPError("http://bitpro/system/health", 401, "Unauthorized", {}, None),
    ],
    ids=["refused", "warming-up", "token-rejected"],
)
def test_probe_exits_with_the_soft_status_when_bitpro_never_answers(monkeypatch, capsys, failure):
    # The route is proven by the alias assertion, so a BitPro that stays silent (down, still
    # warming up, or rejecting the token) is reported, with its last error, as the soft status.
    probe = _probe(monkeypatch, resolved=[GATEWAY], outcomes=[failure] * 15)
    with pytest.raises(SystemExit) as exit_info:
        probe.run()
    assert exit_info.value.code == SOFT
    assert len(probe.requests) == 15 and len(probe.sleeps) == 14
    err = capsys.readouterr().err
    assert "BitPro authenticated health unavailable" in err and repr(failure) in err


def test_probe_alias_mismatch_is_fatal_and_never_calls_bitpro(monkeypatch):
    probe = _probe(monkeypatch, resolved=["10.0.0.9"], outcomes=[200])
    with pytest.raises(AssertionError):
        probe.run()
    assert probe.requests == []
