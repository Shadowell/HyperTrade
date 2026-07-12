from __future__ import annotations

from io import StringIO
from typing import Any

from hypertrade.cli import handle_slash_command


class ResearchProgramClient:
    def run_research_job(self, job_id: str) -> dict[str, Any]:
        return {"job": {"id": job_id, "status": "evidence_recorded"}}

    def research_job_report(self, job_id: str) -> dict[str, Any]:
        return {"job": {"id": job_id}, "outcome": {"paper_promotion": "not_available"}}

    def list_paper_promotions(self, status: str = "") -> dict[str, Any]:
        return {"items": [{"id": "ppr_123", "status": "pending_paper_approval"}]}

    def request_paper_promotion(self, evidence_id: str, reason: str) -> dict[str, Any]:
        return {"id": "ppr_123", "evidence_id": evidence_id, "request_reason": reason}

    def approve_paper_promotion(
        self, promotion_id: str, reason: str, idempotency_key: str
    ) -> dict[str, Any]:
        return {
            "id": promotion_id,
            "status": "paper_observing",
            "approval_idempotency_key": idempotency_key,
            "approval_reason": reason,
        }

    def observe_paper_promotion(self, promotion_id: str) -> dict[str, Any]:
        return {"id": promotion_id, "status": "paper_observing", "observation": {}}


def test_research_program_cli_supports_run_and_read_only_report() -> None:
    output = StringIO()
    client = ResearchProgramClient()

    handle_slash_command("/research-program run rjob_123", client=client, output=output)
    handle_slash_command("/research-program report rjob_123", client=client, output=output)

    rendered = output.getvalue()
    assert '"status": "evidence_recorded"' in rendered
    assert '"paper_promotion": "not_available"' in rendered


def test_research_program_cli_requires_explicit_paper_promotion_commands() -> None:
    output = StringIO()
    client = ResearchProgramClient()

    handle_slash_command("/research-program promotions", client=client, output=output)
    handle_slash_command(
        "/research-program promote rexp_123 validated candidate", client=client, output=output
    )
    handle_slash_command(
        "/research-program approve-paper ppr_123 paper-key-123 operator approved",
        client=client,
        output=output,
    )
    handle_slash_command("/research-program observe-paper ppr_123", client=client, output=output)

    rendered = output.getvalue()
    assert '"pending_paper_approval"' in rendered
    assert '"evidence_id": "rexp_123"' in rendered
    assert '"approval_idempotency_key": "paper-key-123"' in rendered
    assert '"status": "paper_observing"' in rendered
