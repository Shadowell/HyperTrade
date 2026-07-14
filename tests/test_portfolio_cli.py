from __future__ import annotations

from io import StringIO
from typing import Any, cast

from hypertrade.cli import AgentClient, handle_portfolio_v2_command


class PortfolioClient:
    def __init__(self) -> None:
        self.reviews: list[tuple[str, str, str, str]] = []

    def list_portfolio_assessments(self) -> list[dict[str, Any]]:
        return [self.get_portfolio_assessment("pasmt_cli_1")]

    def create_portfolio_assessment(self) -> dict[str, Any]:
        return self.get_portfolio_assessment("pasmt_cli_new")

    def get_portfolio_assessment(self, assessment_id: str) -> dict[str, Any]:
        return {
            "id": assessment_id,
            "status": "needs_data",
            "policy_version": "portfolio_lifecycle_policy.v1",
            "valid_until": "2026-07-15T02:00:00Z",
            "strategies": [{"card_id": "scard_1"}],
            "unknowns": ["strategy.scard_1.capacity"],
            "recommendations": [
                {
                    "recommendation_id": "plrec_cli_1",
                    "action": "run_targeted_research",
                    "strategy_card_id": "scard_1",
                }
            ],
        }

    def diff_portfolio_assessments(
        self, left_id: str, right_id: str
    ) -> dict[str, Any]:
        return {"left_id": left_id, "right_id": right_id, "unknowns_resolved": []}

    def review_portfolio_recommendation(
        self,
        assessment_id: str,
        recommendation_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        self.reviews.append((assessment_id, recommendation_id, decision, reason))
        return {
            "id": "slrev_cli_1",
            "decision": decision,
            "recommendation_action": "run_targeted_research",
        }


def test_portfolio_cli_lists_projects_and_records_review_reason() -> None:
    raw_client = PortfolioClient()
    client = cast(AgentClient, raw_client)
    output = StringIO()

    handle_portfolio_v2_command("/portfolio-v2 list", client=client, output=output)
    handle_portfolio_v2_command(
        "/portfolio-v2 show pasmt_cli_1", client=client, output=output
    )
    handle_portfolio_v2_command(
        "/portfolio-v2 review pasmt_cli_1 plrec_cli_1 hold need aligned returns",
        client=client,
        output=output,
    )

    rendered = output.getvalue()
    assert "strategies=1 unknowns=1" in rendered
    assert "run_targeted_research" in rendered
    assert "[hold]" in rendered
    assert raw_client.reviews == [
        ("pasmt_cli_1", "plrec_cli_1", "hold", "need aligned returns")
    ]
