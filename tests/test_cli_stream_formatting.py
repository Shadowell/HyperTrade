"""Sprint-145: streaming output formatting — plain passthrough and footer.

Rich Live rendering itself needs a terminal; the contract here is the
mode selection (plain vs live), raw passthrough in plain mode, the
structured footer built from run observability, and tool-line formatting.
"""

from __future__ import annotations

import io
from typing import Any

from hypertrade.cli import (
    _LiveMarkdownStreamer,
    _stream_footer,
)


def _plain_streamer() -> tuple[_LiveMarkdownStreamer, io.StringIO]:
    output = io.StringIO()
    output.isatty = lambda: False  # type: ignore[method-assign]
    return _LiveMarkdownStreamer(output), output


def test_plain_mode_passes_raw_text_through() -> None:
    streamer, output = _plain_streamer()

    streamer.append("## 结论\n")
    streamer.append("BTC 中性。")
    streamer.finish()

    # Deltas pass through byte-for-byte; finish() adds exactly one trailing
    # newline so a footer can never concatenate onto the answer.
    assert output.getvalue() == "## 结论\nBTC 中性。\n"
    assert streamer.streamed_chars == len("## 结论\nBTC 中性。")


def test_plain_mode_tool_lines_are_suppressed_not_interleaved() -> None:
    streamer, output = _plain_streamer()

    streamer.append("partial answer")
    streamer.print_tool_line("tool market_candles completed")

    # In plain mode tool lines would corrupt the streamed answer; they are
    # dropped there because full-progress mode already prints them.
    assert output.getvalue() == "partial answer"


def test_tty_mode_uses_rich_live(monkeypatch) -> None:
    monkeypatch.delenv("HYPERTRADE_STREAM_RENDERER", raising=False)
    output = io.StringIO()
    # Force the TTY probe even though StringIO is not a real terminal.
    output.isatty = lambda: True  # type: ignore[method-assign]
    streamer = _LiveMarkdownStreamer(output)

    assert streamer._plain is False

    streamer.start()
    try:
        assert streamer._live is not None
        streamer.append("## 结论\n格式化流式")
        streamer.flush()
    finally:
        streamer.finish()

    assert streamer._live is None


def test_plain_env_var_forces_raw_streaming(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_STREAM_RENDERER", "plain")
    output = io.StringIO()
    output.isatty = lambda: True  # type: ignore[method-assign]

    streamer = _LiveMarkdownStreamer(output)

    assert streamer._plain is True


def test_stream_footer_builds_structured_summary() -> None:
    final_run: dict[str, Any] = {
        "id": "run_footer_01",
        "observability": {
            "duration_ms": 12_340,
            "usage": {"total_tokens": 4_567},
            "tools": {"call_count": 6},
            "context": {"compactions": 2},
        },
    }

    lines = _stream_footer(final_run)

    assert len(lines) == 1
    assert "run run_footer_01" in lines[0]
    assert "12.3s" in lines[0]
    assert "4567 tokens" in lines[0]
    assert "6 tools" in lines[0]
    assert "2 compactions" in lines[0]


def test_stream_footer_degrades_gracefully_without_observability() -> None:
    lines = _stream_footer({"id": "run_min"})

    assert lines == ["── 回答已实时输出 · run run_min ──"]
