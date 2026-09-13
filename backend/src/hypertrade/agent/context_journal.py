"""Private, bounded recovery snapshots. No operator API exposes this store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from hypertrade.agent.compaction import canonical, digest, sanitize_context
from hypertrade.db import Database, ProviderContextRecord

SNAPSHOT_TTL = timedelta(days=30)


def save_context_record(db: Database, run_id: str, record: dict[str, Any]) -> str:
    sanitized = sanitize_context(record)
    if len(canonical(sanitized).encode()) > 2 * 1024 * 1024 + 128 * 1024:
        raise ValueError("context_journal_size_limit")
    snapshot_available = (
        sanitized.get("manifest", {}).get("status") == "ready"
        and "request_messages" in sanitized
        and "tools" in sanitized
    )
    now = datetime.now(UTC)
    with db.session() as session:
        # Expire bounded recovery copies, retaining audit manifests and hashes.
        # Original business events and tool receipts are never modified here.
        expired = session.scalars(
            select(ProviderContextRecord)
            .where(ProviderContextRecord.expires_at <= now)
            .where(ProviderContextRecord.snapshot_available.is_(True))
            .limit(100)
        ).all()
        for old in expired:
            old.snapshot_available = False
            if "request_messages" in old.record_json or "tools" in old.record_json:
                old.record_json = {
                    "manifest": old.record_json["manifest"],
                    "snapshot_expired": True,
                }
        row = ProviderContextRecord(
            run_id=run_id,
            snapshot_hash=digest(sanitized),
            manifest_hash=digest(sanitized["manifest"]),
            record_json=sanitized,
            expires_at=now + SNAPSHOT_TTL if snapshot_available else now,
            snapshot_available=snapshot_available,
        )
        session.add(row)
        session.flush()
        return row.id


def load_context_record(db: Database, run_id: str, record_id: str) -> dict[str, Any]:
    # Internal-only and owner-bound; expired snapshots require original events,
    # never an invented reconstruction or a provider/effect retry.
    with db.session() as session:
        row = session.get(ProviderContextRecord, record_id)
        if row is None or row.run_id != run_id:
            raise KeyError("context_record_not_found")
        if not row.snapshot_available or row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
            raise ValueError("context_snapshot_expired")
        if (
            digest(row.record_json) != row.snapshot_hash
            or digest(row.record_json["manifest"]) != row.manifest_hash
        ):
            raise ValueError("context_record_hash_mismatch")
        return dict(row.record_json)
