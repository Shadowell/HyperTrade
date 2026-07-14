from __future__ import annotations

from io import StringIO

from hypertrade.cli import LocalAgentClient, handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.research.schemas import ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.triggers import ResearchTriggerCreate, ResearchTriggerService


def test_trigger_cli_lists_controls_runs_and_audits() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    mandate = ResearchProgramService(db).create_mandate(
        ResearchMandateCreate(
            name="CLI trigger mandate",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    settings = Settings(RESEARCH_TRIGGERS_ENABLED=True)
    trigger = ResearchTriggerService(db, settings=settings).create(
        ResearchTriggerCreate(
            name="CLI data quality trigger",
            trigger_type="data_quality",
            mandate_id=str(mandate["id"]),
            objective_template="Investigate committed data quality evidence only.",
            enabled=False,
        ),
        actor="test",
    )
    client = LocalAgentClient(settings=settings, db=db)
    output = StringIO()

    handle_slash_command("/triggers list", client=client, output=output)
    handle_slash_command(
        f"/triggers enable {trigger['id']} operator_enable",
        client=client,
        output=output,
    )
    handle_slash_command(
        f"/triggers run {trigger['id']} investigate_now",
        client=client,
        output=output,
    )
    handle_slash_command(
        f"/triggers fires {trigger['id']}", client=client, output=output
    )
    handle_slash_command(
        "/triggers kill on incident_response", client=client, output=output
    )

    rendered = output.getvalue()
    assert "feature_enabled=True" in rendered
    assert "[enabled]" in rendered
    assert "Trigger fire" in rendered
    assert "Research trigger fires" in rendered
    assert "kill switch=True" in rendered
