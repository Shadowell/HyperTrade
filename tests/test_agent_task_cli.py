from io import StringIO

from hypertrade.cli import LocalAgentClient, handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import Database


def test_local_cli_agent_runs_are_task_backed_and_inspectable(tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    client = LocalAgentClient(
        settings=Settings(
            DEEPSEEK_API_KEY="",
            ACTIVE_CHAT_PROVIDER="deepseek",
            KNOWLEDGE_DIR=knowledge,
        ),
        db=db,
    )

    run = client.run_agent("bounded CLI task")
    tasks = client.list_agent_tasks()
    sessions = client.list_agent_sessions()

    assert run["task_id"] == tasks[0]["id"]
    assert tasks[0]["status"] == "completed"
    assert sessions[0]["surface"] == "cli"

    output = StringIO()
    handle_slash_command("/tasks", client=client, output=output)
    handle_slash_command(f"/task {tasks[0]['id']}", client=client, output=output)
    rendered = output.getvalue()
    assert "Agent tasks:" in rendered
    assert tasks[0]["id"] in rendered
    assert "[completed]" in rendered
