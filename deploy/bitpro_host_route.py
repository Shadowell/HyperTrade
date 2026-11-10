#!/usr/bin/env python3
"""Resolve the actual Docker bridge; validate or repair the BitPro host alias."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ALIAS = "host.docker.internal"

# EX_TEMPFAIL: the alias points at the real Docker gateway, but BitPro itself did not answer its
# authenticated health check. BitPro restarts independently of a HyperTrade release, so deploy.sh
# treats this as a warning; every other non-zero status (alias mismatch, docker failure) is a
# defect of the deployment and stays fatal. deploy.sh matches this literal in its `case`.
EXIT_BITPRO_UNAVAILABLE = 75

# Runs inside the api/worker container; argv: gateway, exit status for "BitPro unavailable". The
# alias assertion is deterministic and local, so it fails hard and is never retried. Only the
# authenticated BitPro call may degrade, because the assertion above it already proved the route.
CONTAINER_PROBE = """import socket,sys,time,urllib.request
from hypertrade.config import get_settings
s=get_settings()
assert sys.argv[1] in {r[4][0] for r in socket.getaddrinfo('host.docker.internal',8889)}
q=urllib.request.Request(str(s.bitpro_mcp_api_base).rstrip('/')+'/system/health',headers={s.bitpro_mcp_auth_header:s.bitpro_mcp_api_token})
for attempt in range(15):
    try:
        with urllib.request.urlopen(q,timeout=3) as r: assert r.status==200
        break
    except Exception as exc:
        if attempt == 14:
            print('BitPro authenticated health unavailable: %r' % (exc,), file=sys.stderr)
            sys.exit(int(sys.argv[2]))
        time.sleep(2)
print('BitPro DNS and authenticated health verified')
"""


def gateway_from_network(networks):
    for network in networks:
        for config in network.get("IPAM", {}).get("Config", []):
            try:
                address = ipaddress.ip_address(config.get("Gateway", ""))
            except ValueError:
                continue
            if address.version == 4 and not (
                address.is_unspecified or address.is_loopback or address.is_multicast
            ):
                return str(address)
    raise ValueError("Docker network has no usable IPv4 host gateway")


def replace_alias(content, gateway):
    ipaddress.IPv4Address(gateway)
    lines = [line for line in content.splitlines() if ALIAS not in line.split()]
    return "\n".join([*lines, f"{gateway}\t{ALIAS}"]) + "\n"


def write_gateway_env(path, gateway):
    ipaddress.IPv4Address(gateway)
    key = "BITPRO_DOCKER_HOST_GATEWAY="
    original = path.read_text()
    content = (
        "\n".join(
            [line for line in original.splitlines() if not line.startswith(key)] + [key + gateway]
        )
        + "\n"
    )
    if original == content:
        return
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(content)
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", default="hypertrade")
    parser.add_argument("--write-env", type=Path)
    parser.add_argument("--repair-running", action="store_true")
    parser.add_argument("--check-running", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("/opt/hypertrade/data/backups"))
    args = parser.parse_args()
    raw = subprocess.check_output(["docker", "network", "inspect", args.network], text=True)
    gateway = gateway_from_network(json.loads(raw))
    if args.write_env:
        write_gateway_env(args.write_env, gateway)
    if not (args.repair_running or args.check_running):
        print(gateway)
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")  # noqa: UP017
    bitpro_unavailable = []
    for container in ("hypertrade-api", "hypertrade-worker"):
        content = subprocess.check_output(
            ["docker", "exec", container, "cat", "/etc/hosts"], text=True
        )
        desired = replace_alias(content, gateway)
        backup = None
        if args.repair_running and content != desired:
            args.backup_dir.mkdir(parents=True, exist_ok=True)
            backup = args.backup_dir / f"{container}-hosts-{stamp}.txt"
            backup.touch(mode=0o600, exist_ok=False)
            backup.write_text(content)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "python",
                    "-c",
                    "import pathlib,sys;pathlib.Path('/etc/hosts').write_text(sys.stdin.read())",
                ],
                input=desired,
                text=True,
                check=True,
            )
        result = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "python",
                "-c",
                CONTAINER_PROBE,
                gateway,
                str(EXIT_BITPRO_UNAVAILABLE),
            ],
            check=False,
        )
        # Any other failure (alias mismatch, docker error) aborts immediately, as before; only the
        # soft status is collected so the remaining container still gets its alias check.
        if result.returncode == EXIT_BITPRO_UNAVAILABLE:
            bitpro_unavailable.append(container)
        elif result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        print(
            json.dumps(
                {
                    "container": container,
                    "gateway": gateway,
                    "backup": str(backup) if backup else None,
                    "bitpro": "unavailable" if container in bitpro_unavailable else "ok",
                }
            )
        )
    if bitpro_unavailable:
        print(
            "BitPro did not answer its authenticated health check from "
            + ", ".join(bitpro_unavailable)
            + "; the host route itself is valid",
            file=sys.stderr,
        )
        sys.exit(EXIT_BITPRO_UNAVAILABLE)


if __name__ == "__main__":
    main()
