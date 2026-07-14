"""Optional terminal research workbench.

This package is imported lazily by the CLI so the base command remains usable
without the ``tui`` optional dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hypertrade.cli import AgentClient


def launch_tui(client: AgentClient, *, session_id: str = "") -> None:
    """Start the Textual app after the CLI has authenticated the API client."""
    from hypertrade.tui.app import ResearchWorkbenchApp

    ResearchWorkbenchApp(client=client, initial_session_id=session_id).run()


def dependency_error(exc: ImportError) -> SystemExit:
    """Return a stable operator error without breaking the base CLI import."""
    return SystemExit(
        "The TUI dependency is not installed. Run `uv sync --extra tui`, then retry `ht tui`."
    )


__all__: tuple[str, ...] = ("dependency_error", "launch_tui")
