from hypertrade.arc.variant_status import read_variant_status
from hypertrade.db import ArcMission, ArcMissionEvent, Database
from sqlalchemy import event


def test_summary_is_identity_bound_and_does_not_load_full_projection() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        for mid, parent, target in [
            ("match", 513, "bitpro"),
            ("other", 333, "bitpro"),
            ("market", 513, "quantlab"),
        ]:
            session.add(
                ArcMission(
                    mission_id=mid,
                    state="needs_operator",
                    projection_json={
                        "goal": {
                            "platform": target,
                            "evolution_context": {"source_strategy_id": parent},
                        },
                        "avo": {
                            "messages": ["large transcript"],
                            "development": {
                                "a": {
                                    "bitpro_strategy_id": "546",
                                    "passed": False,
                                    "reasons": ["negative return"],
                                }
                            },
                        },
                    },
                )
            )
        session.add(
            ArcMissionEvent(
                mission_id="match",
                seq=1,
                event_id="e1",
                event_type="operator_needed",
                event_json={
                    "payload": {
                        "reason": "avo_wall_budget_exhausted",
                        "message": "研究时间预算已用尽",
                    }
                },
            )
        )
        session.commit()
    statements: list[str] = []
    event.listen(
        db.engine,
        "before_cursor_execute",
        lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt),
    )
    result = read_variant_status(db, 513, 546)
    assert result["mission_id"] == "match"
    assert result["development"] == {"passed": False, "reasons": ["negative return"]}
    assert result["blocked_reason"]["reason"] == "avo_wall_budget_exhausted"
    assert len(statements) == 2
    assert all("LIMIT" in stmt for stmt in statements)
    assert read_variant_status(db, 513, 547)["status"] == "not_found"
    assert read_variant_status(db, 999)["status"] == "not_found"
    with db.session() as session:
        session.get(ArcMission, "match").state = "researching"
        session.commit()
    assert read_variant_status(db, 513, 546)["blocked_reason"] is None
