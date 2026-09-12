import pytest
from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.streaming import stream_frames


def test_stream_replays_sanitized_events_and_can_resume():
    ctrl = ARCController(goal=ARCGoalV1(objective="test"))
    ctrl.apply_event("operator_needed", {"reason": "budget", "password": "do-not-stream"})
    frames = stream_frames(ctrl.projection, 0)
    assert any(kind == "activity" for kind, _, _ in frames)
    assert "do-not-stream" not in str(frames)
    cursor = len(ctrl.projection.events)
    assert not any(kind == "activity" for kind, _, _ in stream_frames(ctrl.projection, cursor))
    assert frames[-1][0] == "checkpoint"
    with pytest.raises(ValueError):
        stream_frames(ctrl.projection, cursor + 1)


def test_start_follows_by_default_and_detach_is_explicit():
    from hypertrade.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["research", "start", "research"])
    assert not args.detach
    assert parser.parse_args(["research", "start", "research", "--detach"]).detach
    assert parser.parse_args(["research", "watch", "arc_test", "--plain"]).plain


def test_stream_transport_resumes_without_duplicate_output(monkeypatch):
    import httpx
    from hypertrade.arc.streaming import encode_frame
    from hypertrade.research_follow import research_events

    calls = []

    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield encode_frame("activity", 1, {"event_id": "one"}).encode()
            raise httpx.ReadError("disconnect")

    def handler(request):
        calls.append(request.headers.get("Last-Event-ID"))
        if len(calls) == 1:
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=Broken()
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=encode_frame("activity", 1, {"event_id": "one"})
            + encode_frame("activity", 2, {"event_id": "two"})
            + encode_frame("checkpoint", None, {"state": "needs_operator"}),
        )

    monkeypatch.setattr("hypertrade.research_follow.time.sleep", lambda _: None)
    with httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler)) as client:
        events = list(research_events(client, "arc_test"))
    assert calls == ["0", "1"]
    assert [p["event_id"] for k, p in events if k == "activity"] == ["one", "two"]


def test_watch_is_read_only_and_reports_errors():
    import io
    from unittest.mock import patch

    import httpx
    from hypertrade.arc.streaming import encode_frame
    from hypertrade.cli import CliConfig, _build_parser
    from hypertrade.research_cli import run_research_cli

    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=encode_frame("checkpoint", None, {"state": "needs_operator"}),
            )
        return httpx.Response(200, json={"mission_id": "arc_test"})

    client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    args = _build_parser().parse_args(["research", "watch", "arc_test", "--plain"])
    with patch("hypertrade.research_cli.httpx.Client", return_value=client):
        assert run_research_cli(args, CliConfig("https://test", "u", "p"), io.StringIO()) == 0
    assert [path for method, path in calls if method == "POST"] == ["/api/auth/login"]


def test_hui_review_requires_reason_and_binds_exact_hash():
    import asyncio

    import httpx
    from hypertrade.research_ui import EvidenceScreen, ResearchApp
    from textual.widgets import Button, Input

    calls = []
    digest = "a" * 64

    def handler(request):
        import json

        if request.method == "POST":
            calls.append((request.headers.get("Idempotency-Key"), json.loads(request.content)))
            return httpx.Response(200, json={"status": "paper_observing"})
        return httpx.Response(200, json={"status": "ready", "unknowns": [], "package_hash": digest})

    class StaticApp(ResearchApp):
        def action_follow(self):
            pass

    async def exercise():
        with httpx.Client(
            base_url="https://test", transport=httpx.MockTransport(handler)
        ) as client:
            app = StaticApp(client, "arc_test")
            async with app.run_test(size=(100, 35)) as pilot:
                app.action_review()
                await pilot.pause()
                assert isinstance(app.screen, EvidenceScreen)
                assert app.screen.query_one("#approve", Button).disabled
                app.screen.query_one("#reason", Input).value = "已核对版本，同意独立模拟"
                await pilot.pause()
                await pilot.click("#approve")
                await pilot.pause()

    asyncio.run(exercise())
    assert calls == [
        (
            "cli-paper-" + digest + "-approve",
            {"package_hash": digest, "decision": "approve", "reason": "已核对版本，同意独立模拟"},
        )
    ]


def test_checkpoint_does_not_replay_only_last_hundred_events():
    ctrl = ARCController(goal=ARCGoalV1(objective="test"))
    for i in range(130):
        ctrl.apply_event("operator_needed", {"reason": str(i)})
    frames = stream_frames(ctrl.projection, 0)
    assert len([x for x in frames if x[0] == "activity"]) == len(ctrl.projection.events)
    tail = stream_frames(ctrl.projection, len(ctrl.projection.events) - 2)
    assert len([x for x in tail if x[0] == "activity"]) == 2


def test_start_creates_once_then_streams(monkeypatch):
    import io

    import httpx
    from hypertrade.arc.streaming import encode_frame
    from hypertrade.cli import CliConfig, _build_parser
    from hypertrade.research_cli import run_research_cli

    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=encode_frame(
                    "activity",
                    1,
                    {"event_id": "one", "label": "提出候选", "logs": {"symbol": "SOL-USDT-SWAP"}},
                )
                + encode_frame("checkpoint", None, {"state": "needs_operator"}),
            )
        return httpx.Response(200, json={"mission_id": "arc_new"})

    client = httpx.Client(base_url="https://test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr("hypertrade.research_cli.httpx.Client", lambda **kwargs: client)
    output = io.StringIO()
    assert (
        run_research_cli(
            _build_parser().parse_args(["research", "start", "研究", "--plain"]),
            CliConfig("https://test", "u", "p"),
            output,
        )
        == 0
    )
    assert calls.count(("POST", "/api/v1/arc/missions")) == 1
    assert "提出候选" in output.getvalue()
    assert "SOL-USDT-SWAP" in output.getvalue()
