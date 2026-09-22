"""Frozen multi-task process evaluation built from isolated paired ARC journals.

The batch result is a rebuildable view. Pair manifests and journals remain the
authority for controls, spending, and completion; no Paper or Live path exists here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.self_test import ARCSelfTestService
from hypertrade.evals.memory_ablation import _digest, _lock, _write, create_pair, run_pair
from hypertrade.providers.chat import ChatProvider, ChatResponse

_TASK_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
_CONTROL_EXCEPTIONS = {"objective", "symbols", "timeframes"}


def _batch_runtime_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class _StatusProvider:
    """Identity-only provider for journal inspection; dispatch remains impossible."""

    def __init__(self, name: str, model: str) -> None:
        self.name, self.model = name, model

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatResponse:
        raise RuntimeError("status_cannot_dispatch_model")


def _task_goal(value: Any) -> ARCGoalV1:
    return value if isinstance(value, ARCGoalV1) else ARCGoalV1.model_validate(value)


def _common_controls(goal: ARCGoalV1) -> dict[str, Any]:
    return {
        key: value
        for key, value in goal.model_dump(mode="json").items()
        if key not in _CONTROL_EXCEPTIONS
    }


def create_batch(directory: Path, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Freeze a bounded task matrix without dispatching a provider or a tool."""
    if not 2 <= len(tasks) <= 50:
        raise ValueError("batch_task_count_out_of_range")
    parsed: list[tuple[str, ARCGoalV1, list[dict[str, Any]], str | None]] = []
    seen: set[str] = set()
    common: dict[str, Any] | None = None
    for task in tasks:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("invalid_task_id")
        if task_id in seen:
            raise ValueError("duplicate_task_id")
        seen.add(task_id)
        goal = _task_goal(task["goal"])
        controls = _common_controls(goal)
        if common is None:
            common = controls
        elif controls != common:
            raise ValueError("batch_control_mismatch")
        records = task["records"]
        if not isinstance(records, list):
            raise ValueError("invalid_task_records")
        parsed.append((task_id, goal, records, task.get("cost_policy_hash")))
    assert common is not None
    with _lock(directory):
        identity_path = directory / "batch_identity.json"
        if identity_path.exists():
            identity = json.loads(identity_path.read_text())
            execution_id = identity.get("execution_id")
            if (
                identity.get("schema_version") != "research_memory_batch_identity.v1"
                or not isinstance(execution_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", execution_id)
            ):
                raise ValueError("invalid_batch_execution_identity")
        else:
            if (directory / "batch_manifest.json").exists():
                raise ValueError("batch_execution_identity_missing")
            execution_id = uuid.uuid4().hex
            _write(
                identity_path,
                {
                    "schema_version": "research_memory_batch_identity.v1",
                    "execution_id": execution_id,
                },
            )
        pair_entries = []
        for task_id, goal, records, cost_hash in parsed:
            pair_dir = directory / "pairs" / task_id
            if pair_dir.is_symlink():
                raise ValueError("pair_directory_symlink")
            scope = f"batch:{execution_id}:{task_id}"
            pair = create_pair(
                pair_dir, goal, records, cost_policy_hash=cost_hash, scope=scope
            )
            pair_entries.append(
                {"task_id": task_id, "pair_id": pair["pair_id"], "scope": scope}
            )
        frozen = {
            "schema_version": "research_memory_batch.v1",
            "execution_id": execution_id,
            "common_controls": common,
            "runtime_digest": _batch_runtime_digest(),
            "tasks": pair_entries,
        }
        manifest = {**frozen, "batch_id": _digest(frozen)}
        path = directory / "batch_manifest.json"
        if path.exists():
            if json.loads(path.read_text()) != manifest:
                raise ValueError("batch_directory_already_bound")
        else:
            _write(path, manifest)
        return manifest


def _aggregate(manifest: dict[str, Any], pairs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    complete = len(pairs) == len(manifest["tasks"]) and all(
        pair["status"] == "complete" for pair in pairs.values()
    )
    metrics: dict[str, Any] = {}
    paired_outcomes = {"improved": 0, "regressed": 0, "unchanged": 0, "unknown": 0}
    unknown = {"multi_pair_process_only", "effectiveness_not_established"}
    for task in manifest["tasks"]:
        pair = pairs.get(task["task_id"])
        if pair is None or pair["status"] != "complete":
            paired_outcomes["unknown"] += 1
            continue
        on, off = pair["arms"]["on"], pair["arms"]["off"]
        if any("pending_effect_or_model" in arm["unknown"] for arm in (on, off)):
            paired_outcomes["unknown"] += 1
            continue
        on_validated = on["state"] == "paper_review_ready"
        off_validated = off["state"] == "paper_review_ready"
        outcome = (
            "improved" if on_validated and not off_validated else
            "regressed" if off_validated and not on_validated else "unchanged"
        )
        paired_outcomes[outcome] += 1
    for arm in ("on", "off"):
        observations = [
            pair["arms"][arm] for pair in pairs.values() if arm in pair["arms"]
        ]
        successes = sum(item["state"] == "paper_review_ready" for item in observations)
        failures: dict[str, int] = {}
        for item in observations:
            if item["state"] != "paper_review_ready":
                reasons = item["failure_reasons"] or ["unknown_failure"]
                for reason in set(reasons):
                    failures[reason] = failures.get(reason, 0) + 1
            unknown.update(item["unknown"])
        development_count = sum(item["development_experiments"] for item in observations)
        repeats = sum(item["repeated_experiments"] for item in observations)
        tokens_known = all(item["total_tokens"] is not None for item in observations)
        metrics[arm] = {
            "observed_tasks": len(observations),
            "expected_tasks": len(manifest["tasks"]),
            "validated_tasks": successes,
            "success_rate": successes / len(observations) if complete else None,
            "failure_classes": dict(sorted(failures.items())),
            "model_calls_used": sum(item["model_calls_used"] for item in observations),
            "tool_calls_used": sum(item["tool_calls_used"] for item in observations),
            "backtests_used": sum(item["backtests_used"] for item in observations),
            "candidates_used": sum(item["candidates_used"] for item in observations),
            "total_tokens": (
                sum(item["total_tokens"] for item in observations) if tokens_known else None
            ),
            "development_experiments": development_count,
            "repeated_experiments": repeats,
            "repeat_rate": repeats / development_count if development_count else None,
        }
        if not tokens_known:
            unknown.add("provider_usage_unreported")
        if development_count == 0:
            unknown.add("repeat_rate_denominator_missing")
    for pair in pairs.values():
        unknown.update(
            item for item in pair["unknown"] if item != "single_pair_not_effectiveness_evidence"
        )
    if not complete:
        unknown.add("incomplete_task_matrix")
    return {
        "batch_id": manifest["batch_id"],
        "status": "complete" if complete else "pending",
        "pairs": pairs,
        "paired_outcomes": paired_outcomes,
        "metrics": metrics,
        "conclusion": "unknown",
        "profitability_claim": False,
        "causal_claim": False,
        "unknown": sorted(unknown),
    }


def run_batch(
    directory: Path,
    *,
    provider: ChatProvider | None = None,
    experiments: ARCSelfTestService | None = None,
    max_pairs: int = 50,
) -> dict[str, Any]:
    """Resume uncompleted pairs; each pair's journal, not batch_result, decides work."""
    if max_pairs < 0:
        raise ValueError("invalid_max_pairs")
    with _lock(directory):
        manifest = json.loads((directory / "batch_manifest.json").read_text())
        frozen = {key: value for key, value in manifest.items() if key != "batch_id"}
        task_ids = [task["task_id"] for task in manifest["tasks"]]
        if (
            manifest.get("schema_version") != "research_memory_batch.v1"
            or _digest(frozen) != manifest["batch_id"]
            or not 2 <= len(task_ids) <= 50
            or len(task_ids) != len(set(task_ids))
        ):
            raise ValueError("batch_manifest_identity_mismatch")
        if manifest["runtime_digest"] != _batch_runtime_digest():
            raise ValueError("batch_runtime_identity_mismatch")
        identity = json.loads((directory / "batch_identity.json").read_text())
        if identity.get("execution_id") != manifest["execution_id"]:
            raise ValueError("batch_execution_identity_mismatch")
        if max_pairs == 0 and provider is None:
            controls = manifest["common_controls"]
            provider = _StatusProvider(controls["provider_name"], controls["model_name"])
        pairs: dict[str, dict[str, Any]] = {}
        for entry in manifest["tasks"]:
            task_id = entry["task_id"]
            if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
                raise ValueError("batch_manifest_identity_mismatch")
            pair_dir = directory / "pairs" / task_id
            if pair_dir.is_symlink():
                raise ValueError("pair_directory_symlink")
            pair_manifest = json.loads((pair_dir / "manifest.json").read_text())
            if (
                pair_manifest["pair_id"] != entry["pair_id"]
                or pair_manifest.get("scope") != entry["scope"]
                or entry["scope"]
                != f"batch:{manifest['execution_id']}:{task_id}"
                or _common_controls(ARCGoalV1.model_validate(pair_manifest["controls"]))
                != manifest["common_controls"]
            ):
                raise ValueError("batch_pair_identity_mismatch")
        for entry in manifest["tasks"]:
            pair_dir = directory / "pairs" / entry["task_id"]
            current = run_pair(pair_dir, provider=provider, experiments=experiments, max_arms=0)
            if current["status"] != "complete" and max_pairs:
                current = run_pair(pair_dir, provider=provider, experiments=experiments)
                max_pairs -= 1
            pairs[entry["task_id"]] = current
        result = _aggregate(manifest, pairs)
        _write(directory / "batch_result.json", result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "run", "status"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tasks", type=Path, help="JSON list of task_id, goal, records")
    args = parser.parse_args()
    if args.action == "create":
        if args.tasks is None:
            parser.error("create requires --tasks")
        result = create_batch(args.directory, json.loads(args.tasks.read_text()))
    elif args.action == "run":
        result = run_batch(args.directory)
    else:
        result = run_batch(args.directory, max_pairs=0)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
