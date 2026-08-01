from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import AgentToolCall
from hypertrade.main import create_app
from hypertrade.research.validation_v2 import UnifiedStrategyValidationService
from sqlalchemy import func, select
from validation_v2_fixtures import seeded_validation_candidate, validation_request


def test_evolution_and_discovery_candidates_share_required_gates() -> None:
    decisions = []
    for kind in ("evolution", "discovery"):
        db, refs = seeded_validation_candidate(kind)
        decision = UnifiedStrategyValidationService(db).validate(
            validation_request(refs, key=f"validation-{kind}-shared-gates"), actor="test"
        )
        decisions.append(decision)
        assert decision["status"] == "validated"
        assert decision["strategy_card_snapshot"]["validation_status"] == "passed"
        assert decision["id"] in decision["strategy_card_snapshot"]["source_refs"]["validation_ids"]
        assert not any(decision["mutation_boundary"].values())
        with db.session() as session:
            assert session.scalar(select(func.count(AgentToolCall.id))) == 0

    evolution_gates = set(decisions[0]["gates"]) - {"novelty_falsification"}
    discovery_gates = set(decisions[1]["gates"]) - {"novelty_falsification"}
    assert evolution_gates == discovery_gates
    assert decisions[1]["gates"]["novelty_falsification"]["required"] is True


def test_high_return_cannot_hide_oos_cost_or_parameter_failure() -> None:
    db, refs = seeded_validation_candidate("evolution")
    result = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            evidence_changes={
                "locked_oos_return": Decimal("100"),
                "cost_stress_return": Decimal("-1"),
                "parameter_neighbor_returns": [Decimal("0.1")],
            },
        ),
        actor="test",
    )

    assert result["status"] == "rejected"
    assert result["gates"]["cost_stress"]["outcome"] == "failed"
    assert result["gates"]["parameter_stability"]["outcome"] == "failed"


def test_missing_metrics_are_needs_data_and_ex_post_regime_needs_review() -> None:
    db, refs = seeded_validation_candidate("evolution")
    missing = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            key="validation-missing-metric",
            evidence_changes={"deflated_sharpe": None},
        ),
        actor="test",
    )
    assert missing["status"] == "needs_data"

    db, refs = seeded_validation_candidate("evolution")
    review = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            key="validation-ex-post-regime",
            evidence_changes={"regime_label_mode": "ex_post_research"},
        ),
        actor="test",
    )
    assert review["status"] == "needs_review"


def test_replay_is_deterministic_and_source_change_appends_version() -> None:
    db, refs = seeded_validation_candidate("evolution")
    service = UnifiedStrategyValidationService(db)
    first = service.validate(validation_request(refs), actor="test")
    replay = service.validate(
        validation_request(refs, key="another-key-same-fingerprint"), actor="test"
    )
    changed = service.validate(
        validation_request(
            refs,
            key="validation-new-source-version",
            evidence_changes={"source_hash": "sha256:" + "d" * 64},
        ),
        actor="test",
    )

    assert replay["id"] == first["id"]
    assert replay["replay"] == "fingerprint"
    assert changed["validation_version"] == 2
    assert service.diff(first["id"], changed["id"])["equal"] is False


def test_unified_validation_api_is_authenticated_and_read_only(tmp_path) -> None:
    db, refs = seeded_validation_candidate("evolution")
    recorded = UnifiedStrategyValidationService(db).validate(validation_request(refs), actor="test")
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                KNOWLEDGE_DIR=tmp_path,
                DEEPSEEK_API_KEY="",
            ),
            db=db,
        )
    )
    assert client.get("/api/research/unified-validations").status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    listed = client.get("/api/research/unified-validations")
    shown = client.get(f"/api/research/unified-validations/{recorded['id']}")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == recorded["id"]
    assert shown.status_code == 200
