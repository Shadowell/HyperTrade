from __future__ import annotations

from io import StringIO
from typing import Any, cast

from hypertrade.cli import (
    AgentClient,
    handle_memory_assertion_command,
    handle_skill_command,
)


class GovernanceClient:
    def __init__(self) -> None:
        self.decisions: list[tuple[str, str, str, str]] = []

    def list_memory_assertions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "masrt_cli_1",
                "status": "proposed",
                "usable": False,
                "claim": "Source-bound regime assertion",
                "source_evidence_ids": ["evi_1"],
            }
        ]

    def review_memory_assertion(
        self, assertion_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        self.decisions.append(("assertion", assertion_id, decision, reason))
        return {"id": assertion_id, "status": "active", "usable": True}

    def list_skill_proposals(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "skp_cli_1",
                "status": "pending_approval",
                "skill_key": "regime_summary",
                "definition_hash": "a" * 64,
            }
        ]

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any]:
        return {
            **self.list_skill_proposals()[0],
            "id": proposal_id,
            "diff": "+ prompt_template: cite source ids",
            "evaluations": [
                {
                    "status": "passed",
                    "suite_version": "research_os_golden_v1",
                    "artifact_hash": "b" * 64,
                }
            ],
        }

    def list_skill_releases(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "skrel_cli_1",
                "status": "active",
                "skill_key": "regime_summary",
                "version": 1,
            }
        ]

    def decide_skill_proposal(
        self, proposal_id: str, *, decision: str, reason: str
    ) -> dict[str, Any]:
        self.decisions.append(("skill", proposal_id, decision, reason))
        return {"release": {"id": "skrel_cli_1"}}

    def rollback_skill_release(
        self, release_id: str, *, target_release_id: str, reason: str
    ) -> dict[str, Any]:
        self.decisions.append(("rollback", release_id, target_release_id, reason))
        return {"id": target_release_id, "status": "active", "version": 1}


def test_assertion_cli_lists_and_reviews_with_reason() -> None:
    raw_client = GovernanceClient()
    client = cast(AgentClient, raw_client)
    output = StringIO()

    handle_memory_assertion_command("/assertions list", client=client, output=output)
    handle_memory_assertion_command(
        "/assertions approve masrt_cli_1 evidence verified",
        client=client,
        output=output,
    )

    assert "Source-bound regime assertion" in output.getvalue()
    assert "[active] usable=True" in output.getvalue()
    assert raw_client.decisions == [
        ("assertion", "masrt_cli_1", "approve", "evidence verified")
    ]


def test_skill_cli_projects_diff_release_and_rollback() -> None:
    raw_client = GovernanceClient()
    client = cast(AgentClient, raw_client)
    output = StringIO()

    handle_skill_command("/skills proposals", client=client, output=output)
    handle_skill_command("/skills show skp_cli_1", client=client, output=output)
    handle_skill_command(
        "/skills approve skp_cli_1 isolated eval verified",
        client=client,
        output=output,
    )
    handle_skill_command("/skills releases", client=client, output=output)
    handle_skill_command(
        "/skills rollback skrel_cli_2 skrel_cli_1 restore stable",
        client=client,
        output=output,
    )

    rendered = output.getvalue()
    assert "+ prompt_template: cite source ids" in rendered
    assert "research_os_golden_v1" in rendered
    assert "regime_summary v1" in rendered
    assert raw_client.decisions == [
        ("skill", "skp_cli_1", "approve", "isolated eval verified"),
        ("rollback", "skrel_cli_2", "skrel_cli_1", "restore stable"),
    ]
