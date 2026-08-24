"""Bare `ht` local runtime bootstrap: database fallback and settings resolution."""

from pathlib import Path

from hypertrade.cli import (
    _DEFAULT_DOCKER_DATABASE_URL,
    _ensure_sqlite_schema,
    _local_runtime_settings,
    _resolve_local_database_url,
)
from hypertrade.db import Database


def test_docker_default_database_url_falls_back_to_user_sqlite():
    resolved = _resolve_local_database_url(_DEFAULT_DOCKER_DATABASE_URL)

    assert resolved.startswith("sqlite:///")
    assert ".hypertrade" in resolved


def test_explicit_database_url_is_respected():
    assert (
        _resolve_local_database_url("postgresql+psycopg://u:p@localhost:5432/ht")
        == "postgresql+psycopg://u:p@localhost:5432/ht"
    )
    assert _resolve_local_database_url("sqlite:///./custom.db") == "sqlite:///./custom.db"


def test_ensure_sqlite_schema_creates_tables_idempotently(tmp_path):
    url = f"sqlite:///{tmp_path}/boot.db"

    _ensure_sqlite_schema(url)
    _ensure_sqlite_schema(url)  # second call must be a no-op, not an error

    db = Database(url)
    with db.session() as session:
        from sqlalchemy import inspect

        tables = set(inspect(session.connection()).get_table_names())
    assert "agent_sessions" in tables
    assert "memory_items" in tables


def test_local_runtime_settings_resolve_from_any_cwd(monkeypatch, tmp_path):
    """在无 .env 的目录运行时，仍能拿到 repo 配置与可用的本地库。"""
    monkeypatch.chdir(tmp_path)  # empty cwd: no .env, no docs/knowledge

    settings = _local_runtime_settings()

    assert settings.database_url.startswith("sqlite:///")
    # Knowledge base falls back to the repo checkout so RAG stays usable.
    assert (Path(settings.knowledge_dir) / "knowledge").exists() or Path(
        settings.knowledge_dir
    ).exists()
