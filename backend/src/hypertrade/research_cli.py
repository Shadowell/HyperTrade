"""CLI transport for the same research lifecycle exposed to external consoles."""

from __future__ import annotations

import argparse
import json
import uuid
from typing import TYPE_CHECKING, Any, TextIO, get_args
from urllib.parse import quote

import httpx

from hypertrade.arc.contracts import ChatProviderName

if TYPE_CHECKING:
    from hypertrade.cli import CliConfig


def add_research_parser(subparsers: Any) -> None:
    research = subparsers.add_parser("research", help="策略研究、证据与逐版本模拟盘审核")
    commands = research.add_subparsers(dest="research_action", required=True)
    start = commands.add_parser("start", help="发起研究；回测后等待人工审核")
    start.add_argument("objective", nargs="+")
    start.add_argument("--mode", choices=("avo", "arc"), default="avo")
    start.add_argument("--provider", choices=get_args(ChatProviderName))
    start.add_argument("--model", help="任务模型覆盖（codex / vide_coding）")
    start.add_argument("--max-model-calls", type=int, default=20)
    start.add_argument("--max-backtests", type=int, default=10)
    start.add_argument("--symbol", default="BTC-USDT-SWAP")
    start.add_argument("--timeframe", default="1H")
    start.add_argument("--max-candidates", type=int, default=5)
    start.add_argument("--paper-capital", type=float, default=100)
    start.add_argument("--alternative-source-confirmed", action="store_true")
    commands.add_parser("list", help="列出与 BitPro 页面相同的研究任务")
    for name in ("status", "evidence", "review", "candidate", "continue", "decide"):
        command = commands.add_parser(name)
        command.add_argument("mission_id")
        if name == "candidate":
            command.add_argument("attempt_id")
        if name == "continue":
            command.add_argument("--provider", choices=get_args(ChatProviderName))
            command.add_argument("--model", help="任务模型覆盖（codex / vide_coding）")
            command.add_argument("--extra-candidates", type=int, default=3)
            command.add_argument("--extra-model-calls", type=int, default=0)
            command.add_argument("--extra-tool-calls", type=int, default=0)
            command.add_argument("--extra-backtests", type=int, default=0)
            command.add_argument("--extra-wall-seconds", type=int, default=0)
            command.add_argument("--idempotency-key")
        if name == "decide":
            command.add_argument("--decision", choices=("approve", "reject"), required=True)
            command.add_argument("--reason", required=True)
            command.add_argument("--package-hash", required=True)
            command.add_argument("--idempotency-key")


def research_request(args: argparse.Namespace) -> tuple[str, str, dict[str, Any], dict[str, str]]:
    root = "/api/v1/arc/missions"
    action = args.research_action
    if action == "list":
        return "GET", root, {}, {}
    if action == "start":
        return (
            "POST",
            root,
            {
                "objective": " ".join(args.objective),
                "research_mode": args.mode,
                "provider_name": args.provider,
                "model_name": args.model,
                "max_model_calls": args.max_model_calls,
                "max_backtests": args.max_backtests,
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "max_candidates": args.max_candidates,
                "paper_initial_equity": args.paper_capital,
                "alternative_source_confirmed": args.alternative_source_confirmed,
            },
            {},
        )
    path = f"{root}/{quote(args.mission_id, safe='')}"
    if action == "decide":
        return (
            "POST",
            f"{path}/paper-review/decide",
            {
                "decision": args.decision,
                "reason": args.reason,
                "package_hash": args.package_hash,
            },
            {
                "Idempotency-Key": args.idempotency_key
                or f"cli-paper-{args.package_hash}-{args.decision}"
            },
        )
    if action == "continue":
        return (
            "POST",
            f"{path}/continue",
            {
                "extra_candidates": args.extra_candidates,
                "provider_name": args.provider,
                "model_name": args.model,
                "extra_model_calls": args.extra_model_calls,
                "extra_tool_calls": args.extra_tool_calls,
                "extra_backtests": args.extra_backtests,
                "extra_wall_seconds": args.extra_wall_seconds,
            },
            {"Idempotency-Key": args.idempotency_key or f"cli-continue-{uuid.uuid4().hex}"},
        )
    suffix = {"status": "progress", "evidence": "evidence", "review": "paper-review"}
    if action == "candidate":
        return "GET", f"{path}/candidates/{quote(args.attempt_id, safe='')}", {}, {}
    return "GET", f"{path}/{suffix[action]}", {}, {}


def run_research_cli(args: argparse.Namespace, config: CliConfig, output: TextIO) -> int:
    method, path, body, headers = research_request(args)
    # Standalone deployment can be localhost; neither CLI nor BitPro owns a second
    # research state machine. Both operate on service-owned mission IDs and reviews.
    try:
        with httpx.Client(
            base_url=config.api_url.rstrip("/"), timeout=config.timeout_seconds
        ) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "username": config.username,
                    "password": config.password,
                },
            )
            login.raise_for_status()
            response = client.request(
                method, path, headers=headers, json=body if method == "POST" else None
            )
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2), file=output)
        return 0
    except httpx.HTTPError as exc:
        message = "研究服务不可用"
        if isinstance(exc, httpx.HTTPStatusError):
            message = f"研究请求被拒绝（HTTP {exc.response.status_code}）"
        print(message, file=output)
        return 1
