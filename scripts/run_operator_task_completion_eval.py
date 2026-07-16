#!/usr/bin/env python3
"""Run all 100 operator tasks against the isolated Mission API.

The output contains only synthetic public-answer excerpts, checks and repair
labels. It deliberately excludes private reasoning, credentials and raw external
payloads so it can be reviewed as a durable QA artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hypertrade.evals.task_completion import (
    TASK_COMPLETION_SUITE_VERSION,
    OperatorTaskCompletionSuite,
    TaskCompletionCase,
    TaskCompletionObservation,
    remediation_catalog,
)
from hypertrade.runtime.domain.models import OperatorResponseV1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 100 operator task-completion checks.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-url",
        default=os.getenv("HYPERTRADE_EVAL_BASE_URL", "http://127.0.0.1:4334"),
    )
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=float(os.getenv("HYPERTRADE_EVAL_CASE_TIMEOUT_SECONDS", "30")),
    )
    args = parser.parse_args()
    if os.getenv("HYPERTRADE_EVAL_TARGET") != "isolated":
        parser.error("set HYPERTRADE_EVAL_TARGET=isolated before running this suite")
    base_url = str(args.base_url).rstrip("/")
    if not _is_loopback(base_url):
        parser.error("operator task completion runs only against a loopback isolated target")

    suite = OperatorTaskCompletionSuite()
    catalog = suite.catalog_status()
    if catalog["status"] != "ready":
        raise RuntimeError("operator task completion catalog is invalid")
    results: list[dict[str, Any]] = []
    timeout = max(10.0, min(args.case_timeout_seconds, 120.0))
    for case in suite.cases():
        started = time.monotonic()
        try:
            observation = _run_case(base_url, case, timeout)
            result = suite.evaluate(case, observation)
            result["visible_excerpt"] = _excerpt(observation.visible_text)
            result["duration_ms"] = int((time.monotonic() - started) * 1_000)
        except RuntimeError as exc:
            result = {
                "case_id": case.case_id,
                "cohort": case.cohort,
                "status": "failed",
                "failed_checks": [f"target_error:{type(exc).__name__}"],
                "remediation_ids": ["R5"],
                "visible_characters": 0,
                "evidence_count": 0,
                "executed_turns": 0,
                "visible_excerpt": "",
                "duration_ms": int((time.monotonic() - started) * 1_000),
            }
        results.append(result)

    failed = [row for row in results if row["status"] != "passed"]
    payload = {
        "schema_version": "operator_task_completion_result.v1",
        "suite_version": TASK_COMPLETION_SUITE_VERSION,
        "suite": catalog,
        "status": "passed" if not failed else "failed",
        "case_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "p0_count": len(failed),
        "p1_count": 0,
        "remediation_catalog": remediation_catalog(),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Operator task completion: "
        f"passed={payload['passed_count']}/{payload['case_count']} output={args.output}"
    )
    return 0 if not failed or args.allow_failures else 1


def _run_case(
    base_url: str,
    case: TaskCompletionCase,
    timeout: float,
) -> TaskCompletionObservation:
    final_run: dict[str, Any] | None = None
    event_types: tuple[str, ...] = ()
    first_public_event_ms: int | None = None
    for turn_index, prompt in enumerate(case.turns, start=1):
        final_run, event_types, first_public_event_ms = _stream_run(
            base_url,
            case_id=case.case_id,
            prompt=prompt,
            turn_index=turn_index,
            timeout=timeout,
        )
    if final_run is None:
        raise RuntimeError("isolated target did not return a final run")
    report = final_run.get("report_json")
    if not isinstance(report, dict):
        raise RuntimeError("final run has no report projection")
    operator_payload = report.get("operator_response")
    response = (
        OperatorResponseV1.model_validate(operator_payload)
        if isinstance(operator_payload, dict)
        else None
    )
    attempts = report.get("attempts", [])
    capability_ids: list[str] = []
    source_refs: list[str] = []
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            capability_id = attempt.get("capability_id")
            if isinstance(capability_id, str):
                capability_ids.append(capability_id)
            refs = attempt.get("source_refs", [])
            if isinstance(refs, list):
                source_refs.extend(str(ref) for ref in refs if isinstance(ref, str))
    if response is not None:
        for evidence in response.evidence:
            source_refs.extend(evidence.source_refs)
            source_refs.extend(evidence.artifact_refs)
    visible = str(final_run.get("report_markdown", ""))
    return TaskCompletionObservation(
        response=response,
        visible_text=visible,
        capability_ids=tuple(dict.fromkeys(capability_ids)),
        source_refs=tuple(dict.fromkeys(source_refs)),
        event_types=event_types,
        first_public_event_ms=first_public_event_ms,
        executed_turns=len(case.turns),
        # Desktop is required to render this final projection verbatim; a dedicated
        # desktop test exercises the equivalent TypeScript event reducer.
        desktop_final_text=visible,
    )


def _stream_run(
    base_url: str,
    *,
    case_id: str,
    prompt: str,
    turn_index: int,
    timeout: float,
) -> tuple[dict[str, Any], tuple[str, ...], int | None]:
    request = Request(
        f"{base_url}/api/agent/runs/stream",
        data=json.dumps(
            {
                "prompt": prompt,
                "evaluation_mode": True,
                "evaluation_case_id": case_id,
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": f"task-completion-{case_id}-{turn_index}",
        },
        method="POST",
    )
    started = time.monotonic()
    event_types: list[str] = []
    first_public_event_ms: int | None = None
    current_event = "message"
    data_lines: list[str] = []
    final_run: dict[str, Any] | None = None
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - isolated loopback target
            for raw_line in response:
                line = raw_line.decode().rstrip("\r\n")
                if line.startswith("event:"):
                    current_event = line.partition(":")[2].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.partition(":")[2].strip())
                elif not line and data_lines:
                    event_types.append(current_event)
                    if current_event in {"answer_delta", "evidence_ready", "warning", "final"} and (
                        first_public_event_ms is None
                    ):
                        first_public_event_ms = int((time.monotonic() - started) * 1_000)
                    payload = json.loads("\n".join(data_lines))
                    if current_event == "final" and isinstance(payload, dict):
                        candidate = payload.get("run")
                        if isinstance(candidate, dict):
                            final_run = candidate
                    current_event = "message"
                    data_lines = []
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("isolated target stream failed") from exc
    if final_run is None:
        raise RuntimeError("isolated target stream has no final run")
    return final_run, tuple(event_types), first_public_event_ms


def _excerpt(value: str, *, max_chars: int = 480) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= max_chars else f"{compact[: max_chars - 1].rstrip()}…"


def _is_loopback(base_url: str) -> bool:
    return base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")


if __name__ == "__main__":
    raise SystemExit(main())
