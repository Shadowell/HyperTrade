"""Read-only, bounded projection for a strategy card; never hydrate mission journals."""

from typing import Any

from sqlalchemy import String, cast, select

from hypertrade.db import ArcMission, ArcMissionEvent, Database


def read_variant_status(
    database: Database, source_strategy_id: int, candidate_strategy_id: int | None = None
) -> dict[str, Any]:
    projection = ArcMission.projection_json
    with database.session() as session:
        rows = session.execute(
            select(
                ArcMission.mission_id,
                ArcMission.state,
                ArcMission.updated_at,
                projection["avo"]["development"],
                projection["paper_review"]["strategy"]["bitpro_strategy_id"],
            )
            .where(
                projection["goal"]["platform"].as_string() == "bitpro",
                cast(
                    projection["goal"]["evolution_context"]["source_strategy_id"].as_string(),
                    String,
                )
                == str(source_strategy_id),
            )
            .order_by(ArcMission.updated_at.desc(), ArcMission.mission_id.desc())
            .limit(100)
        ).all()
        for mission_id, state, updated_at, development, approved_id in rows:
            results = list(development.values()) if isinstance(development, dict) else []
            result = next(
                (
                    item
                    for item in reversed(results)
                    if isinstance(item, dict)
                    and (
                        candidate_strategy_id is None
                        or str(item.get("bitpro_strategy_id")) == str(candidate_strategy_id)
                    )
                ),
                None,
            )
            if (
                candidate_strategy_id is not None
                and result is None
                and str(approved_id) != str(candidate_strategy_id)
            ):
                continue
            blocker = None
            if state in {"needs_operator", "failed", "paused"}:
                event = session.execute(
                    select(ArcMissionEvent.event_json["payload"], ArcMissionEvent.created_at)
                    .where(
                        ArcMissionEvent.mission_id == mission_id,
                        ArcMissionEvent.event_type.in_(["operator_needed", "mission_failed"]),
                    )
                    .order_by(ArcMissionEvent.seq.desc())
                    .limit(1)
                ).first()
                if event and isinstance(event[0], dict):
                    blocker = {
                        "reason": str(event[0].get("reason") or ""),
                        "message": str(event[0].get("message") or "")[:300],
                    }
            return {
                "status": "found",
                "source_strategy_id": source_strategy_id,
                "candidate_strategy_id": candidate_strategy_id,
                "mission_id": mission_id,
                "state": state,
                "updated_at": updated_at.isoformat(),
                "development": {
                    "passed": result.get("passed"),
                    "reasons": result.get("reasons", []),
                }
                if result
                else None,
                "blocked_reason": blocker,
            }
    return {
        "status": "not_found",
        "source_strategy_id": source_strategy_id,
        "candidate_strategy_id": candidate_strategy_id,
        "search_limit": 100,
    }
