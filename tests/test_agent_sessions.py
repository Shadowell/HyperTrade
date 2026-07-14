from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService, session_to_dict
from hypertrade.agent.tasks import AgentTaskCreate, AgentTaskService
from hypertrade.db import Database


def test_agent_session_persists_safe_provider_config_and_task_cursor() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    sessions = AgentSessionService(db)
    row = sessions.create(
        AgentSessionCreate(
            title="Research BTC",
            surface="cli",
            provider_config={
                "provider": "codex",
                "model": "gpt-5.4",
                "api_key": "must-not-persist",
            },
            context_policy={"max_history_turns": 8},
            created_by="operator:test",
        )
    )

    task = AgentTaskService(db).create(
        AgentTaskCreate(
            session_id=row.id,
            objective="Research BTC",
            idempotency_key="session-task-1",
        )
    )

    stored = session_to_dict(sessions.get(row.id))
    assert stored["provider_config"] == {"provider": "codex", "model": "gpt-5.4"}
    assert stored["last_event_sequence"] == 1
    assert AgentTaskService(db).get(task.id).session_id == row.id
    assert sessions.list()[0].id == row.id
