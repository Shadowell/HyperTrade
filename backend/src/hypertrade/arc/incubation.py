"""
ARC Paper Incubation Resolver - BitPro strategy create, configure, and start.

A paper instance id is only returned after BitPro has created the strategy and
accepted configure + start. A local uuid is not a running simulation.
"""

import hashlib
import json
from decimal import Decimal
from typing import Any, Protocol

from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    PaperPreauthorizationV1,
)
from hypertrade.bitpro.mcp import BitProToolAdapter


class PaperProvisionClient(Protocol):
    """The BitPro surface this resolver may touch. No live-order methods."""

    def paper_configure_reviewed(self, **parameters: Any) -> dict[str, Any]: ...

    def paper_start_reviewed(self, **parameters: Any) -> dict[str, Any]: ...

    def strategy_get(self, *, strategy_id: int) -> dict[str, Any]: ...

    def strategy_create(
        self,
        *,
        name: str,
        script_content: str,
        description: str | None = None,
        exchange: str = "okx",
        symbols: list[str] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def paper_configure(
        self,
        *,
        strategy_id: int,
        initial_equity: float = 10000.0,
        exchange: str = "okx",
        loop_interval_sec: int = 60,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def paper_start(self, *, strategy_id: int, idempotency_key: str = "") -> dict[str, Any]:
        """Start a paper instance.

        BitProToolAdapter keeps the argument name `strategy_id`, but the
        request body field is `instance_id`, but that legacy field contains the numeric strategy ID.
        The immutable paper_... session ID is used only for evidence reads.
        """
        ...


def format_bitpro_strategy_name(
    symbol: str,
    timeframe: str = "1H",
    strategy_type: str = "CTA",
    logic_summary: str = "unspecified",
    capital_u: int = 100,
) -> str:
    """
    Formats strategy name according to BitPro's official card naming specification:
    Format: [合约][<周期>][<类型>] <标的代码> - <算法逻辑> - <初始资金>U
    Example: [合约][1H][CTA] CL - EMA9/20趋势追踪迹速 - 100U
    """
    clean_symbol = symbol.replace("-SWAP", "").replace("-USDT", "").replace("-", "").upper()
    symbol_code = "CL" if clean_symbol in ["CLUSDT", "OILUSDT", "OIL", "CRCL"] else clean_symbol
    return f"[合约][{timeframe}][{strategy_type}] {symbol_code} - {logic_summary} - {capital_u}U"


def _logic_summary(attempt: ARCCandidateAttemptV1) -> str:
    family = str(attempt.strategy_spec.get("family") or "").strip()
    direction = str(attempt.strategy_spec.get("direction") or "").replace("_", " ").strip()
    parts = [part for part in (family, direction) if part]
    return " ".join(parts)[:48] or "unspecified"


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _strategy_id(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("strategy")
    if isinstance(nested, dict):
        found = _as_int(nested.get("id"))
        if found is not None:
            return found
    return _as_int(payload.get("id") or payload.get("strategy_id"))


def _instance_id(payload: Any) -> str | None:
    """Read a BitPro paper instance id. Never invent one from the strategy id."""
    if not isinstance(payload, dict):
        return None
    paper = payload.get("paper", payload)
    value = paper.get("instance_id") if isinstance(paper, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _ok(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("status") == "ok"


class ARCPaperIncubationResolver:
    """Create the BitPro strategy, then configure and start its paper instance."""

    def __init__(self, client: PaperProvisionClient | None = None) -> None:
        self._client = client

    def resolve_and_provision_paper_trading(
        self,
        attempt: ARCCandidateAttemptV1,
        preauth: PaperPreauthorizationV1,
    ) -> tuple[bool, str | None, str | None, str | None]:
        if attempt.state != "validated":
            return (
                False,
                None,
                None,
                "Candidate must be validated before paper incubation",
            )

        if not preauth or not preauth.allowed_actions:
            return False, None, None, "Invalid or missing paper preauthorization"
        allowed = set(preauth.allowed_actions)
        if not {"configure", "start"}.issubset(allowed):
            return False, None, None, "paper_preauthorization_missing_configure_or_start"

        capital = preauth.max_capital_per_instance
        if not capital.is_finite() or not Decimal("0") < capital <= Decimal("10000"):
            return False, None, None, "paper_capital_outside_supported_range"
        symbol = preauth.symbols[0] if preauth.symbols else "BTC-USDT-SWAP"
        timeframe = str(attempt.strategy_spec.get("timeframe") or "1H")
        bitpro_strategy_name = format_bitpro_strategy_name(
            symbol=symbol,
            timeframe=timeframe,
            strategy_type="CTA",
            logic_summary=_logic_summary(attempt),
            capital_u=int(capital),
        )
        client = self._client or BitProToolAdapter()
        create_key = f"arc-create-{attempt.candidate_id}"
        # New review packages bind the operation to mission, code and capital;
        # equal candidate names in another mission must not reuse this receipt.
        operation_scope = (
            preauth.policy_hash if len(preauth.policy_hash) == 64 else attempt.candidate_id
        )
        reviewed = len(preauth.policy_hash) == 64
        code_sha256 = hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
        configure_key = f"arc-configure-{operation_scope}"
        start_key = f"arc-start-{operation_scope}"

        existing_id = _as_int(attempt.bitpro_strategy_id)
        strategy_id: int
        if existing_id is not None:
            strategy_id = existing_id
        else:
            try:
                created = client.strategy_create(
                    name=bitpro_strategy_name,
                    script_content=attempt.strategy_code,
                    description=(
                        f"ARC Autonomous Research Candidate {attempt.candidate_id} for {symbol}"
                    ),
                    exchange="okx",
                    symbols=[symbol],
                    idempotency_key=create_key,
                )
            except Exception as exc:
                return (
                    False,
                    None,
                    bitpro_strategy_name,
                    f"bitpro_strategy_create_failed:{type(exc).__name__}",
                )

            created_id = _strategy_id(created)
            if not _ok(created) or created_id is None:
                return False, None, bitpro_strategy_name, "bitpro_strategy_create_rejected"
            strategy_id = created_id

        # Existing platform IDs are mutable; approval binds the submitted bytes, not just an ID.
        try:
            remote = client.strategy_get(strategy_id=strategy_id)
        except Exception as exc:
            return (
                False,
                None,
                bitpro_strategy_name,
                f"paper_source_read_failed:{type(exc).__name__}",
            )
        source = remote.get("strategy") if isinstance(remote, dict) else None
        if (
            not _ok(remote)
            or not isinstance(source, dict)
            or _as_int(source.get("id")) != strategy_id
            or source.get("script_content") != attempt.strategy_code
        ):
            return False, None, bitpro_strategy_name, "paper_source_code_or_identity_changed"
        config = source.get("config") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (TypeError, ValueError):
                return False, None, bitpro_strategy_name, "paper_source_config_unreadable"
        if (
            not isinstance(config, dict)
            or config.get("paper_instance_id")
            or source.get("run_started_at")
            or source.get("status") == "running"
        ):
            return False, None, bitpro_strategy_name, "paper_source_already_has_runtime_history"

        try:
            if reviewed:
                configured = client.paper_configure_reviewed(
                    strategy_id=strategy_id,
                    code_sha256=code_sha256,
                    review_hash=preauth.policy_hash,
                    initial_equity=float(capital),
                    exchange="okx",
                    symbols=list(preauth.symbols),
                    timeframe=timeframe,
                    parameters=attempt.strategy_spec.get("tunable_parameters", {}),
                    execution_policy=attempt.strategy_spec.get("execution_policy", {}),
                    idempotency_key=configure_key,
                )
            else:
                configured = client.paper_configure(
                    strategy_id=strategy_id,
                    initial_equity=float(capital),
                    exchange="okx",
                    loop_interval_sec=60,
                    idempotency_key=configure_key,
                )
        except Exception as exc:
            return (
                False,
                None,
                bitpro_strategy_name,
                f"bitpro_paper_configure_failed:{type(exc).__name__}:strategy_id={strategy_id}",
            )
        if not _ok(configured):
            return (
                False,
                None,
                bitpro_strategy_name,
                f"bitpro_paper_configure_rejected:strategy_id={strategy_id}",
            )
        # Configure returns a string session identity. Start still addresses the numeric strategy.
        instance_id = _instance_id(configured)
        receipt = configured.get("paper") or {}
        if not instance_id:
            return (
                False,
                None,
                bitpro_strategy_name,
                f"bitpro_paper_configure_missing_instance:strategy_id={strategy_id}",
            )
        if (
            receipt.get("configured") is not True
            or _as_int(receipt.get("strategy_id")) != strategy_id
        ):
            return False, None, bitpro_strategy_name, "bitpro_paper_configure_identity_mismatch"

        expected_version = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {"script_content": attempt.strategy_code},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        if receipt.get("strategy_version") != expected_version:
            return False, None, bitpro_strategy_name, "bitpro_paper_configured_code_changed"

        try:
            if reviewed:
                started = client.paper_start_reviewed(
                    strategy_id=strategy_id,
                    instance_id=instance_id,
                    code_sha256=code_sha256,
                    review_hash=preauth.policy_hash,
                    config_version=receipt["config_version"],
                    idempotency_key=start_key,
                )
            else:
                started = client.paper_start(strategy_id=strategy_id, idempotency_key=start_key)
        except Exception as exc:
            return (
                False,
                None,
                bitpro_strategy_name,
                f"bitpro_paper_start_failed:{type(exc).__name__}:instance_id={instance_id}",
            )
        if not _ok(started):
            return (
                False,
                None,
                bitpro_strategy_name,
                f"bitpro_paper_start_rejected:instance_id={instance_id}",
            )

        started_receipt = started.get("paper") or {}
        if (
            started_receipt.get("started") is not True
            or _as_int(started_receipt.get("strategy_id")) != strategy_id
            or _instance_id(started) != instance_id
        ):
            return False, None, bitpro_strategy_name, "bitpro_paper_start_identity_unconfirmed"
        if reviewed and any(
            started_receipt.get(key) != receipt.get(key)
            for key in ("guard_version", "review_hash", "code_sha256", "config_version")
        ):
            return False, None, bitpro_strategy_name, "bitpro_started_review_binding_unconfirmed"
        paper_instance_id = instance_id
        msg = (
            f"Started BitPro paper '{bitpro_strategy_name}' "
            f"strategy_id={strategy_id} instance={paper_instance_id} capital={capital}"
        )
        return True, paper_instance_id, bitpro_strategy_name, msg
