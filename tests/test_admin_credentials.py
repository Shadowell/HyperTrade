"""A deployed HyperTrade console must never accept the repository's built-in credentials."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app, refuse_builtin_admin_credentials

BUILTIN_PASSWORD = Settings.model_fields["admin_password"].default
BUILTIN_SECRET = Settings.model_fields["session_secret"].default
REAL_PASSWORD = "a-real-admin-password"
REAL_SECRET = "s" * 48


@pytest.mark.parametrize("app_env", ["production", "Staging"])
@pytest.mark.parametrize(
    ("password", "secret"),
    [
        (BUILTIN_PASSWORD, REAL_SECRET),
        (REAL_PASSWORD, BUILTIN_SECRET),
        (BUILTIN_PASSWORD, BUILTIN_SECRET),
    ],
)
def test_deployed_api_refuses_builtin_credentials(app_env: str, password: str, secret: str) -> None:
    settings = Settings(APP_ENV=app_env, ADMIN_PASSWORD=password, SESSION_SECRET=secret)
    with pytest.raises(RuntimeError, match="built-in"):
        create_app(settings=settings, db=Database("sqlite:///:memory:"))


@pytest.mark.parametrize("app_env", ["production", "development", "evaluation"])
def test_real_credentials_always_pass_and_defaults_stay_local(app_env: str) -> None:
    refuse_builtin_admin_credentials(
        Settings(APP_ENV=app_env, ADMIN_PASSWORD=REAL_PASSWORD, SESSION_SECRET=REAL_SECRET)
    )
    if app_env != "production":
        local = Settings(
            APP_ENV=app_env, ADMIN_PASSWORD=BUILTIN_PASSWORD, SESSION_SECRET=BUILTIN_SECRET
        )
        refuse_builtin_admin_credentials(local)


def test_login_requires_both_fields_exactly() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret-pass",
        SESSION_SECRET="t" * 40,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        for username, password in (
            ("admin", "secret-pas"),
            ("admin", "secret-pass "),
            ("Admin", "secret-pass"),
            ("admin", ""),
            ("管理员", "密码"),
        ):
            response = client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            assert response.status_code == 401, (username, password)
        accepted = client.post(
            "/api/auth/login", json={"username": "admin", "password": "secret-pass"}
        )
        assert accepted.status_code == 200
        assert client.get("/api/auth/me").json() == {"username": "admin"}
