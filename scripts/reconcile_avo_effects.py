#!/usr/bin/env python3
"""Reconcile audited failed development effects without replaying external actions.

Input is a JSON array of {pending_sha256, receipt}; dry-run unless --apply.
Receipts must come from a fresh external read-only audit, including all active jobs.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from hypertrade.arc.controller import ARCController, ARCEventV1
from hypertrade.arc.store import configure_store, get_controller, research_lock
from hypertrade.config import get_settings
from hypertrade.db import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("/app/data/backups"))
    args = parser.parse_args()
    configure_store(Database(str(get_settings().database_url)))
    for payload in json.loads(args.receipts.read_text()):
        mission_id = payload["receipt"]["mission_id"]
        with research_lock(mission_id) as check_owner:
            if check_owner is None:
                raise RuntimeError(f"research owner active: {mission_id}")
            ctrl = get_controller(mission_id)
            if ctrl is None:
                raise ValueError(f"mission missing: {mission_id}")
            if ctrl.projection.avo.get("effect_reconciliation") == payload:
                print(json.dumps({"mission_id": mission_id, "status": "already_reconciled"}))
                continue
            # Validate the complete reducer before creating a backup or committing.
            probe = ARCController(mission_id=mission_id)
            probe.rebase(ctrl.projection.model_copy(deep=True), ctrl.revision)
            probe.absorb(
                ARCEventV1(
                    mission_id=mission_id, event_type="avo_effect_reconciled", payload=payload
                )
            )
            backup = None
            if args.apply:
                args.backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                backup = args.backup_dir / f"{mission_id}-{stamp}.json"
                backup.touch(mode=0o600, exist_ok=False)
                backup.write_text(ctrl.projection.model_dump_json())
                check_owner()
                ctrl.apply_event("avo_effect_reconciled", payload)
                after = get_controller(mission_id)
                assert after is not None and after.projection.state == "failed"
                assert after.projection.avo.get("pending") is None
            print(
                json.dumps(
                    {
                        "mission_id": mission_id,
                        "status": "reconciled" if args.apply else "verified_dry_run",
                        "backup": str(backup) if backup else None,
                    }
                )
            )


if __name__ == "__main__":
    main()
