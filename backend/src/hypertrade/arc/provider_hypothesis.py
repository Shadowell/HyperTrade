"""Provider hypothesis channel: the model proposes, deterministic systems dispose.

M0 required a real provider inside the research loop, which a fixed six-family
catalogue cannot satisfy on its own. This channel is bounded by construction:

- The provider may only shape a ``research_strategy_spec.v1`` mapping that the
  deterministic codegen compiles; its text never becomes strategy code directly.
- Every compiled candidate passes the same static gate as family candidates, at
  compile time and again at load time in the replay simulator.
- Budgets, success criteria, authorizations and state transitions are not part of
  the prompt contract, so the model structurally cannot grant or widen them.
- A proposal that fails JSON/schema/compile validation is discarded with an explicit
  reason code; the deterministic path continues untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from hypertrade.providers.chat import ChatProvider
from hypertrade.research.codegen import FAMILIES, StrategyCodegenError, generate_strategy

PROVIDER_OK = "ok"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_SPEC_INVALID = "provider_spec_invalid"

_FAMILY_KEYS = tuple(family.key for family in FAMILIES)
_DIRECTIONS = ("long_only", "short_only", "long_short")

_SYSTEM_PROMPT_TEMPLATE = """You are the blue-team quant on an autonomous strategy research loop.
Propose ONE falsifiable trading-strategy hypothesis for the given market.

Reply with STRICT JSON only (no prose, no markdown fences) using exactly this shape:
{
  "hypothesis": "one falsifiable sentence: what edge, in which regime, why it exists",
  "family_key": "one of: @FAMILIES",
  "direction": "one of: @DIRECTIONS",
  "entry_logic": "concise entry rule the family can express",
  "exit_logic": "concise exit rule; must include a stop-loss side",
  "risk_conditions": ["stop loss", "take profit"],
  "parameter_bounds": {"<param_name>": {"min": number, "max": number}}
}

Rules:
- family_key MUST come from the list. Direction must be expressible for that family.
- Do NOT invent budgets, approval rules, or risk limits; you have no authority there.
- If prior failure reasons are given, propose a hypothesis that addresses them rather
  than repeating the rejected idea.
"""

_SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.replace(
    "@FAMILIES", ", ".join(_FAMILY_KEYS)
).replace("@DIRECTIONS", ", ".join(_DIRECTIONS))


@dataclass(frozen=True)
class ProviderProposal:
    """A validated provider-shaped spec plus the provenance needed to audit it."""

    spec: dict[str, Any]
    hypothesis: str
    provider: str
    model: str
    request_hash: str


def build_provider_hypothesist() -> ProviderHypothesist | None:
    """Wire the configured chat provider behind the opt-in flag, else None."""
    from hypertrade.config import get_settings
    from hypertrade.providers.runtime import ProviderRuntime

    settings = get_settings()
    if not bool(getattr(settings, "arc_provider_hypotheses_enabled", False)):
        return None
    try:
        provider = ProviderRuntime(settings).get_chat_provider()
    except Exception:
        return None
    if provider is None:
        return None
    return ProviderHypothesist(provider)


class ProviderHypothesist:
    """One structured call per proposal; no tools, no state transitions."""

    def __init__(self, provider: ChatProvider) -> None:
        self._provider = provider

    @property
    def label(self) -> str:
        name = getattr(self._provider, "name", "provider")
        model = getattr(self._provider, "model", "unknown")
        return f"{name}:{model}"

    def propose(
        self,
        *,
        objective: str,
        symbol: str,
        timeframe: str,
        failure_reasons: tuple[str, ...] = (),
        skills_context: str = "",
    ) -> tuple[ProviderProposal | None, str]:
        user_payload: dict[str, Any] = {
            "objective": objective,
            "symbol": symbol,
            "timeframe": timeframe,
            "prior_failure_reasons": list(failure_reasons)[-12:],
        }
        if skills_context:
            # Distilled skills from previously validated candidates: reusable
            # building blocks the hypothesis may compose from, never new scopes.
            user_payload["validated_skill_library"] = skills_context
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        request_hash = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        try:
            response = self._provider.chat(messages)
            content = response.content or ""
        except Exception:
            # Network/model outages must never break the deterministic search.
            return None, PROVIDER_UNAVAILABLE

        parsed = _parse_json_object(content)
        if parsed is None:
            return None, PROVIDER_SPEC_INVALID
        spec = _bounded_spec(parsed, objective=objective, symbol=symbol, timeframe=timeframe)
        if spec is None:
            return None, PROVIDER_SPEC_INVALID
        try:
            generate_strategy(spec)
        except StrategyCodegenError:
            return None, PROVIDER_SPEC_INVALID
        except Exception:
            return None, PROVIDER_SPEC_INVALID

        return (
            ProviderProposal(
                spec=spec,
                hypothesis=str(parsed.get("hypothesis") or spec["entry_logic"])[:300],
                provider=str(getattr(self._provider, "name", "provider")),
                model=str(getattr(self._provider, "model", "unknown")),
                request_hash=request_hash,
            ),
            PROVIDER_OK,
        )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Read one JSON object out of a model reply, tolerating fenced output."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _bounded_spec(
    parsed: dict[str, Any],
    *,
    objective: str,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Project a provider reply onto the spec shape the codegen consumes.

    Only whitelisted keys survive. Family and direction must be values the catalogue
    actually knows; anything else fails closed here instead of surprising the
    compiler or, worse, widening what a candidate is allowed to be.
    """
    family_key = parsed.get("family_key")
    direction = parsed.get("direction")
    if family_key not in _FAMILY_KEYS:
        return None
    if direction not in _DIRECTIONS:
        return None
    bounds = parsed.get("parameter_bounds")
    cleaned_bounds: dict[str, dict[str, float]] = {}
    if isinstance(bounds, dict):
        for name, pair in bounds.items():
            if not isinstance(name, str) or not isinstance(pair, dict):
                continue
            low, high = pair.get("min"), pair.get("max")
            if not isinstance(low, int | float) or not isinstance(high, int | float):
                continue
            if high < low:
                continue
            cleaned_bounds[name] = {"min": float(low), "max": float(high)}

    entry_logic = str(parsed.get("entry_logic") or objective)[:400]
    exit_logic = str(parsed.get("exit_logic") or "stop loss and take profit exit")[:400]
    return {
        "schema_version": "research_strategy_spec.v1",
        "strategy_key": f"prov_{symbol.replace('-', '_').casefold()}",
        "title": f"Provider hypothesis for {symbol}",
        "hypothesis": str(parsed.get("hypothesis") or objective)[:400],
        # The family/direction wording doubles as selection input, but both explicit
        # keys short-circuit inference, so the provider's choice is authoritative.
        "entry_logic": f"{entry_logic} ({family_key})",
        "exit_logic": exit_logic,
        "symbols": [symbol],
        "timeframes": [timeframe],
        "strategy_category": "ARC",
        "family_key": family_key,
        "direction": direction,
        # BitPro refuses candidates without a profit exit; same requirement as the
        # family path, so provider candidates cannot skip it either.
        "risk_conditions": ["bounded notional", "stop loss", "take profit"],
        "data_requirements": ["ohlcv"],
        "invalidation_conditions": ["insufficient data"],
        "parameter_bounds": cleaned_bounds,
    }
