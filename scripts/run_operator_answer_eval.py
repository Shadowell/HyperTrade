#!/usr/bin/env python3
"""Run privacy-safe public-answer checks against an isolated Agent target."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hypertrade.evals.operator_answer import (
    OperatorAnswerEvalSuite,
    OperatorAnswerObservation,
)
from hypertrade.runtime.domain.models import OperatorResponseV1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate public Agent answers on an isolated target."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-url",
        default=os.getenv("HYPERTRADE_EVAL_BASE_URL", "http://127.0.0.1:3334"),
    )
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=float(os.getenv("HYPERTRADE_EVAL_CASE_TIMEOUT_SECONDS", "300")),
    )
    args = parser.parse_args()
    if os.getenv("HYPERTRADE_EVAL_TARGET") != "isolated":
        parser.error("set HYPERTRADE_EVAL_TARGET=isolated before evaluating answers")
    base_url = str(args.base_url).rstrip("/")
    if not _is_loopback(base_url) and not args.allow_remote:
        parser.error("non-loopback targets require --allow-remote and must be isolated")

    suite = OperatorAnswerEvalSuite()
    results: list[dict[str, Any]] = []
    for case in suite.cases():
        if len(case.turns) != 1:
            results.append(
                {
                    "case_id": case.case_id,
                    "cohort": case.cohort,
                    "status": "not_supported",
                    "failed_checks": ["conversation_context_api"],
                }
            )
            continue
        try:
            observation = _run_case(
                base_url,
                prompt=case.turns[0],
                needs_stream=bool(case.required_event_types),
                timeout_seconds=args.case_timeout_seconds,
            )
            result = suite.evaluate(case, observation)
        except RuntimeError as exc:
            result = {
                "case_id": case.case_id,
                "cohort": case.cohort,
                "status": "failed",
                "failed_checks": [f"target_error:{type(exc).__name__}"],
            }
        results.append(result)

    passed = sum(row["status"] == "passed" for row in results)
    not_supported = sum(row["status"] == "not_supported" for row in results)
    payload = {
        "schema_version": "operator_answer_eval_result.v1",
        "suite": suite.catalog_status(),
        "status": "passed" if passed == len(results) else "incomplete",
        "case_count": len(results),
        "passed_count": passed,
        "not_supported_count": not_supported,
        # The artifact stores only checks and aggregate sizes, never prompts,
        # final text, tool arguments, raw results, reasoning, or credentials.
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Operator answer eval: passed={passed}/{len(results)} "
        f"not_supported={not_supported} output={args.output}"
    )
    return 0 if payload["status"] == "passed" else 1


def _run_case(
    base_url: str,
    *,
    prompt: str,
    needs_stream: bool,
    timeout_seconds: float,
) -> OperatorAnswerObservation:
    timeout = max(30.0, min(timeout_seconds, 600.0))
    if needs_stream:
        run, event_types, first_public_event_ms = _stream_run(base_url, prompt, timeout)
    else:
        run = _post_json(base_url, "/api/agent/runs", prompt, timeout)
        event_types = ()
        first_public_event_ms = None
    report = run.get("report_json") if isinstance(run, dict) else None
    response_payload = report.get("operator_response") if isinstance(report, dict) else None
    response = (
        OperatorResponseV1.model_validate(response_payload)
        if isinstance(response_payload, dict)
        else None
    )
    return OperatorAnswerObservation(
        response=response,
        visible_text=str(run.get("report_markdown", "")) if isinstance(run, dict) else "",
        event_types=event_types,
        first_public_event_ms=first_public_event_ms,
    )


def _post_json(base_url: str, path: str, prompt: str, timeout: float) -> dict[str, Any]:
    request = _request(base_url, path, prompt)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - guarded isolated target
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("isolated target request failed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("isolated target returned a non-object response")
    return payload


def _stream_run(
    base_url: str,
    prompt: str,
    timeout: float,
) -> tuple[dict[str, Any], tuple[str, ...], int | None]:
    request = _request(base_url, "/api/agent/runs/stream", prompt)
    started = time.monotonic()
    event_types: list[str] = []
    first_public_event_ms: int | None = None
    current_event = "message"
    data_lines: list[str] = []
    final_run: dict[str, Any] | None = None
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - guarded isolated target
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    current_event = line.partition(":")[2].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.partition(":")[2].strip())
                elif not line and data_lines:
                    event_types.append(current_event)
                    public_events = {
                        "answer_delta",
                        "evidence_ready",
                        "action_required",
                        "warning",
                        "final",
                    }
                    if current_event in public_events and first_public_event_ms is None:
                        first_public_event_ms = int((time.monotonic() - started) * 1_000)
                    try:
                        event_data = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("isolated target emitted invalid SSE JSON") from exc
                    if current_event == "final" and isinstance(event_data, dict):
                        candidate = event_data.get("run")
                        if isinstance(candidate, dict):
                            final_run = candidate
                    current_event = "message"
                    data_lines = []
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("isolated target stream failed") from exc
    if final_run is None:
        raise RuntimeError("isolated target stream has no final run")
    return final_run, tuple(event_types), first_public_event_ms


def _request(base_url: str, path: str, prompt: str) -> Request:
    return Request(
        f"{base_url}{path}",
        data=json.dumps({"prompt": prompt, "evaluation_mode": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _is_loopback(base_url: str) -> bool:
    return base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")


if __name__ == "__main__":
    raise SystemExit(main())
