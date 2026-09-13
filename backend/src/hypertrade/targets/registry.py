"""Process-wide registry of market targets.

Registration is explicit and idempotent: built-in targets register on first
use, tests may register throwaway targets, and nothing is ever auto-discovered
from the network — a target only becomes reachable after its profile passed
this module. The active target id comes from settings (``MARKET_TARGET``,
default ``bitpro``) so switching platforms is a configuration change, not a
code change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hypertrade.targets.schemas import MarketTargetProfileV1


class MarketTargetUnavailable(RuntimeError):
    """Raised when a target id has no registered profile."""


AdapterFactory = Callable[[], Any]


@dataclass(frozen=True)
class MarketTargetBinding:
    profile: MarketTargetProfileV1
    adapter_factory: AdapterFactory | None = None


_REGISTRY: dict[str, MarketTargetBinding] = {}
_BUILTINS_LOADED = False


def _ensure_builtin_targets() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    from hypertrade.targets.bitpro import register_bitpro_target

    register_bitpro_target()


def register_market_target(
    profile: MarketTargetProfileV1,
    adapter_factory: AdapterFactory | None = None,
    *,
    replace: bool = False,
) -> MarketTargetBinding:
    if profile.target_id in _REGISTRY and not replace:
        raise ValueError(f"market target {profile.target_id!r} is already registered")
    binding = MarketTargetBinding(profile=profile, adapter_factory=adapter_factory)
    _REGISTRY[profile.target_id] = binding
    return binding


def get_market_target(target_id: str) -> MarketTargetBinding:
    _ensure_builtin_targets()
    binding = _REGISTRY.get(str(target_id).strip())
    if binding is None:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise MarketTargetUnavailable(
            f"market target {target_id!r} is not registered; registered: {known}"
        )
    return binding


def adapter_for_target(target_id: str) -> Any:
    """Build the platform adapter for a target via its registered factory."""
    binding = get_market_target(target_id)
    if binding.adapter_factory is None:
        raise MarketTargetUnavailable(
            f"market target {target_id!r} has no adapter factory registered"
        )
    return binding.adapter_factory()


def registered_market_targets() -> list[MarketTargetProfileV1]:
    _ensure_builtin_targets()
    return [binding.profile for binding in _REGISTRY.values()]


def active_market_target_id() -> str:
    from hypertrade.config import get_settings

    configured = str(getattr(get_settings(), "market_target", "") or "").strip()
    return configured or "bitpro"


def get_active_market_target() -> MarketTargetBinding:
    return get_market_target(active_market_target_id())


def reset_market_targets() -> None:
    """Test helper: drop every registration (built-ins reload on next use)."""
    global _BUILTINS_LOADED
    _REGISTRY.clear()
    _BUILTINS_LOADED = False
