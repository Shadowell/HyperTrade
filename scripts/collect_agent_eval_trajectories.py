#!/usr/bin/env python3
"""Collect sanitized trajectories from an isolated HyperTrade evaluation target."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hypertrade.evals.trajectory import build_trajectory_from_api_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect isolated Agent eval trajectories.")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-url",
        default=os.getenv("HYPERTRADE_EVAL_BASE_URL", "http://127.0.0.1:3334"),
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Acknowledge that the explicitly configured target is isolated but non-loopback.",
    )
    args = parser.parse_args()
    if os.getenv("HYPERTRADE_EVAL_TARGET") != "isolated":
        parser.error("set HYPERTRADE_EVAL_TARGET=isolated before collecting trajectories")
    base_url = str(args.base_url).rstrip("/")
    if not _is_loopback(base_url) and not args.allow_remote:
        parser.error("non-loopback targets require --allow-remote and must be isolated")
    references = _load_references(args.reference)
    trajectories = [
        _run_case(base_url, reference)
        for reference in references
    ]
    serialized = json.dumps(trajectories, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(serialized, encoding="utf-8")
    return 0


def _run_case(base_url: str, reference: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{base_url}/api/agent/runs",
        data=json.dumps(
            {"prompt": str(reference["prompt"]), "evaluation_mode": True}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - explicit eval target
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"case {reference['case_id']} failed: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"case {reference['case_id']} returned a non-object response")
    return build_trajectory_from_api_payload(str(reference["case_id"]), payload)


def _load_references(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("reference must contain a JSON list of objects")
    for item in payload:
        if not item.get("case_id") or not item.get("prompt"):
            raise ValueError("each reference case needs case_id and prompt")
    return [dict(item) for item in payload]


def _is_loopback(base_url: str) -> bool:
    return base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")


if __name__ == "__main__":
    raise SystemExit(main())
