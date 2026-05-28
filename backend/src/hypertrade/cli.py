from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TextIO

import httpx


class AgentClient(Protocol):
    def login(self) -> None: ...

    def run_agent(self, prompt: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CliConfig:
    api_url: str
    username: str
    password: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> CliConfig:
        return cls(
            api_url=os.getenv("HYPERTRADE_API_URL", "http://127.0.0.1:3334"),
            username=os.getenv("HYPERTRADE_USERNAME")
            or os.getenv("ADMIN_USERNAME")
            or "admin",
            password=os.getenv("HYPERTRADE_PASSWORD")
            or os.getenv("ADMIN_PASSWORD")
            or "hypertrade-admin",
            timeout_seconds=float(os.getenv("HYPERTRADE_TIMEOUT_SECONDS", "20")),
        )


class AgentApiClient:
    def __init__(
        self,
        config: CliConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.client = http_client or httpx.Client(
            base_url=config.api_url.rstrip("/"),
            timeout=config.timeout_seconds,
        )

    def login(self) -> None:
        response = self.client.post(
            self._url("/api/auth/login"),
            json={"username": self.config.username, "password": self.config.password},
        )
        response.raise_for_status()

    def run_agent(self, prompt: str) -> dict[str, Any]:
        response = self.client.post(self._url("/api/agent/runs"), json={"prompt": prompt})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Agent run response must be a JSON object")
        return payload

    def _url(self, path: str) -> str:
        return f"{self.config.api_url.rstrip('/')}{path}"


def main(
    argv: Sequence[str] | None = None,
    *,
    client: AgentClient | None = None,
    output: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    parser = _build_parser()
    args = parser.parse_args(argv)
    agent_client = client or AgentApiClient(CliConfig.from_env())

    if args.command == "ask":
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            parser.error("ask requires a prompt")
        agent_client.login()
        render_run(agent_client.run_agent(prompt), output=output)
        return 0

    if args.command == "chat":
        run_chat(client=agent_client, output=output)
        return 0

    parser.print_help(output)
    return 0


def run_chat(
    *,
    client: AgentClient,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    client.login()
    print("HyperTrade CLI chat. Type exit, quit, or :q to leave.", file=output)
    while True:
        try:
            prompt = input_fn("hypertrade> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("", file=output)
            return
        if prompt.lower() in {"exit", "quit", ":q"}:
            return
        if not prompt:
            continue
        render_run(client.run_agent(prompt), output=output)


def render_run(run: dict[str, Any], *, output: TextIO | None = None) -> None:
    output = output or sys.stdout
    print(f"Run: {run.get('id', 'unknown')}", file=output)
    print(f"Status: {run.get('status', 'unknown')}", file=output)
    trace_events = run.get("trace_events", [])
    if isinstance(trace_events, list) and trace_events:
        print("Tools:", file=output)
        for event in trace_events:
            if not isinstance(event, dict):
                continue
            print(
                f"- {event.get('tool_name', 'unknown')}: {event.get('status', 'unknown')}",
                file=output,
            )
    print("", file=output)
    print(str(run.get("report_markdown", "")), file=output)


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hypertrade",
        description="HyperTrade Agent CLI conversation harness.",
    )
    subparsers = parser.add_subparsers(dest="command")
    ask = subparsers.add_parser("ask", help="Run one Agent prompt through the HyperTrade API.")
    ask.add_argument("prompt", nargs="+")
    subparsers.add_parser("chat", help="Start an interactive Agent conversation loop.")
    return parser
