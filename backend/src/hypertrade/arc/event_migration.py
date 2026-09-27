"""Move inline mission events into ``arc_mission_events``; idempotent, verified, reversible.

Each mission is handled in its own transaction under its row lock, so a concurrent api or
worker commit waits and then continues on the migrated row. The logical projection
(merged events plus every other field) is hashed before and after; any difference
aborts that mission's transaction. ``revision`` is not bumped: the layout changes, the
mission does not. ``--dry-run`` performs the same writes and verification, then rolls back.

    python -m hypertrade.arc.event_migration migrate [--dry-run] [--mission ID ...]
    python -m hypertrade.arc.event_migration rollback [--dry-run] [--mission ID ...]
    python -m hypertrade.arc.event_migration verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from hypertrade.arc.store import load_projection
from hypertrade.db import ArcMission, ArcMissionEvent, Database


class _Mismatch(RuntimeError):
    pass


def logical_digest(session: Session, row: ArcMission) -> tuple[str, int]:
    projection = load_projection(session, row).model_dump(mode="json")
    encoded = json.dumps(projection, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest(), len(projection["events"])


def _stored(session: Session, mission_id: str) -> list[dict[str, Any]]:
    return [
        dict(value)
        for value in session.scalars(
            select(ArcMissionEvent.event_json)
            .where(ArcMissionEvent.mission_id == mission_id)
            .order_by(ArcMissionEvent.seq)
        )
    ]


def _move_inline(session: Session, row: ArcMission) -> int:
    stored = _stored(session, row.mission_id)
    if int(row.event_count or 0) != len(stored):
        raise _Mismatch("event_count_does_not_match_journal")
    known = {event["event_id"] for event in stored}
    raw = dict(row.projection_json or {})
    pending = [e for e in raw.get("events") or [] if e.get("event_id") not in known]
    for seq, event in enumerate(pending, start=len(stored) + 1):
        session.add(
            ArcMissionEvent(
                mission_id=row.mission_id,
                seq=seq,
                event_id=event["event_id"],
                event_type=event["event_type"],
                event_json=event,
            )
        )
    if raw.get("events"):
        row.projection_json = {**raw, "events": []}
    row.event_count = len(stored) + len(pending)
    return len(pending)


def _fold_back(session: Session, row: ArcMission) -> int:
    stored = _stored(session, row.mission_id)
    known = {event["event_id"] for event in stored}
    raw = dict(row.projection_json or {})
    inline = [e for e in raw.get("events") or [] if e.get("event_id") not in known]
    row.projection_json = {**raw, "events": stored + inline}
    row.event_count = 0
    session.execute(delete(ArcMissionEvent).where(ArcMissionEvent.mission_id == row.mission_id))
    return len(stored)


def _run(
    db: Database,
    change: Callable[[Session, ArcMission], int],
    *,
    dry_run: bool,
    mission_ids: Sequence[str] | None,
) -> dict[str, Any]:
    with db.session() as session:
        ids = list(mission_ids or session.scalars(select(ArcMission.mission_id)).all())
    per_mission: dict[str, dict[str, Any]] = {}
    changed_total = 0
    for mission_id in ids:
        with db.session() as session:
            row = session.get(ArcMission, mission_id, with_for_update=True)
            if row is None:
                per_mission[mission_id] = {"error": "mission_not_found"}
                continue
            revision = int(row.revision or 0)
            before, events = logical_digest(session, row)
            try:
                changed = change(session, row)
                session.flush()
                after, after_events = logical_digest(session, row)
                if (after, after_events, int(row.revision or 0)) != (before, events, revision):
                    raise _Mismatch("logical_projection_changed")
            except _Mismatch as exc:
                session.rollback()
                per_mission[mission_id] = {"error": str(exc), "before_sha256": before}
                continue
            if dry_run:
                session.rollback()
            changed_total += changed
            per_mission[mission_id] = {
                "events": events,
                "changed": changed,
                "revision": revision,
                "before_sha256": before,
                "after_sha256": after,
            }
    return {
        "dry_run": dry_run,
        "missions": len(ids),
        "per_mission": per_mission,
        "verified": all("error" not in item for item in per_mission.values()),
        "changed_events": changed_total,
    }


def migrate(
    db: Database, *, dry_run: bool = False, mission_ids: Sequence[str] | None = None
) -> dict[str, Any]:
    report = _run(db, _move_inline, dry_run=dry_run, mission_ids=mission_ids)
    report["moved_events"] = report.pop("changed_events")
    return report


def rollback(
    db: Database, *, dry_run: bool = False, mission_ids: Sequence[str] | None = None
) -> dict[str, Any]:
    report = _run(db, _fold_back, dry_run=dry_run, mission_ids=mission_ids)
    report["restored_events"] = report.pop("changed_events")
    return report


def verify(db: Database) -> dict[str, Any]:
    """Read-only layout census plus per-mission logical digests."""
    with db.session() as session:
        rows = session.scalars(select(ArcMission)).all()
        per_mission = {}
        for row in rows:
            digest, events = logical_digest(session, row)
            per_mission[row.mission_id] = {
                "events": events,
                "journalled": int(row.event_count or 0),
                "inline": len((row.projection_json or {}).get("events") or []),
                "revision": int(row.revision or 0),
                "sha256": digest,
            }
        journal_rows = session.scalar(select(func.count()).select_from(ArcMissionEvent))
    return {
        "missions": len(per_mission),
        "events": sum(item["events"] for item in per_mission.values()),
        "journal_rows": int(journal_rows or 0),
        "inline_events": sum(item["inline"] for item in per_mission.values()),
        "per_mission": per_mission,
    }


def main(argv: Sequence[str] | None = None) -> int:
    from hypertrade.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["migrate", "rollback", "verify"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mission", action="append", default=None)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)
    db = Database(args.database_url or get_settings().database_url)
    if args.action == "verify":
        report = verify(db)
    elif args.action == "migrate":
        report = migrate(db, dry_run=args.dry_run, mission_ids=args.mission)
    else:
        report = rollback(db, dry_run=args.dry_run, mission_ids=args.mission)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("verified", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
