"""Small, auditable context resolver for operator follow-up questions.

The resolver consumes only prior *user* turns supplied by the trusted client
surface. It does not treat prior assistant prose as evidence and it never
silently resolves an explicitly ambiguous reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class ResolvedConversation:
    objective: str
    context_ref: str = ""
    clarification_options: tuple[str, ...] = ()


def resolve_operator_turn(*, prompt: str, prior_turns: tuple[str, ...]) -> ResolvedConversation:
    """Resolve a bounded follow-up against the immediately preceding user turn."""

    normalized = prompt.strip()
    prior = tuple(turn.strip() for turn in prior_turns[-8:] if turn.strip())
    if not prior or not _uses_reference(normalized):
        return ResolvedConversation(objective=normalized)
    previous = prior[-1]
    if _ambiguous_strategy_pair(previous, normalized):
        return ResolvedConversation(
            objective=normalized,
            clarification_options=("策略 A", "策略 B"),
        )
    if "后者" in normalized:
        instruments = _market_instruments(previous)
        if len(instruments) >= 2:
            return _resolved(normalized, f"上文后者为 {instruments[-1]}。")
    return _resolved(normalized, f"上文用户问题：{previous}")


def _resolved(prompt: str, context: str) -> ResolvedConversation:
    digest = sha256(context.encode()).hexdigest()[:20]
    return ResolvedConversation(
        objective=f"{context}\n当前问题：{prompt}",
        context_ref=f"conversation:{digest}",
    )


def _uses_reference(value: str) -> bool:
    return any(
        token in value for token in ("它", "这个", "其中", "后者", "哪个", "哪一个", "他的", "她的")
    )


def _ambiguous_strategy_pair(previous: str, current: str) -> bool:
    return (
        "策略 A" in previous
        and "策略 B" in previous
        and any(token in current for token in ("他", "她", "它", "交易数据"))
    )


def _market_instruments(value: str) -> tuple[str, ...]:
    # Chinese text has no ASCII word boundary around tickers, so ``\b`` would
    # miss “比较 BTC 和 ETH”. Tickers are a fixed bounded set here.
    found = re.findall(r"(BTC|ETH|SOL)", value.upper())
    return tuple(dict.fromkeys(found))
