"""Deterministic provider views; the journal remains the source of truth.

UTF-8 bytes plus framing is a conservative input-token allowance for byte-based
provider tokenizers (including CJK), not billing or a reasoning/output budget.
Only known bulk data fields may be elided; all other evidence stays verbatim.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

VERSION = "compaction.v1"
_BULK = {"candles", "ohlcv", "equity_curve"}
_UNRESOLVED = (
    "pending",
    "effect_unknown",
    "unknown_result",
    "approval",
    "budget",
    "审批",
    "待确认",
)


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def request_size(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]], model: str = ""
) -> int:
    # Include complete message fields, schemas, model and ample adapter framing.
    return (
        len(canonical({"messages": messages, "tools": tools, "model": model}).encode())
        + 1024
        + 64 * len(messages)
    )


class ContextBlocked(RuntimeError):
    def __init__(self, reason: str, record: dict[str, Any]) -> None:
        super().__init__(reason)
        self.record = record


@dataclass(frozen=True)
class RequestCompaction:
    messages: list[dict[str, Any]]
    compacted_groups: int
    manifest: dict[str, Any]
    record: dict[str, Any]


def _groups(messages: list[dict[str, Any]]) -> list[list[int]]:
    groups: list[list[int]] = []
    seen: set[str] = set()
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message.get("role")
        if message.get("content") is not None and not isinstance(message.get("content"), str):
            raise ValueError("invalid_role_or_content")
        if role not in {"system", "developer", "user", "assistant", "tool"}:
            raise ValueError("invalid_role")
        if role == "tool":
            raise ValueError("tool_protocol_orphan")
        calls = message.get("tool_calls")
        group = [index]
        index += 1
        if calls:
            if role != "assistant" or not isinstance(calls, list):
                raise ValueError("tool_protocol_calls")
            ids = []
            for call in calls:
                if (
                    not isinstance(call, dict)
                    or not isinstance(call.get("id"), str)
                    or not call["id"]
                ):
                    raise ValueError("tool_protocol_id")
                function = call.get("function")
                if (
                    not isinstance(function, dict)
                    or not isinstance(function.get("arguments"), str)
                    or not isinstance(function.get("name"), str)
                    or not function["name"]
                ):
                    raise ValueError("tool_protocol_arguments")
                args = json.loads(function["arguments"])
                canonical(args)
                if not isinstance(args, dict):
                    raise ValueError("tool_protocol_arguments")
                ids.append(call["id"])
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                raise ValueError("tool_protocol_duplicate")
            seen.update(ids)
            results = []
            while index < len(messages) and messages[index].get("role") == "tool":
                if not isinstance(messages[index].get("content"), str):
                    raise ValueError("tool_protocol_result_content")
                results.append(messages[index].get("tool_call_id"))
                group.append(index)
                index += 1
            if sorted(results, key=str) != sorted(ids):
                raise ValueError("tool_protocol_pending_or_mismatch")
        groups.append(group)
    return groups


def _numeric_scalar(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        Decimal(value)
    except InvalidOperation:
        return False
    return True


def _numeric_series(value: Any) -> bool:
    return isinstance(value, list) and all(
        _numeric_scalar(item) or isinstance(item, list) and _numeric_series(item) for item in value
    )


def _source_refs(value: Any, *, key: str = "") -> list[str]:
    refs: list[str] = []
    normalized = re.sub(r"[^a-z]", "", key.lower())
    is_ref = normalized == "id" or normalized.endswith(("id", "ids", "ref", "refs", "hash"))
    if is_ref and isinstance(value, (str, int)) and not isinstance(value, bool):
        refs.append(str(value))
    elif isinstance(value, dict):
        for child_key, child in value.items():
            refs.extend(_source_refs(child, key=child_key))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_source_refs(child, key=key if is_ref else ""))
    return sorted(set(refs))


def _bulk_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or len(canonical(value)) <= 512:
        return None
    if not _numeric_series(value) and not all(isinstance(item, dict) for item in value):
        return None
    refs = _source_refs(value)
    return {
        "compacted_bulk": True,
        "sha256": digest(value),
        "items": len(value),
        "source_refs": refs,
        "evidence_available": "source_event_journal",
        "not_full_evidence": True,
    }


def _bulk_view(value: Any, key: str = "") -> Any:
    # Free text or objects may contain source IDs/instructions, so only numeric
    # series can be reduced. All identity, decision and outcome fields survive.
    if key in _BULK:
        summary = _bulk_summary(value)
        if summary is not None:
            return summary
    if isinstance(value, dict):
        return {k: _bulk_view(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_bulk_view(v) for v in value]
    return value


_SECRET_KEYS = {
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "authorization",
    "cookie",
    "privatekey",
    "clientsecret",
    "token",
}
_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+|(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)
_URL_AUTH = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@", re.I)


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", key.lower())
    return normalized in _SECRET_KEYS or normalized.endswith(
        ("apikey", "secret", "password", "accesstoken", "refreshtoken", "privatekey")
    )


def sanitize_context(value: Any) -> Any:
    """One redaction path for provider input and its private recovery snapshot."""
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("invalid_context_keys")
        return {
            k: "[REDACTED]" if _secret_key(k) else sanitize_context(v) for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize_context(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            sanitized = sanitize_context(parsed)
            if sanitized != parsed:
                return canonical(sanitized)
        redacted = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", value)
        redacted = _URL_AUTH.sub(r"\1[REDACTED]@", redacted)
        return _SECRET_TEXT.sub(lambda m: m.group(1) + "[REDACTED]", redacted)
    return value


def compact_request(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    max_tokens: int = 64000,
    model: str = "",
    keep_recent_groups: int = 1,
) -> RequestCompaction:
    manifest: dict[str, Any] = {
        "version": VERSION,
        "status": "blocked",
        "max_tokens": max_tokens,
        "estimator": "utf8_bytes_plus_framing.v1",
        "groups": [],
    }
    record: dict[str, Any] = {"manifest": manifest}
    try:
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            raise ValueError("invalid_context_messages")
        if not isinstance(tools, list) or not all(isinstance(t, dict) for t in tools):
            raise ValueError("invalid_context_tools")
        messages = sanitize_context(messages)
        tools = sanitize_context(tools)
        # Every persisted or operator-visible commitment is computed after
        # redaction. A raw SHA-256 of a low-entropy credential would let an
        # observer verify guesses even though the credential text was removed.
        original_messages = messages
        original_hash = digest(messages)
        original_message_hashes = [digest(m) for m in messages]
        raw = canonical(messages)
        original_size = request_size(messages, tools, model)
        manifest.update(
            original_hash=original_hash,
            original_message_hashes=original_message_hashes,
            hash_scope="redacted_pre_compaction.v1",
            excluded_fields=[],
            redaction_policy="context_secrets.v1",
            sanitized_hash=digest(messages),
            tools_hash=digest(tools),
            original_tokens_upper_bound=original_size,
            message_hashes=[digest(message) for message in messages],
        )
        groups = _groups(messages)
        view: list[dict[str, Any]] = json.loads(raw)
        first_user = next((i for i, m in enumerate(messages) if m.get("role") == "user"), -1)
        tool_groups = [group for group in groups if len(group) > 1]
        recent = {i for g in tool_groups[-max(1, keep_recent_groups) :] for i in g}
        # Preserve the latest conversational round, including non-tool corrections.
        last_user = max(
            (i for i, m in enumerate(messages) if m.get("role") == "user"), default=len(messages)
        )
        recent.add(len(messages) - 1)
        if last_user != first_user:
            recent.update(range(last_user, len(messages)))
        count = 0
        for group in groups:
            data = [messages[i] for i in group]
            reason = "within_budget"
            protected = any(
                messages[i].get("role") in {"system", "developer"} or i == first_user or i in recent
                for i in group
            )
            unresolved = any(word in canonical(data).lower() for word in _UNRESOLVED)
            if protected:
                reason = "required_or_recent"
            elif unresolved:
                reason = "unresolved_fact"
            elif request_size(view, tools, model) > max_tokens and len(group) > 1:
                candidate = [dict(view[i]) for i in group]
                try:
                    for entry in candidate[1:]:
                        parsed = json.loads(entry.get("content", ""))
                        entry["content"] = canonical(_bulk_view(parsed))
                except (ValueError, TypeError):
                    reason = "opaque_evidence_retained"
                else:
                    if len(canonical(candidate)) < len(canonical(data)):
                        for i, entry in zip(group, candidate, strict=True):
                            view[i] = entry
                        count += 1
                        reason = "bulk_payload_digest_sources_retained"
                    else:
                        reason = "no_safe_reduction"
            manifest["groups"].append(
                {
                    "indexes": group,
                    "original_hash": digest([original_messages[i] for i in group]),
                    "sanitized_hash": digest(data),
                    "action": "compressed"
                    if reason == "bulk_payload_digest_sources_retained"
                    else "retained",
                    "reason": reason,
                }
            )
        final_size = request_size(view, tools, model)
        manifest.update(
            final_tokens_upper_bound=final_size,
            final_request_bytes=len(
                canonical({"messages": view, "tools": tools, "model": model}).encode()
            ),
            final_hash=digest({"messages": view, "tools": tools, "model": model}),
        )
        if max_tokens <= 0 or final_size > max_tokens:
            raise ValueError("required_context_exceeds_budget")
        manifest["status"] = "ready"
        # Persist only the exact bounded provider view. Full source events stay
        # in their existing journals; duplicating them here would expand secret
        # and retention scope and would make oversized results unrecoverable.
        record.update(
            request_messages=view,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            keep_recent_groups=keep_recent_groups,
        )
        if len(canonical(record).encode()) > 2 * 1024 * 1024:
            raise ValueError("recovery_snapshot_limit")
        # Freeze the request snapshot; subsequent loop mutations cannot rewrite it.
        record = json.loads(canonical(record))
        return RequestCompaction(view, count, manifest, record)
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        reason = (
            str(exc)
            if str(exc).startswith(
                ("tool_protocol", "required_context", "recovery_snapshot", "invalid_role")
            )
            else "invalid_context_content"
        )
        manifest["reason"] = reason
        # Blocked input never becomes a recovery snapshot. The manifest is
        # sufficient to audit the refusal; source journals retain the input.
        record = {"manifest": manifest}
        raise ContextBlocked(reason, record) from exc


def rebuild_request(record: dict[str, Any]) -> RequestCompaction:
    manifest = record.get("manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != VERSION
        or manifest.get("status") != "ready"
    ):
        raise ContextBlocked("compaction_replay_mismatch", record)
    try:
        messages = sanitize_context(record["request_messages"])
        tools = sanitize_context(record["tools"])
        model = str(record["model"])
        _groups(messages)
        final_payload = {"messages": messages, "tools": tools, "model": model}
        valid = (
            digest(final_payload) == manifest["final_hash"]
            and len(canonical(final_payload).encode()) == manifest["final_request_bytes"]
            and request_size(messages, tools, model) == manifest["final_tokens_upper_bound"]
            and manifest["final_tokens_upper_bound"] <= int(record["max_tokens"])
        )
    except (KeyError, TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ContextBlocked("compaction_replay_mismatch", record) from exc
    if not valid:
        raise ContextBlocked("compaction_replay_mismatch", record)
    compacted_groups = sum(
        group.get("action") == "compressed" for group in manifest.get("groups", [])
    )
    return RequestCompaction(messages, compacted_groups, manifest, record)
