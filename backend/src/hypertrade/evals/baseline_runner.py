"""CLI runner for a prompt-free Agent-evaluation baseline report."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from hypertrade.evals.baseline import build_baseline_report
from hypertrade.evals.ragas_runner import score_trajectories


def _load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"Expected a JSON list of objects: {path}")
    return [dict(item) for item in payload]


async def build_report(
    references: list[dict[str, Any]], trajectories: list[dict[str, Any]]
) -> dict[str, Any]:
    ragas_results = await score_trajectories(references, trajectories)
    return build_baseline_report(references, trajectories, ragas_results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated Agent evaluation baseline.")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--trajectories", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    references = _load_records(args.reference)
    trajectories = _load_records(args.trajectories)
    report = asyncio.run(build_report(references, trajectories))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
