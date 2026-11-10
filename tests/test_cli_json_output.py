"""Unit tests for CLI structured JSON output (--json)."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

from hypertrade.cli import handle_regime_shadow_command


def test_handle_regime_shadow_command_json_output() -> None:
    client = MagicMock()
    mock_targets = [
        {"id": "tgt-1", "version_number": 1, "status": "active", "eligible_count": 5},
        {"id": "tgt-2", "version_number": 2, "status": "draft", "eligible_count": 2},
    ]
    client.list_regime_shadow_targets.return_value = mock_targets

    out = io.StringIO()
    handle_regime_shadow_command("/shadow list --json", client=client, output=out)

    parsed = json.loads(out.getvalue())
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["id"] == "tgt-1"
    assert parsed[1]["id"] == "tgt-2"


def test_handle_regime_shadow_command_text_output() -> None:
    client = MagicMock()
    client.list_regime_shadow_targets.return_value = [
        {"id": "tgt-1", "version_number": 1, "status": "active", "eligible_count": 5}
    ]

    out = io.StringIO()
    handle_regime_shadow_command("/shadow list", client=client, output=out)

    text = out.getvalue()
    assert "Regime-aware Shadow V2 targets:" in text
    assert "tgt-1 v1 [active]" in text
