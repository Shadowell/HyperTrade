"""Dynamic Security Token Lifecycle and Rotation Management Service.

Provides cryptographic token generation, SHA-256 hashed storage, smooth grace-period
rotation, active revocation, and expiration pre-warning auditing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TokenStatus(StrEnum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class TokenRecord:
    token_id: str
    token_label: str
    token_hash: str
    token_prefix: str
    scopes: list[str]
    created_at: str
    expires_at: str | None
    revoked_at: str | None = None
    revocation_reason: str | None = None
    grace_until: str | None = None
    usage_count: int = 0
    last_used_at: str | None = None

    def compute_status(self, now: datetime | None = None) -> TokenStatus:
        curr = now or datetime.now(UTC)
        if self.revoked_at is not None:
            return TokenStatus.REVOKED

        if self.grace_until is not None:
            grace_dt = datetime.fromisoformat(self.grace_until)
            if curr > grace_dt:
                return TokenStatus.EXPIRED

        if self.expires_at is not None:
            exp_dt = datetime.fromisoformat(self.expires_at)
            if curr > exp_dt:
                return TokenStatus.EXPIRED
            if exp_dt - curr <= timedelta(days=7):
                return TokenStatus.EXPIRING_SOON

        return TokenStatus.ACTIVE

    def to_public_dict(self) -> dict[str, Any]:
        """Return public representation without leaking token_hash."""
        status = self.compute_status()
        return {
            "token_id": self.token_id,
            "token_label": self.token_label,
            "token_prefix": self.token_prefix,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
            "grace_until": self.grace_until,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at,
            "status": status.value,
        }


class TokenRotationService:
    """Manages secure API service tokens with persistent hashed records and rotation."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path else None
        self._tokens: dict[str, TokenRecord] = {}
        self._load()

    @staticmethod
    def hash_token(plaintext: str) -> str:
        return hashlib.sha256(plaintext.strip().encode("utf-8")).hexdigest()

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            with open(self._storage_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for item in data.values():
                    if isinstance(item, dict) and "token_id" in item:
                        rec = TokenRecord(**item)
                        self._tokens[rec.token_id] = rec
        except Exception as exc:
            logger.warning("Failed to load security tokens from %s: %s", self._storage_path, exc)

    def _save(self) -> None:
        if not self._storage_path:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {tid: asdict(rec) for tid, rec in self._tokens.items()}
            # Atomic write via temp file
            dir_name = self._storage_path.parent
            with tempfile.NamedTemporaryFile(
                "w", dir=dir_name, delete=False, encoding="utf-8"
            ) as tf:
                json.dump(serializable, tf, indent=2)
                temp_name = tf.name
            os.replace(temp_name, self._storage_path)
        except Exception as exc:
            logger.error("Failed to persist security tokens to %s: %s", self._storage_path, exc)

    def issue_token(
        self,
        *,
        label: str,
        scopes: Sequence[str],
        ttl_days: int | None = 30,
    ) -> tuple[TokenRecord, str]:
        """Issue a new random token, store its hash, and return the record with plaintext token."""
        token_id = f"tok_{uuid.uuid4().hex[:12]}"
        random_suffix = secrets.token_urlsafe(32)
        plaintext = f"ht_sec_{random_suffix}"
        token_hash = self.hash_token(plaintext)
        token_prefix = f"ht_sec_{random_suffix[:6]}..."

        now = datetime.now(UTC)
        created_at = now.isoformat()
        expires_at = (now + timedelta(days=ttl_days)).isoformat() if ttl_days else None

        record = TokenRecord(
            token_id=token_id,
            token_label=label,
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=list(scopes),
            created_at=created_at,
            expires_at=expires_at,
        )
        self._tokens[token_id] = record
        self._save()
        return record, plaintext

    def verify_token(self, plaintext: str) -> TokenRecord | None:
        """Verify token authenticity and status. Increment usage if valid."""
        if not plaintext or not isinstance(plaintext, str):
            return None
        hashed = self.hash_token(plaintext)
        now = datetime.now(UTC)

        for record in self._tokens.values():
            if hmac.compare_digest(record.token_hash, hashed):
                status = record.compute_status(now)
                if status in (TokenStatus.REVOKED, TokenStatus.EXPIRED):
                    return None
                # Valid token: update usage
                record.usage_count += 1
                record.last_used_at = now.isoformat()
                self._save()
                return record
        return None

    def rotate_token(
        self,
        token_id: str,
        *,
        grace_period_hours: float = 24.0,
        ttl_days: int | None = 30,
    ) -> tuple[TokenRecord, TokenRecord, str]:
        """Rotate token: existing token remains valid until grace_until, issues new token."""
        old_record = self._tokens.get(token_id)
        if not old_record:
            raise KeyError(f"Token with id '{token_id}' not found")

        now = datetime.now(UTC)
        if old_record.revoked_at is not None:
            raise ValueError(f"Cannot rotate revoked token '{token_id}'")

        grace_until = (now + timedelta(hours=grace_period_hours)).isoformat()
        old_record.grace_until = grace_until

        new_record, new_plaintext = self.issue_token(
            label=old_record.token_label,
            scopes=old_record.scopes,
            ttl_days=ttl_days,
        )
        self._save()
        return old_record, new_record, new_plaintext

    def revoke_token(self, token_id: str, *, reason: str = "manual_revocation") -> TokenRecord:
        """Immediately revoke a token."""
        record = self._tokens.get(token_id)
        if not record:
            raise KeyError(f"Token with id '{token_id}' not found")
        now = datetime.now(UTC)
        record.revoked_at = now.isoformat()
        record.revocation_reason = reason
        self._save()
        return record

    def list_tokens(self) -> list[TokenRecord]:
        """List all tokens sorted by creation timestamp descending."""
        records = list(self._tokens.values())
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records

    def audit_expiring_tokens(self, *, warning_threshold_days: int = 7) -> list[TokenRecord]:
        """List active tokens that are expiring within the warning threshold."""
        now = datetime.now(UTC)
        threshold = now + timedelta(days=warning_threshold_days)
        expiring = []
        for r in self._tokens.values():
            if r.revoked_at is not None:
                continue
            if r.expires_at is not None:
                exp_dt = datetime.fromisoformat(r.expires_at)
                if now < exp_dt <= threshold:
                    expiring.append(r)
        return expiring
