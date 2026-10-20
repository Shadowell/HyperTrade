"""Variant-slot facts BitPro reports for a parent: whether to feed it, and with what.

BitPro lets one parent race several challengers at once (one per variant slot). Its
`research-variant-policy.relay` says how many seats exist, how many reviewed candidates already
wait for one, and which variants it already raced, queued or eliminated. All of it is optional:
an older BitPro (or another market target) reports none of it, and callers then fall back to the
earlier one-challenger behaviour.
"""

from __future__ import annotations

import json
import math
from typing import Any

_TRIED_STATES = {
    "racing": "is racing",
    "adopting": "is being handed over",
    "adopted": "was adopted",
    "eliminated": "was eliminated",
    "cancelled": "was cancelled by an operator",
    "waiting": "is queued for a seat",
}


def relay_seats(relay: Any) -> dict[str, int] | None:
    """Seats of one parent; `open` is what is still free once queued candidates took theirs.

    None when BitPro does not report seats. Candidates already waiting for a seat will fill
    free seats within seconds, so only `open` seats justify researching more of them.
    """
    slots = relay.get("slots") if isinstance(relay, dict) else None
    if not isinstance(slots, dict):
        return None
    counts: dict[str, int] = {}
    for key in ("total", "used", "free"):
        value = slots.get(key)
        if type(value) is not int or value < 0:
            return None
        counts[key] = value
    queued = slots.get("queued")
    # A BitPro that does not count queued candidates leaves every free seat open.
    queued = queued if type(queued) is int and queued >= 0 else 0
    return {**counts, "queued": queued, "open": max(0, counts["free"] - queued)}


def _plain(value: Any) -> Any:
    """Equal numbers compare equal whether they arrive as 8 or 8.0."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return int(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def variant_identity(parameter_changes: Any, structural_changes: Any) -> str:
    """Two proposals are the same experiment when their parameter and structural changes match.

    This is the identity BitPro's own enrollment uses to never race the same variant twice.
    """
    return json.dumps(
        {"p": _plain(parameter_changes or {}), "s": _plain(structural_changes or {})},
        sort_keys=True,
        ensure_ascii=False,
    )


def tried_variant(
    relay: Any, parameter_changes: Any, structural_changes: Any
) -> dict[str, Any] | None:
    """The variant BitPro already raced, queued or eliminated with exactly these changes."""
    entries = relay.get("tried_variants") if isinstance(relay, dict) else None
    if not isinstance(entries, list):
        return None
    wanted = variant_identity(parameter_changes, structural_changes)
    for entry in entries:  # newest first
        if isinstance(entry, dict) and wanted == variant_identity(
            entry.get("parameter_changes"), entry.get("structural_changes")
        ):
            return entry
    return None


def describe_tried(entry: dict[str, Any]) -> str:
    state = _TRIED_STATES.get(str(entry.get("state")), "was already tried")
    kind = entry.get("kind")
    detail = f" ({kind})" if isinstance(kind, str) and kind else ""
    return f"variant #{entry.get('candidate_strategy_id')} {state}{detail}"
