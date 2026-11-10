"""Prompt change control: editing an agent prompt must be a decision, not a side effect.

The AVO system prompt steers every autonomous research round and the research roles steer the
research graph. A one-line edit changes behaviour for every strategy at once, and results from
before and after it are not directly comparable, so a prompt edit that rides along in an
unrelated PR is easy to miss and hard to attribute later. These tests pin the exact text by hash.

When one fails, that is the point: review the change, say in the PR what behaviour it is meant to
change and that earlier research results are not comparable across it (or re-run the paired
evaluation: `python -m hypertrade.evals.memory_ablation`), then update the hash below.
"""

import hashlib

from hypertrade.arc.avo import _SYSTEM
from hypertrade.research.roles.definitions import ROLE_CATALOG, role_catalog_hash

AVO_SYSTEM_PROMPT_SHA256 = "ac40c3c02e865fdba35ee26d3019da3b079f4fb92ef597dadb41d45fbda13c78"
RESEARCH_ROLE_CATALOG_SHA256 = "1a87a27a99fcf580ae7998e2cb9aabd4a11b23092126a7155aa2629ab659731a"

_HOW_TO_ACKNOWLEDGE = (
    "State in the PR what behaviour this prompt change is meant to change and that research "
    "results before and after it are not directly comparable (or re-run the paired evaluation, "
    "`python -m hypertrade.evals.memory_ablation`), then set the expected hash in "
    "tests/test_prompt_change_control.py to {actual}."
)


def test_avo_system_prompt_is_unchanged_or_the_change_was_acknowledged() -> None:
    actual = hashlib.sha256(_SYSTEM.encode("utf-8")).hexdigest()

    assert actual == AVO_SYSTEM_PROMPT_SHA256, (
        "The AVO system prompt changed. " + _HOW_TO_ACKNOWLEDGE.format(actual=actual)
    )


def test_research_role_catalog_is_unchanged_or_the_change_was_acknowledged() -> None:
    # The catalog hash covers every role's prompt, version, tool policy and budget.
    actual = role_catalog_hash()

    assert actual == RESEARCH_ROLE_CATALOG_SHA256, (
        "A research role (prompt, version, tool policy or budget) changed. "
        + _HOW_TO_ACKNOWLEDGE.format(actual=actual)
    )


def test_every_research_role_carries_a_version_and_its_own_prompt_hash() -> None:
    # The version string is what runs record next to results; a prompt edit without a version
    # bump would make two different prompts indistinguishable in the evidence.
    for key, role in ROLE_CATALOG.items():
        assert role.version.startswith(f"{key}.v"), (key, role.version)
        assert len(role.prompt_hash) == 64, key
