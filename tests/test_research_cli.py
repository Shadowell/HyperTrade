from __future__ import annotations

from io import StringIO
from typing import Any

from hypertrade.cli import handle_slash_command


class ResearchProgramClient:
    def run_research_job(self, job_id: str) -> dict[str, Any]:
        return {"job": {"id": job_id, "status": "evidence_recorded"}}

    def research_job_report(self, job_id: str) -> dict[str, Any]:
        return {"job": {"id": job_id}, "outcome": {"paper_promotion": "not_available"}}


def test_research_program_cli_supports_run_and_read_only_report() -> None:
    output = StringIO()
    client = ResearchProgramClient()

    handle_slash_command("/research-program run rjob_123", client=client, output=output)
    handle_slash_command("/research-program report rjob_123", client=client, output=output)

    rendered = output.getvalue()
    assert '"status": "evidence_recorded"' in rendered
    assert '"paper_promotion": "not_available"' in rendered
