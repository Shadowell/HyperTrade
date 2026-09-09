"""The external console may start and read. It may never approve with a token."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from hypertrade.arc.auth import (
    ARCScope,
    hash_service_token,
    parse_service_tokens,
    sign_operator_assertion,
    verify_assertion_values,
)
from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCReflexionEventV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence_view import build_evidence_view
from hypertrade.arc.store import get_controller, reset_store, save_mission
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app

READ_TOKEN = "ht_svc_test_read"
START_TOKEN = "ht_svc_test_start"
BOTH_TOKEN = "ht_svc_test_both"
ASSERTION_SECRET = "arc-assertion-test-secret"


def test_new_mission_requires_paper_review_even_with_legacy_preauth(client):
    response = client.post(
        "/api/v1/arc/missions",
        headers={
            "X-HyperTrade-Service-Token": BOTH_TOKEN,
        },
        json={"objective": "review first", "paper_preauth_approved": True},
    )
    assert response.status_code == 200
    ctrl = get_controller(response.json()["mission_id"])
    assert ctrl.projection.goal.paper_review_required is True
    assert ctrl.projection.goal.paper_authorization is None


def test_token_cannot_approve_paper_and_missing_package_is_not_approvable(client):
    ctrl = ARCController(goal=ARCGoalV1(objective="review", paper_review_required=True))
    save_mission(ctrl)
    headers = {"X-HyperTrade-Service-Token": BOTH_TOKEN}
    package = client.get(f"/api/v1/arc/missions/{ctrl.mission_id}/paper-review", headers=headers)
    assert package.status_code == 200
    assert package.json()["status"] == "incomplete"
    response = client.post(
        f"/api/v1/arc/missions/{ctrl.mission_id}/paper-review/decide",
        headers={**headers, "Idempotency-Key": "paper-review-test"},
        json={"decision": "approve", "reason": "reviewed", "package_hash": "a" * 64},
    )
    assert response.status_code == 403


def test_paper_mission_cannot_request_live_approval(client):
    ctrl = ARCController(goal=ARCGoalV1(objective="review", paper_review_required=True))
    save_mission(ctrl)
    response = client.get(
        f"/api/v1/arc/missions/{ctrl.mission_id}/live-approval",
        headers={"X-HyperTrade-Service-Token": BOTH_TOKEN},
    )
    assert response.status_code == 409


def _catalog() -> str:
    return ",".join(
        [
            f"reader:arc:read:{hash_service_token(READ_TOKEN)}",
            f"starter:arc:start:{hash_service_token(START_TOKEN)}",
            f"console:arc:read+arc:start:{hash_service_token(BOTH_TOKEN)}",
        ]
    )


@pytest.fixture
def client() -> TestClient:
    reset_store()
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="arc-surface-test-secret",
        ARC_SERVICE_TOKENS=_catalog(),
        ARC_OPERATOR_ASSERTION_SECRET=ASSERTION_SECRET,
    )
    with TestClient(create_app(settings=settings, db=database)) as test_client:
        yield test_client
    reset_store()


@pytest.fixture
def unsigned_client() -> TestClient:
    reset_store()
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="arc-surface-test-secret",
        ARC_SERVICE_TOKENS=_catalog(),
        ARC_OPERATOR_ASSERTION_SECRET="",
    )
    with TestClient(create_app(settings=settings, db=database)) as test_client:
        yield test_client
    reset_store()


def _login(client: TestClient) -> None:
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code
        == 200
    )


def _headers(token: str, **extra: str) -> dict[str, str]:
    return {"X-HyperTrade-Service-Token": token, **extra}


def _create_mission(client: TestClient, token: str = START_TOKEN) -> str:
    created = client.post(
        "/api/v1/arc/missions",
        json={"objective": "probe", "symbol": "ETH-USDT-SWAP", "max_candidates": 2},
        headers=_headers(token),
    )
    assert created.status_code == 200, created.text
    return str(created.json()["mission_id"])


def _seed_rejected_attempt(mission_id: str) -> str:
    ctrl = ARCController(mission_id=mission_id, goal=ARCGoalV1(objective="probe"))
    existing = get_controller(mission_id)
    if existing is not None:
        ctrl = existing
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_reject",
        candidate_id="cand_reject",
        state="rejected",
        hypothesis="donchian short",
        strategy_code="class Secret: pass",
        strategy_spec={"family": "donchian_breakout", "direction": "short_only"},
        observed_metrics={
            "out_of_sample_sharpe": 0.2,
            "out_of_sample_trades": 3,
            "win_rate": 0.33,
            "walk_forward_folds": 4,
            "walk_forward_sharpes": [0.1, 0.2, 1.5, 0.0],
            "walk_forward_drawdowns": [0.2, 0.1, 0.05, 0.4],
            "ranking_basis": "out_of_sample",
        },
        reflexion_events=[
            ARCReflexionEventV1(
                candidate_id="cand_reject",
                failure_class="red_team_attack_failed",
                reason_codes=["OOS_SAMPLE_TOO_SMALL"],
                failed_gates=["historical_evidence"],
                observed_metrics={},
                negative_constraints=["样本外成交笔数不足，不能把夏普当证据"],
            )
        ],
    )
    if not any(item.attempt_id == attempt.attempt_id for item in ctrl.projection.attempts):
        ctrl.projection.attempts.append(attempt)
        save_mission(ctrl)
    return attempt.attempt_id


def _assertion(
    *,
    mission_id: str,
    decision: str,
    operator_id: str = "bitpro-admin",
    idempotency_key: str = "k-decide",
    issued_at: int | None = None,
    secret: str = ASSERTION_SECRET,
) -> str:
    return sign_operator_assertion(
        mission_id=mission_id,
        decision=decision,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        issued_at=issued_at if issued_at is not None else int(time.time()),
        secret=secret,
    )


def test_parse_service_tokens_keeps_colons_in_scopes() -> None:
    digest = "a" * 64
    parsed = parse_service_tokens(f"bitpro-console:arc:read+arc:start:{digest}")
    assert len(parsed) == 1
    principal, stored = parsed[0]
    assert principal.label == "bitpro-console"
    assert principal.scopes == frozenset({ARCScope.READ, ARCScope.START})
    assert stored == digest


def test_a_read_scoped_token_lists_and_reads_but_cannot_create_or_approve(
    client: TestClient,
) -> None:
    mission_id = _create_mission(client)
    attempt_id = _seed_rejected_attempt(mission_id)
    read = _headers(READ_TOKEN)

    listed = client.get("/api/v1/arc/missions", headers=read)
    assert listed.status_code == 200
    assert listed.json()["missions"][0]["mission_id"] == mission_id
    assert "progress" in listed.json()["missions"][0]
    assert "strategy_code" not in json.dumps(listed.json())

    evidence = client.get(f"/api/v1/arc/missions/{mission_id}/evidence", headers=read)
    assert evidence.status_code == 200
    assert "strategy_code" not in json.dumps(evidence.json())

    detail = client.get(f"/api/v1/arc/missions/{mission_id}/candidates/{attempt_id}", headers=read)
    assert detail.status_code == 200
    assert "class Secret" in detail.json()["strategy_code"]

    assert (
        client.post(
            "/api/v1/arc/missions",
            json={"objective": "no", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
            headers=read,
        ).status_code
        == 403
    )
    for path in (
        f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
        f"/api/v1/arc/missions/{mission_id}/live-approval/revoke",
    ):
        body = (
            {"decision": "reject", "reason": "probe"}
            if path.endswith("decide")
            else {"reason": "probe"}
        )
        assert (
            client.post(path, json=body, headers={**read, "Idempotency-Key": "k-read"}).status_code
            == 403
        )


def test_a_start_scoped_token_creates_and_extends_but_cannot_approve(
    client: TestClient,
) -> None:
    start = _headers(START_TOKEN)
    mission_id = _create_mission(client, START_TOKEN)
    continued = client.post(
        f"/api/v1/arc/missions/{mission_id}/continue",
        json={"extra_candidates": 2},
        headers={**start, "Idempotency-Key": "k-continue"},
    )
    assert continued.status_code == 200
    assert (
        client.post(
            f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
            json={"decision": "reject", "reason": "probe"},
            headers={**start, "Idempotency-Key": "k-start"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/arc/missions/{mission_id}/live-approval/revoke",
            json={"reason": "probe"},
            headers={**start, "Idempotency-Key": "k-revoke"},
        ).status_code
        == 403
    )


def test_no_token_and_no_session_is_401_on_every_arc_route(client: TestClient) -> None:
    mission = "arc_missing"
    probes = [
        client.post(
            "/api/v1/arc/missions",
            json={"objective": "probe", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
        ),
        client.get("/api/v1/arc/missions"),
        client.get("/api/v1/arc/evidence/preflight"),
        client.get(f"/api/v1/arc/missions/{mission}"),
        client.get(f"/api/v1/arc/missions/{mission}/evidence"),
        client.get(f"/api/v1/arc/missions/{mission}/candidates/att_x"),
        client.get(f"/api/v1/arc/missions/{mission}/live-approval"),
        client.post(
            f"/api/v1/arc/missions/{mission}/live-approval/decide",
            json={"decision": "reject", "reason": "probe"},
            headers={"Idempotency-Key": "k1"},
        ),
        client.post(
            f"/api/v1/arc/missions/{mission}/live-approval/revoke",
            json={"reason": "probe"},
            headers={"Idempotency-Key": "k2"},
        ),
    ]
    for response in probes:
        assert response.status_code == 401, (response.request.url, response.status_code)


def test_a_valid_assertion_decides_and_records_the_signed_operator(
    client: TestClient,
) -> None:
    mission_id = _create_mission(client)
    _mark_legacy_mission(mission_id)
    header = _assertion(mission_id=mission_id, decision="reject")
    decided = client.post(
        f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
        json={"decision": "reject", "reason": "not ready"},
        headers={
            "X-Operator-Assertion": header,
            "Idempotency-Key": "k-decide",
            "X-Operator-Id": "forged-name",
        },
    )
    assert decided.status_code == 200, decided.text
    events = client.get(f"/api/v1/arc/missions/{mission_id}", headers=_headers(READ_TOKEN)).json()[
        "events"
    ]
    recorded = [event for event in events if event.get("event_type") == "live_decided"]
    assert recorded
    assert recorded[-1]["payload"]["operator_id"] == "bitpro-admin"
    assert recorded[-1]["payload"]["identity_source"] == "bitpro_signed"


def test_a_tampered_expired_or_mismatched_assertion_records_no_decision(
    client: TestClient,
) -> None:
    mission_id = _create_mission(client)
    other = _create_mission(client)
    valid = _assertion(mission_id=mission_id, decision="reject", idempotency_key="k-bad")
    cases = [
        valid[:-1] + ("0" if valid[-1] != "0" else "1"),
        _assertion(
            mission_id=mission_id,
            decision="reject",
            idempotency_key="k-bad",
            issued_at=int(time.time()) - 400,
        ),
        _assertion(
            mission_id=mission_id,
            decision="reject",
            idempotency_key="k-bad",
            issued_at=int(time.time()) + 120,
        ),
        _assertion(mission_id=other, decision="reject", idempotency_key="k-bad"),
        _assertion(mission_id=mission_id, decision="approve", idempotency_key="k-bad"),
    ]
    for header in cases:
        response = client.post(
            f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
            json={"decision": "reject", "reason": "probe"},
            headers={"X-Operator-Assertion": header, "Idempotency-Key": "k-bad"},
        )
        assert response.status_code == 401, (header[:24], response.status_code)
    events = client.get(f"/api/v1/arc/missions/{mission_id}", headers=_headers(READ_TOKEN)).json()[
        "events"
    ]
    assert not [event for event in events if event.get("event_type") == "live_decided"]


def test_an_empty_assertion_secret_refuses_every_assertion(
    unsigned_client: TestClient,
) -> None:
    mission_id = _create_mission(unsigned_client)
    header = _assertion(mission_id=mission_id, decision="reject")
    response = unsigned_client.post(
        f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
        json={"decision": "reject", "reason": "probe"},
        headers={"X-Operator-Assertion": header, "Idempotency-Key": "k-empty"},
    )
    assert response.status_code == 401
    events = unsigned_client.get(
        f"/api/v1/arc/missions/{mission_id}", headers=_headers(READ_TOKEN)
    ).json()["events"]
    assert not [event for event in events if event.get("event_type") == "live_decided"]


def test_an_admin_session_still_decides_as_hypertrade_session(client: TestClient) -> None:
    _login(client)
    mission_id = client.post(
        "/api/v1/arc/missions",
        json={"objective": "probe", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
    ).json()["mission_id"]
    _mark_legacy_mission(mission_id)
    client.post(
        f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
        json={"decision": "reject", "reason": "probe"},
        headers={"X-Operator-Id": "someone-else", "Idempotency-Key": "k-session"},
    )
    events = client.get(f"/api/v1/arc/missions/{mission_id}").json()["events"]
    decided = [event for event in events if event.get("event_type") == "live_decided"]
    assert decided
    assert decided[-1]["payload"]["operator_id"] == "admin"
    assert decided[-1]["payload"]["identity_source"] == "hypertrade_session"


def test_evidence_view_carries_reason_codes_and_no_strategy_source() -> None:
    ctrl = ARCController(goal=ARCGoalV1(objective="probe", symbols=["ETH-USDT-SWAP"]))
    ctrl.projection.attempts.append(
        ARCCandidateAttemptV1(
            attempt_id="att_a",
            candidate_id="cand_a",
            state="rejected",
            hypothesis="x",
            strategy_code="class MustNotLeak: pass",
            strategy_spec={"family": "donchian_breakout", "direction": "short_only"},
            observed_metrics={
                "out_of_sample_sharpe": 1.64,
                "out_of_sample_trades": 3,
                "win_rate": 0.4,
                "walk_forward_folds": 4,
                "walk_forward_sharpes": [1.5, 0.1, 1.3, 0.2],
                "walk_forward_drawdowns": [0.05, 0.2, 0.04, 0.3],
                "ranking_basis": "out_of_sample",
            },
            reflexion_events=[
                ARCReflexionEventV1(
                    candidate_id="cand_a",
                    failure_class="red_team_attack_failed",
                    reason_codes=["OOS_SAMPLE_TOO_SMALL"],
                    failed_gates=["historical_evidence"],
                    observed_metrics={},
                    negative_constraints=["样本外成交笔数不足"],
                )
            ],
        )
    )
    first = build_evidence_view(ctrl.projection)
    second = build_evidence_view(ctrl.projection)
    dumped = json.dumps(first, sort_keys=True, default=str)
    assert dumped == json.dumps(second, sort_keys=True, default=str)
    assert "MustNotLeak" not in dumped
    assert "strategy_code" not in dumped
    rejected = first["candidates"][0]
    assert rejected["rejections"][0]["code"] == "OOS_SAMPLE_TOO_SMALL"
    assert rejected["family"] == "donchian_breakout"
    assert first["mission"]["progress"]["candidates_used"] == 1


def test_verify_assertion_binds_mission_and_decision() -> None:
    issued_at = int(time.time())
    header = sign_operator_assertion(
        mission_id="arc_a",
        decision="approve",
        operator_id="op",
        idempotency_key="k1",
        issued_at=issued_at,
        secret=ASSERTION_SECRET,
    )
    assert (
        verify_assertion_values(
            header=header,
            mission_id="arc_a",
            decision="approve",
            idempotency_key="k1",
            secret=ASSERTION_SECRET,
            max_age_seconds=300,
            now=issued_at,
        )
        is not None
    )
    assert (
        verify_assertion_values(
            header=header,
            mission_id="arc_b",
            decision="approve",
            idempotency_key="k1",
            secret=ASSERTION_SECRET,
            max_age_seconds=300,
            now=issued_at,
        )
        is None
    )


def test_mission_list_reports_progress_and_awaiting_approval(client: TestClient) -> None:
    mission_id = _create_mission(client)
    listed = client.get("/api/v1/arc/missions", headers=_headers(READ_TOKEN)).json()
    row = next(item for item in listed["missions"] if item["mission_id"] == mission_id)
    assert "candidates_used" in row["progress"]
    assert "max_candidates" in row["progress"]
    assert "awaiting_approval" in row


def _mark_legacy_mission(mission_id: str) -> None:
    # Compatibility coverage for historical missions; new HTTP missions cannot opt out.
    ctrl = get_controller(mission_id)
    assert ctrl is not None and ctrl.projection.goal is not None
    ctrl.projection.goal.paper_review_required = False
    ctrl.apply_event("goal_compiled", {"goal": ctrl.projection.goal.model_dump()})


def test_provider_selection_is_task_local_and_idempotent(client):
    default = client.app.state.active_chat_provider
    headers = {"X-HyperTrade-Service-Token": BOTH_TOKEN}
    created = client.post(
        "/api/v1/arc/missions",
        headers=headers,
        json={"objective": "provider selection", "provider_name": "codex"},
    )
    mission_id = created.json()["mission_id"]
    ctrl = get_controller(mission_id)
    assert ctrl.projection.goal.provider_name == "codex"
    ctrl.apply_event("operator_needed", {"reason": "provider_unavailable"})
    headers["Idempotency-Key"] = "provider-selection"
    payload = {"extra_candidates": 0, "provider_name": "openai"}
    url = f"/api/v1/arc/missions/{mission_id}/continue"
    assert client.post(url, headers=headers, json=payload).status_code == 200
    repeated = client.post(url, headers=headers, json=payload)
    assert repeated.status_code == 200 and repeated.json()["idempotent"]
    assert ctrl.projection.goal.provider_name == "openai"
    assert client.app.state.active_chat_provider == default


def test_signed_paper_review_rejects_stale_assertion_and_records_human(client):
    from hypertrade.arc.paper_review import request_paper_review

    ctrl = ARCController(goal=ARCGoalV1(objective="paper", paper_review_required=True))
    save_mission(ctrl)
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="att_paper",
                candidate_id="candidate_paper",
                hypothesis="test",
                state="validated",
                strategy_code="class X: pass",
                bitpro_strategy_id="445",
                bitpro_backtest_id="450",
                validation_id="val450",
            ).model_dump()
        },
    )
    package = request_paper_review(ctrl)
    digest = package["package_hash"]
    payload = {"decision": "reject", "reason": "reviewed", "package_hash": digest}
    signed = _assertion(mission_id=ctrl.mission_id, decision=f"paper:reject:{digest}")
    headers = {"X-Operator-Assertion": signed, "Idempotency-Key": "k-decide"}
    url = f"/api/v1/arc/missions/{ctrl.mission_id}/paper-review/decide"
    bad = client.post(url, headers=headers, json={**payload, "package_hash": "b" * 64})
    assert bad.status_code == 401
    result = client.post(url, headers=headers, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "rejected"
    assert result.json()["decision"]["identity_source"] == "bitpro_signed"
