from __future__ import annotations

from pathlib import Path


def test_host_cli_defaults_interactive_sessions_to_rich_without_override() -> None:
    wrapper = (Path(__file__).parents[1] / "deploy" / "hypertrade-host-cli").read_text()

    assert '[ -t 1 ]' in wrapper
    assert '[ "${HYPERTRADE_RENDERER+x}" != "x" ]' in wrapper
    assert '"HYPERTRADE_RENDERER=rich"' in wrapper
