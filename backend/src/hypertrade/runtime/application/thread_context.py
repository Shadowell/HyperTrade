"""Compile bounded canonical context from server-persisted Thread Items."""

from __future__ import annotations

import re

from hypertrade.runtime.domain.models import StrictModel
from hypertrade.runtime.domain.thread_turn import ThreadSnapshotV1, TurnProjectionV1

_STRATEGY_REF = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)")
_INSTRUMENT_REF = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{2,20}(?:-USDT(?:-SWAP)?)?)(?![A-Z0-9])")
_REFERENCE_WORDS = ("后者", "前者", "它", "这个", "其中", "该策略", "该标的")
_NON_INSTRUMENT_WORDS = {"USDT", "SWAP", "API", "CLI", "MCP", "LAB"}


class CanonicalResolvedContextV1(StrictModel):
    schema_version: str = "thread_context.v1"
    normalized_objective: str
    subject_kind: str = ""
    subject_refs: tuple[str, ...] = ()
    resolved_subject: str = ""
    source_item_ids: tuple[str, ...] = ()
    input_gap: str = ""


def compile_thread_context(
    snapshot: ThreadSnapshotV1,
    turn_id: str,
) -> CanonicalResolvedContextV1:
    """Resolve a follow-up only from committed Items in the same Thread."""

    turn = snapshot.turn(turn_id)
    current_item = snapshot.item(turn.input_item_id)
    prompt = str(current_item.content.get("text") or "").strip()
    previous_turns = [row for row in snapshot.turns if row.created_at < turn.created_at]
    previous_turns.sort(key=lambda row: (row.created_at, row.turn_id))

    current_strategies = _strategy_refs(prompt)
    current_instruments = _instrument_refs(prompt)
    if current_strategies:
        return CanonicalResolvedContextV1(
            normalized_objective=prompt,
            subject_kind="strategy",
            subject_refs=current_strategies,
            resolved_subject=current_strategies[-1] if len(current_strategies) == 1 else "",
            source_item_ids=(current_item.item_id,),
        )
    if current_instruments:
        return CanonicalResolvedContextV1(
            normalized_objective=prompt,
            subject_kind="instrument",
            subject_refs=current_instruments,
            resolved_subject=current_instruments[-1] if len(current_instruments) == 1 else "",
            source_item_ids=(current_item.item_id,),
        )
    if not any(word in prompt for word in _REFERENCE_WORDS):
        return CanonicalResolvedContextV1(
            normalized_objective=prompt,
            source_item_ids=(current_item.item_id,),
        )

    prior_refs, prior_kind, source_ids = _latest_subject_refs(snapshot, previous_turns)
    if not prior_refs:
        return CanonicalResolvedContextV1(
            normalized_objective=prompt,
            source_item_ids=(current_item.item_id,),
            input_gap="无法从当前 Thread 的已提交 Items 安全解析指代对象。",
        )
    if "后者" in prompt:
        resolved = prior_refs[-1]
    elif "前者" in prompt or len(prior_refs) == 1:
        resolved = prior_refs[0]
    else:
        return CanonicalResolvedContextV1(
            normalized_objective=prompt,
            subject_kind=prior_kind,
            subject_refs=prior_refs,
            source_item_ids=(*source_ids, current_item.item_id),
            input_gap="当前指代可能对应多个对象，请明确策略或标的。",
        )
    return CanonicalResolvedContextV1(
        normalized_objective=f"上文指代对象为 {resolved}。\n当前问题：{prompt}",
        subject_kind=prior_kind,
        subject_refs=prior_refs,
        resolved_subject=resolved,
        source_item_ids=(*source_ids, current_item.item_id),
    )


def _latest_subject_refs(
    snapshot: ThreadSnapshotV1,
    previous_turns: list[TurnProjectionV1],
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    for raw_turn in reversed(previous_turns):
        turn_id = raw_turn.turn_id
        turn = snapshot.turn(turn_id)
        context = turn.resolved_context
        refs = tuple(str(value) for value in context.get("subject_refs", []) if str(value))
        kind = str(context.get("subject_kind") or "")
        if refs:
            return refs, kind, tuple(str(value) for value in context.get("source_item_ids", []))
        user_item = snapshot.item(turn.input_item_id)
        text = str(user_item.content.get("text") or "")
        strategies = _strategy_refs(text)
        if strategies:
            return strategies, "strategy", (user_item.item_id,)
        instruments = _instrument_refs(text)
        if instruments:
            return instruments, "instrument", (user_item.item_id,)
    return (), "", ()


def _strategy_refs(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.casefold() for match in _STRATEGY_REF.findall(value)))


def _instrument_refs(value: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in _INSTRUMENT_REF.findall(value):
        candidate = match.upper()
        if "-" not in candidate and candidate in _NON_INSTRUMENT_WORDS and candidate != "LAB":
            continue
        if "_" in candidate:
            continue
        values.append(candidate if "-" in candidate else f"{candidate}-USDT-SWAP")
    return tuple(dict.fromkeys(values))
