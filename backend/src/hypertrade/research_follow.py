"""Shared resumable SSE transport for plain terminals and the interactive research UI."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any, TextIO
from urllib.parse import quote

import httpx


def research_events(
    client: httpx.Client, mission_id: str, *, stopped: Callable[[], bool] = lambda: False
) -> Iterator[tuple[str, dict[str, Any]]]:
    cursor, failures = 0, 0
    path = f"/api/v1/arc/missions/{quote(mission_id, safe='')}/stream"
    while not stopped():
        try:
            with client.stream("GET", path, headers={"Last-Event-ID": str(cursor)}) as response:
                response.raise_for_status()
                if not response.headers.get("content-type", "").startswith("text/event-stream"):
                    raise ValueError("服务器未返回研究事件流，请检查服务版本")
                kind, identifier, data = "", None, []
                for line in response.iter_lines():
                    if stopped():
                        return
                    if line.startswith("event:"):
                        kind = line[6:].strip()
                    elif line.startswith("id:"):
                        identifier = int(line[3:].strip())
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        payload = json.loads("\n".join(data))
                        if identifier is None or identifier > cursor:
                            yield kind, payload
                            if identifier is not None:
                                cursor = identifier
                        failures = 0
                        if kind in {"checkpoint", "error"}:
                            return
                        kind, identifier, data = "", None, []
        except (httpx.TransportError, httpx.StreamError) as exc:
            failures += 1
            if failures > 3:
                raise RuntimeError(
                    f"连接中断；使用 ht research watch {mission_id} 重新连接"
                ) from exc
            yield "connection", {"message": f"连接中断，正在从事件 {cursor} 续接（{failures}/3）"}
            time.sleep(min(failures, 3))


def follow_research(
    client: httpx.Client, mission_id: str, output: TextIO, *, plain: bool = False
) -> int:
    print(f"研究任务 {mission_id} · Ctrl+C 退出观看，服务器任务继续", file=output, flush=True)
    if not plain and output.isatty():
        try:
            from hypertrade.research_ui import ResearchApp
        except ImportError:
            print("未安装交互界面依赖，使用逐行流式输出。", file=output, flush=True)
        else:
            ResearchApp(client, mission_id).run()
            return 0
    state = ""
    try:
        for kind, payload in research_events(client, mission_id):
            if kind == "activity":
                print(f"[{payload.get('at', '')}] {payload.get('label', '')}", file=output)
                logs = payload.get("logs") or payload.get("detail")
                if logs:
                    print(json.dumps(logs, ensure_ascii=False, indent=2), file=output)
            elif kind == "snapshot" and payload.get("state") != state:
                state = str(payload.get("state", ""))
                print(f"阶段：{state}", file=output)
            elif kind == "checkpoint":
                print(
                    f"本轮停靠：{payload.get('state')}；查看证据：ht research review {mission_id}",
                    file=output,
                )
            elif kind in {"error", "connection"}:
                print(payload.get("message"), file=output)
            output.flush()
            if kind == "error":
                return 1
        return 0
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=output, flush=True)
        return 1
