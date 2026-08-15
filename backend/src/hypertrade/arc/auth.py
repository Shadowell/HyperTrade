"""Machine and human identity for the ARC external surface.

A service token may start missions and read everything. It may never approve one:
``ARCScope`` has no approve member, so no token value can carry that capability.
Approval is a verified human — either a HyperTrade admin session or a BitPro-signed
operator assertion bound to the mission, decision, and idempotency key of the request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer

from hypertrade.config import Settings

SESSION_COOKIE = "hypertrade_session"
SERVICE_TOKEN_HEADER = "X-HyperTrade-Service-Token"
OPERATOR_ASSERTION_HEADER = "X-Operator-Assertion"
_FUTURE_SKEW_SECONDS = 60
_TOKEN_ENTRY = re.compile(
    r"^(?P<label>.+):(?P<scopes>(?:arc:(?:read|start)\+)*arc:(?:read|start)):"
    r"(?P<digest>[0-9a-fA-F]{64})$"
)


class ARCScope(StrEnum):
    READ = "arc:read"
    START = "arc:start"
    # No approve scope exists. Approval is not a token capability.


@dataclass(frozen=True)
class ServicePrincipal:
    label: str
    scopes: frozenset[ARCScope]


@dataclass(frozen=True)
class OperatorIdentity:
    operator_id: str
    identity_source: Literal["hypertrade_session", "bitpro_signed"]


def hash_service_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def parse_service_tokens(raw: str) -> list[tuple[ServicePrincipal, str]]:
    """Return ``(principal, digest)`` pairs from the configured token catalog."""
    principals: list[tuple[ServicePrincipal, str]] = []
    for entry in raw.split(","):
        match = _TOKEN_ENTRY.match(entry.strip())
        if match is None:
            continue
        scopes = frozenset(ARCScope(item) for item in match.group("scopes").split("+") if item)
        if not scopes:
            continue
        principals.append(
            (
                ServicePrincipal(label=match.group("label"), scopes=scopes),
                match.group("digest").lower(),
            )
        )
    return principals


def _settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    from hypertrade.config import get_settings

    return get_settings()


def resolve_admin_session(request: Request) -> str | None:
    """Read the verified HyperTrade admin identity off the session cookie.

    Writes ``request.state.admin_user`` so later handlers see the same identity
    ``require_admin`` would have set. A caller-supplied name is never consulted.
    """
    cached = str(getattr(request.state, "admin_user", "") or "")
    if cached:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    settings = _settings(request)
    try:
        username = URLSafeSerializer(settings.session_secret, salt="hypertrade-session").loads(
            token
        )
    except BadSignature:
        return None
    if username != settings.admin_username:
        return None
    request.state.admin_user = str(username)
    return str(username)


def resolve_service_principal(request: Request) -> ServicePrincipal | None:
    """Hash ``X-HyperTrade-Service-Token`` and match it against configured digests."""
    provided = str(request.headers.get(SERVICE_TOKEN_HEADER, "") or "").strip()
    if not provided:
        return None
    digest = hash_service_token(provided)
    for principal, stored in parse_service_tokens(_settings(request).arc_service_tokens):
        if hmac.compare_digest(digest, stored):
            request.state.service_principal = principal
            return principal
    return None


def require_scope(scope: ARCScope) -> Callable[[Request], None]:
    """401 when nobody authenticated; 403 when the principal lacks ``scope``.

    An admin session is treated as holding every defined scope so a human on the
    HyperTrade console keeps working. A service token is checked against its
    declared scopes only.
    """

    def dependency(request: Request) -> None:
        if resolve_admin_session(request):
            return
        principal = resolve_service_principal(request)
        if principal is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if scope not in principal.scopes:
            raise HTTPException(status_code=403, detail="Forbidden")

    return dependency


def reject_token_only_approval(request: Request) -> None:
    """First-line gate on decide/revoke: tokens cannot approve, silence is 401."""
    if resolve_admin_session(request):
        return
    if str(request.headers.get(OPERATOR_ASSERTION_HEADER, "") or "").strip():
        return
    if resolve_service_principal(request) is not None:
        raise HTTPException(status_code=403, detail="Forbidden")
    raise HTTPException(status_code=401, detail="Not authenticated")


def sign_operator_assertion(
    *,
    mission_id: str,
    decision: str,
    operator_id: str,
    idempotency_key: str,
    issued_at: int,
    secret: str,
) -> str:
    """Produce ``v1:{issued_at}:{operator_id_b64url}:{signature_hex}``.

    The signed payload is reconstructed by the verifier from the request, not
    from this header, so an assertion captured for one mission cannot authorize
    another and an approve cannot be replayed as a reject.
    """
    payload = _assertion_payload(
        mission_id=mission_id,
        decision=decision,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        issued_at=issued_at,
    )
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    encoded_operator = base64.urlsafe_b64encode(operator_id.encode("utf-8")).decode("ascii")
    return f"v1:{issued_at}:{encoded_operator}:{signature.hexdigest()}"


def verify_assertion_values(
    *,
    header: str,
    mission_id: str,
    decision: str,
    idempotency_key: str,
    secret: str,
    max_age_seconds: int,
    now: int | None = None,
) -> OperatorIdentity | None:
    """Verify a signed assertion. Empty secret refuses every assertion."""
    if not secret:
        return None
    parts = header.strip().split(":")
    if len(parts) != 4 or parts[0] != "v1":
        return None
    try:
        issued_at = int(parts[1])
        operator_id = base64.urlsafe_b64decode(parts[2].encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError):
        return None
    clock = int(now if now is not None else time.time())
    if issued_at > clock + _FUTURE_SKEW_SECONDS:
        return None
    if clock - issued_at > max(1, int(max_age_seconds)):
        return None
    expected = sign_operator_assertion(
        mission_id=mission_id,
        decision=decision,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        issued_at=issued_at,
        secret=secret,
    )
    if not hmac.compare_digest(header.strip(), expected):
        return None
    return OperatorIdentity(operator_id=operator_id, identity_source="bitpro_signed")


def verify_operator_assertion(
    request: Request,
    *,
    mission_id: str,
    decision: str,
    idempotency_key: str,
) -> OperatorIdentity | None:
    """Verify ``X-Operator-Assertion`` against the request it claims to authorize."""
    header = str(request.headers.get(OPERATOR_ASSERTION_HEADER, "") or "").strip()
    if not header:
        return None
    settings = _settings(request)
    return verify_assertion_values(
        header=header,
        mission_id=mission_id,
        decision=decision,
        idempotency_key=idempotency_key,
        secret=settings.arc_operator_assertion_secret,
        max_age_seconds=settings.arc_operator_assertion_max_age_seconds,
    )


def _assertion_payload(
    *,
    mission_id: str,
    decision: str,
    operator_id: str,
    idempotency_key: str,
    issued_at: int,
) -> str:
    return f"v1|{mission_id}|{decision}|{operator_id}|{idempotency_key}|{issued_at}"
