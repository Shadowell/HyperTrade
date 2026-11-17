"""Regression tests ensuring verified dead prototypes stay removed and core modules import."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

OBSOLETE_MODULES = (
    "hypertrade.ui",
    "hypertrade.ui.cli_renderer",
    "hypertrade.ui.colors",
    "hypertrade.ui.config",
    "hypertrade.ui.formatter",
    "hypertrade.ui.progress",
    "hypertrade.agent.formatters",
    "hypertrade.risk.canary",
)

OBSOLETE_SCRIPTS = (
    "scripts/demo_agent_task_complete.py",
    "scripts/demo_ui_enhancements.py",
    "scripts/test_agent_output_formatting.py",
    "scripts/test_cli_renderer.py",
    "scripts/test_cli_integration.py",
)

ACTIVE_MODULES = (
    "hypertrade.main",
    "hypertrade.worker",
    "hypertrade.cli",
    "hypertrade.tui",
    "hypertrade.risk.governance",
    "hypertrade.research.source_refs",
    "hypertrade.agent.context",
)


@pytest.mark.parametrize("module_name", OBSOLETE_MODULES)
def test_obsolete_modules_cannot_be_imported(module_name: str) -> None:
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        spec = None
    assert spec is None or (
        spec.origin is None
        and not any(any(Path(p).glob("*.py")) for p in (spec.submodule_search_locations or []))
    )


def test_obsolete_ui_directory_has_no_python_sources() -> None:
    assert not list((REPO_ROOT / "backend/src/hypertrade/ui").glob("*.py"))


@pytest.mark.parametrize("script_relpath", OBSOLETE_SCRIPTS)
def test_obsolete_prototype_scripts_do_not_exist(script_relpath: str) -> None:
    assert not (REPO_ROOT / script_relpath).exists()


def test_dead_helper_symbols_are_removed() -> None:
    context_mod = importlib.import_module("hypertrade.agent.context")
    source_refs_mod = importlib.import_module("hypertrade.research.source_refs")

    assert not hasattr(context_mod, "_prefix_end")
    assert not hasattr(source_refs_mod, "source_ref_from_trace")
    assert not hasattr(source_refs_mod, "TraceEvent")


@pytest.mark.parametrize("module_name", ACTIVE_MODULES)
def test_active_modules_import_cleanly(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module is not None
