"""Autonomous Self-Healing Evolution Engine for Degraded Production Strategies.

When execution strategies trigger circuit breakers or performance degradation,
this engine extracts post-mortem Reflexion failure attributions and negative constraints,
synthesizes mutated parameter spaces, validates robustness, and dynamically registers
healed offspring generations into StrategyRegistry and Feishu notifications.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypertrade.arc.reflexion_alert import ReflexionAlertPayload, dispatch_reflexion_alert
from hypertrade.paper.registry import StrategyRecord, StrategyRegistry, get_strategy_registry
from hypertrade.paper.stage_gate import StrategyStage

logger = logging.getLogger(__name__)


def _paper_snapshot_payload(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    nested = response.get("snapshot")
    return nested if isinstance(nested, dict) else response


def _running_snapshot(
    adapter: Any, *, strategy_id: str | int, instance_id: str | None
) -> str | None:
    if not hasattr(adapter, "paper_snapshot"):
        return None
    try:
        snapshot = _paper_snapshot_payload(
            adapter.paper_snapshot(strategy_id=strategy_id, instance_id=instance_id)
        )
    except Exception:
        return None
    actual_strategy = str(snapshot.get("strategy_id") or "")
    actual_instance = str(snapshot.get("instance_id") or snapshot.get("id") or "")
    if (
        actual_strategy == str(strategy_id)
        and actual_instance
        and (not instance_id or actual_instance == instance_id)
        and str(snapshot.get("status") or "").lower() == "running"
    ):
        return actual_instance
    return None


@dataclass
class HealedOffspring:
    """Audit record of a self-healed strategy generation."""

    parent_strategy_id: str
    offspring_strategy_id: str
    generation: int
    strategy_type: str
    mutated_parameters: dict[str, Any]
    reflexion_constraints: list[str]
    validation_metrics: dict[str, Any]
    registered: bool = True
    feishu_delivered: bool = False
    attribution_report: dict[str, Any] = field(default_factory=dict)
    bitpro_deployed: bool = False
    bitpro_strategy_id: int | None = None
    bitpro_instance_id: str | None = None
    quantlab_deployed: bool = False
    quantlab_strategy_id: str | None = None
    quantlab_instance_id: str | None = None
    target_id: str = "bitpro"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealedOffspring:
        target = str(
            data.get("target_id")
            or ("quantlab" if data.get("quantlab_deployed") else "bitpro")
        )
        return cls(
            parent_strategy_id=data["parent_strategy_id"],
            offspring_strategy_id=data["offspring_strategy_id"],
            generation=int(data["generation"]),
            strategy_type=data["strategy_type"],
            mutated_parameters=data.get("mutated_parameters", {}),
            reflexion_constraints=data.get("reflexion_constraints", []),
            validation_metrics=data.get("validation_metrics", {}),
            registered=bool(data.get("registered", True)),
            feishu_delivered=bool(data.get("feishu_delivered", False)),
            attribution_report=data.get("attribution_report", {}),
            bitpro_deployed=bool(data.get("bitpro_deployed", False)),
            bitpro_strategy_id=data.get("bitpro_strategy_id"),
            bitpro_instance_id=data.get("bitpro_instance_id"),
            quantlab_deployed=bool(data.get("quantlab_deployed", False)),
            quantlab_strategy_id=data.get("quantlab_strategy_id"),
            quantlab_instance_id=data.get("quantlab_instance_id"),
            target_id=target,
            timestamp=data.get("timestamp", ""),
        )


def generate_7d_attribution_report(
    *,
    strategy_name: str,
    strategy_type: str,
    parameters: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    strategy_id: str | int | None = None,
) -> dict[str, Any]:
    """Summary metrics and parameter proposals are not execution evidence."""
    from hypertrade.arc.attribution import attribution_report

    report = attribution_report({"strategy_id": strategy_id}, datetime.now(UTC))
    report["scope"].update(strategy_name=strategy_name, strategy_type=strategy_type)
    return report


def mutate_strategy_parameters(
    strategy_type: str,
    parent_params: dict[str, Any],
    strategy_name: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Mutate parameters to address degradation failure modes across supported families."""
    st = strategy_type.lower()
    name_lower = strategy_name.lower()
    mutated_params: dict[str, Any]
    new_constraints: list[str] = []

    if st == "rsi_reversal" or "rsi" in st:
        orig_os = float(parent_params.get("oversold_threshold", 30.0))
        orig_ob = float(parent_params.get("overbought_threshold", 70.0))
        orig_sl = Decimal(str(parent_params.get("stop_loss_pct", "0.04")))
        orig_tp = Decimal(str(parent_params.get("take_profit_pct", "0.08")))
        orig_period = int(parent_params.get("rsi_period", 14))

        mutated_params = {
            **parent_params,
            "rsi_period": min(24, orig_period + 4),
            "oversold_threshold": max(15.0, round(orig_os - 5.0, 1)),
            "overbought_threshold": min(85.0, round(orig_ob + 5.0, 1)),
            "stop_loss_pct": str(max(Decimal("0.025"), orig_sl * Decimal("0.8"))),
            "take_profit_pct": str(max(Decimal("0.07"), orig_tp * Decimal("1.1"))),
        }
        new_constraints.append("tighten_stop_loss_under_adverse_momentum")
        new_constraints.append("require_deeper_rsi_extremity_boundary")

    elif st == "momentum_breakout" or "breakout" in st:
        orig_thresh = Decimal(str(parent_params.get("breakout_threshold_pct", "2.0")))
        orig_sl = Decimal(str(parent_params.get("stop_loss_pct", "0.03")))
        orig_tp = Decimal(str(parent_params.get("take_profit_pct", "0.06")))

        mutated_params = {
            **parent_params,
            "breakout_threshold_pct": str(orig_thresh + Decimal("0.8")),
            "stop_loss_pct": str(max(Decimal("0.02"), orig_sl * Decimal("0.85"))),
            "take_profit_pct": str(orig_tp * Decimal("1.25")),
        }
        new_constraints.append("expand_breakout_hurdle_to_filter_chop")

    elif st == "macd_trend" or "macd" in st:
        orig_fast = int(parent_params.get("fast_period", 12))
        orig_slow = int(parent_params.get("slow_period", 26))
        orig_sig = int(parent_params.get("signal_period", 9))
        orig_sl = Decimal(str(parent_params.get("stop_loss_pct", "0.035")))
        orig_tp = Decimal(str(parent_params.get("take_profit_pct", "0.075")))

        mutated_params = {
            **parent_params,
            "fast_period": orig_fast + 2,
            "slow_period": orig_slow + 6,
            "signal_period": orig_sig + 3,
            "stop_loss_pct": str(orig_sl * Decimal("0.9")),
            "take_profit_pct": str(orig_tp * Decimal("1.15")),
        }
        new_constraints.append("dampen_macd_signal_line_lag")

    elif (
        "multi_factor" in st
        or "quantlab" in st
        or "a_share" in st
        or "ashare" in st
        or "股票" in strategy_name
        or "a股" in strategy_name.lower()
    ):
        orig_fast = int(parent_params.get("fast_period") or parent_params.get("fast_window") or 10)
        orig_slow = int(parent_params.get("slow_period") or parent_params.get("slow_window") or 30)
        raw_sl = (
            parent_params.get("hard_stop_loss_pct")
            or parent_params.get("stop_loss_pct")
            or "0.06"
        )
        orig_sl = Decimal(str(raw_sl))
        raw_pos = parent_params.get("position_sizing_pct") or 20.0

        mutated_params = {
            **parent_params,
            "fast_period": max(orig_fast + 5, 15),
            "slow_period": max(orig_slow + 10, 40),
            "stop_loss_pct": str(max(Decimal("0.035"), orig_sl * Decimal("0.8"))),
            "position_sizing_pct": min(30.0, float(raw_pos) * 0.8),
            "allow_short": False,  # A股现货禁止裸做空
            "min_holding_days": max(1, int(parent_params.get("min_holding_days", 1))),  # T+1约束
        }
        new_constraints.append("smooth_ashare_trend_filters_and_enforce_t_plus_one")
        new_constraints.append("cap_ashare_cash_exposure_and_forbid_short_selling")

    elif (
        st in (
            "cta_trend_following",
            "ema_trend",
            "ema_trend_following",
            "cta_trend",
            "ema5_20",
        )
        or "ema" in st
        or "cta" in st
        or "fast_window" in parent_params
        or "fast_period" in parent_params
    ):
        orig_fast = int(
            parent_params.get("fast_window") or parent_params.get("fast_period") or 5
        )
        orig_slow = int(
            parent_params.get("slow_window") or parent_params.get("slow_period") or 20
        )
        orig_sl = Decimal(
            str(
                parent_params.get("hard_stop_loss_pct")
                or parent_params.get("stop_loss_pct")
                or "0.04"
            )
        )
        orig_tp = Decimal(str(parent_params.get("profit_peak_pullback_pct") or "0.3"))
        orig_atr = Decimal(str(parent_params.get("atr_stop_mult") or "1.5"))

        mutated_params = {
            **parent_params,
            "fast_window": max(orig_fast + 3, 8),
            "slow_window": max(orig_slow + 5, 25),
            "hard_stop_loss_pct": str(max(Decimal("0.02"), orig_sl * Decimal("0.625"))),
            "profit_peak_pullback_pct": str(max(Decimal("0.18"), orig_tp * Decimal("0.733"))),
            "atr_stop_mult": str(max(Decimal("1.0"), orig_atr * Decimal("0.833"))),
        }
        new_constraints.append("smooth_ema_entry_windows_to_filter_chop")
        new_constraints.append("tighten_hard_stop_loss_to_limit_drawdown")
        new_constraints.append("tighten_trailing_profit_pullback")

    elif "grid" in st or "网格" in strategy_name or "grid" in name_lower:
        raw_spacing = (
            parent_params.get("grid_spacing_pct")
            or parent_params.get("grid_spacing")
            or "0.01"
        )
        orig_spacing = Decimal(str(raw_spacing))
        orig_levels = int(
            parent_params.get("grid_levels") or parent_params.get("levels") or 10
        )
        raw_sl = (
            parent_params.get("stop_loss_pct")
            or parent_params.get("hard_stop_loss_pct")
            or "0.05"
        )
        orig_sl = Decimal(str(raw_sl))
        orig_tp = Decimal(str(parent_params.get("take_profit_pct") or "0.015"))

        mutated_params = {
            **parent_params,
            "grid_spacing_pct": str(min(Decimal("0.05"), orig_spacing * Decimal("1.25"))),
            "grid_levels": max(4, int(orig_levels * 0.8)),
            "stop_loss_pct": str(max(Decimal("0.025"), orig_sl * Decimal("0.8"))),
            "take_profit_pct": str(orig_tp * Decimal("1.15")),
        }
        new_constraints.append("widen_grid_spacing_to_absorb_volatility")
        new_constraints.append("tighten_grid_safety_stop_loss")

    elif "martingale" in st or "马丁" in strategy_name or "martingale" in name_lower:
        raw_mult = (
            parent_params.get("martingale_multiplier")
            or parent_params.get("multiplier")
            or "1.5"
        )
        orig_mult = Decimal(str(raw_mult))
        raw_step = parent_params.get("step_pct") or parent_params.get("step") or "0.015"
        orig_step = Decimal(str(raw_step))
        raw_max = (
            parent_params.get("max_add_counts")
            or parent_params.get("max_layers")
            or 6
        )
        orig_max = int(raw_max)
        raw_sl = (
            parent_params.get("stop_loss_pct")
            or parent_params.get("hard_stop_loss_pct")
            or "0.08"
        )
        orig_sl = Decimal(str(raw_sl))

        mutated_params = {
            **parent_params,
            "martingale_multiplier": str(max(Decimal("1.15"), orig_mult * Decimal("0.85"))),
            "step_pct": str(orig_step * Decimal("1.25")),
            "max_add_counts": max(2, int(orig_max * 0.75)),
            "stop_loss_pct": str(max(Decimal("0.03"), orig_sl * Decimal("0.8"))),
        }
        new_constraints.append("reduce_martingale_multiplier_risk")
        new_constraints.append("cap_max_martingale_layers")

    elif (
        "dynamic_pool" in st
        or "basket" in st
        or "rotation" in st
        or "轮动" in strategy_name
        or "动态标的" in strategy_name
        or "top20" in name_lower
    ):
        raw_w = (
            parent_params.get("momentum_window")
            or parent_params.get("lookback_period")
            or 14
        )
        orig_w = int(raw_w)
        raw_reb = (
            parent_params.get("rebalance_interval_days")
            or parent_params.get("rebalance_days")
            or 7
        )
        orig_reb = int(raw_reb)
        raw_k = parent_params.get("top_k") or parent_params.get("basket_size") or 10
        orig_k = int(raw_k)
        orig_sl = Decimal(str(parent_params.get("stop_loss_pct") or "0.05"))

        mutated_params = {
            **parent_params,
            "momentum_window": orig_w + 4,
            "rebalance_interval_days": min(14, orig_reb + 2),
            "top_k": max(3, int(orig_k * 0.8)),
            "stop_loss_pct": str(max(Decimal("0.025"), orig_sl * Decimal("0.85"))),
        }
        new_constraints.append("tighten_basket_momentum_selection_filter")
        new_constraints.append("dampen_rebalance_churn")

    elif "threshold_pct" in parent_params:
        orig_thresh = Decimal(str(parent_params.get("threshold_pct", "3.0")))
        mutated_params = {
            **parent_params,
            "threshold_pct": str(orig_thresh + Decimal("1.5")),
        }
        new_constraints.append("elevate_utc0_conviction_threshold")

    else:
        mutated = dict(parent_params)
        has_changes = False
        for sl_key in ("stop_loss_pct", "hard_stop_loss_pct", "stop_loss_bps"):
            if sl_key in mutated:
                try:
                    val = Decimal(str(mutated[sl_key]))
                    mutated[sl_key] = str(max(Decimal("0.01"), val * Decimal("0.85")))
                    has_changes = True
                except Exception:
                    pass
        for tp_key in ("take_profit_pct", "profit_peak_pullback_pct", "profit_target_pct"):
            if tp_key in mutated:
                try:
                    val = Decimal(str(mutated[tp_key]))
                    mutated[tp_key] = str(val * Decimal("1.1"))
                    has_changes = True
                except Exception:
                    pass
        if not has_changes:
            mutated["volatility_filter_mult"] = "1.2"
        mutated_params = mutated
        new_constraints.append("tighten_risk_parameters_under_chop")
        new_constraints.append("generic_risk_dampening_mutation")

    return mutated_params, new_constraints


class SelfHealingEvolutionEngine:
    """Executes closed-loop parameter mutation and offspring regeneration."""

    def __init__(
        self,
        registry: StrategyRegistry | None = None,
        history_file: Path | str | None = None,
        bitpro_adapter: Any | None = None,
        quantlab_adapter: Any | None = None,
    ) -> None:
        self._registry = registry or get_strategy_registry()
        self._lock = threading.Lock()
        self._bitpro_adapter = bitpro_adapter
        self._quantlab_adapter = quantlab_adapter
        if history_file is None:
            self._history_file = Path("data/paper_self_healing_history.json")
        else:
            self._history_file = Path(history_file)
        self._history: list[HealedOffspring] = []
        self._load_history()

    def _load_history(self) -> None:
        with self._lock:
            if self._history_file.exists():
                try:
                    raw = json.loads(self._history_file.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        self._history = [HealedOffspring.from_dict(item) for item in raw]
                except Exception:
                    self._history = []

    def _persist_history_unlocked(self) -> None:
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            serialized = [h.to_dict() for h in self._history]
            self._history_file.write_text(
                json.dumps(serialized, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get_history(self) -> list[HealedOffspring]:
        with self._lock:
            return list(self._history)

    def _get_quantlab_adapter(self) -> Any | None:
        if self._quantlab_adapter is not None:
            return self._quantlab_adapter
        try:
            from hypertrade.targets.registry import adapter_for_target

            return adapter_for_target("quantlab")
        except Exception:
            return None

    def _validate_offspring(
        self,
        strategy_id: str | int,
        strategy_type: str,
        mutated_params: dict[str, Any],
        symbols: list[str] | None = None,
        timeframe: str | None = None,
        target_id: str = "bitpro",
    ) -> dict[str, Any]:
        """Validate offspring; QuantLab must produce a real, completed backtest receipt."""
        sid_str = str(strategy_id)
        is_quantlab = target_id == "quantlab"

        if is_quantlab:
            ql_adapter = self._get_quantlab_adapter()
            if ql_adapter is not None:
                try:
                    metrics: dict[str, Any] | None = None
                    job_id = "ql_bt_direct"
                    if hasattr(ql_adapter, "run_backtest"):
                        metrics = ql_adapter.run_backtest(
                            strategy_id=sid_str,
                            parameters=mutated_params,
                            symbols=symbols,
                            timeframe=timeframe or "1D",
                            timeout_seconds=15.0,
                        )
                        job_id = str(metrics.get("job_id") or "ql_bt_direct")
                    elif hasattr(ql_adapter, "backtest_start_job"):
                        start_job = ql_adapter.backtest_start_job(
                            strategy_id=sid_str,
                            parameters=mutated_params,
                            symbols=symbols,
                            timeframe=timeframe,
                        )
                        job_id = start_job.get("job_id") or "ql_bt_job"
                        if job_id and hasattr(ql_adapter, "backtest_get_job"):
                            job_res = ql_adapter.backtest_get_job(job_id)
                            if job_res.get("status") != "completed":
                                raise RuntimeError("quantlab_backtest_not_completed")
                            metrics = job_res.get("metrics")

                    if isinstance(metrics, dict):
                        win_rate = float(metrics["win_rate"])
                        profit_factor = float(metrics["profit_factor"])
                        sharpe_raw = metrics.get("annualized_sharpe")
                        if sharpe_raw is None:
                            sharpe_raw = metrics["sharpe_ratio"]
                        sharpe = float(sharpe_raw)
                        max_dd = float(metrics["max_drawdown_pct"])
                        sim_trades = metrics.get("simulated_trades") or 0
                        raw_trades = metrics.get("total_trades") or sim_trades
                        trades = int(raw_trades)
                        passed = win_rate >= 0.40 and (profit_factor >= 1.0 or sharpe >= 0.5)
                        return {
                            "win_rate": round(win_rate, 4),
                            "profit_factor": round(profit_factor, 2),
                            "sharpe_ratio": round(sharpe, 2),
                            "max_drawdown_pct": round(max_dd, 4),
                            "simulated_trades": trades,
                            "validation_passed": passed,
                            "source": "quantlab_backtest",
                            "backtest_id": job_id,
                        }
                except Exception as exc:
                    logger.info(
                        "QuantLab backtest validation unavailable: %s",
                        exc,
                    )
            return {
                "validation_passed": False,
                "source": "quantlab_backtest_unavailable",
                "reason": "real_quantlab_backtest_receipt_required",
                "simulated_trades": 0,
            }

        # This legacy path knows a parent ID and a parameter proposal, not an
        # immutable candidate receipt. The ARC pipeline owns candidate creation,
        # same-window backtests, review and Paper admission. Never borrow the
        # parent's backtest or promote a heuristic projection as that evidence.
        return {
            "validation_passed": False,
            "source": "bitpro_candidate_backtest_unavailable",
            "reason": "immutable_candidate_backtest_required",
            "simulated_trades": 0,
        }

    def _deploy_offspring_to_bitpro(
        self,
        record: StrategyRecord,
        offspring_id: str,
        next_gen: int,
        mutated_params: dict[str, Any],
    ) -> tuple[bool, int | None, str | None]:
        """Deploy offspring as an active paper twin instance on BitPro via BitProToolAdapter."""
        if self._bitpro_adapter is None:
            return False, None, None

        parent_sid_raw = str(record.strategy_id)
        if not parent_sid_raw.isdigit():
            return False, None, None

        parent_sid = int(parent_sid_raw)
        try:
            parent_info: dict[str, Any] = {}
            if hasattr(self._bitpro_adapter, "strategy_get"):
                try:
                    parent_info = self._bitpro_adapter.strategy_get(strategy_id=parent_sid)
                except Exception as exc:
                    logger.debug("Could not get parent strategy info: %s", exc)

            parent_strategy = (
                parent_info.get("strategy") if isinstance(parent_info, dict) else None
            )
            strat_data: dict[str, Any] = (
                parent_strategy
                if isinstance(parent_strategy, dict)
                else (parent_info if isinstance(parent_info, dict) else {})
            )

            script_content = str(strat_data.get("script_content") or strat_data.get("code") or "")
            if not script_content and hasattr(self._bitpro_adapter, "strategy_research_source"):
                try:
                    src_resp = self._bitpro_adapter.strategy_research_source(
                        strategy_id=parent_sid
                    )
                    if isinstance(src_resp, dict):
                        raw_source = src_resp.get("source")
                        src_dict: dict[str, Any] = (
                            raw_source if isinstance(raw_source, dict) else {}
                        )
                        script_content = str(
                            src_resp.get("script_content")
                            or src_dict.get("script_content")
                            or ""
                        )
                except Exception as exc:
                    logger.debug("Could not fetch research source: %s", exc)

            if not script_content:
                script_content = (
                    f"# Self-healed twin strategy evolved from #{parent_sid} (Gen {next_gen})\n"
                    "from app.services.strategies.base import BaseStrategy\n\n"
                    "class SelfHealedTwinStrategy(BaseStrategy):\n"
                    "    pass\n"
                )

            parent_name = str(strat_data.get("name") or record.name)
            struct_match = re.match(
                r"^\[(?P<asset>[^\[\]]+)\]\[(?P<period>[^\[\]]+)\]\[(?P<type>[^\[\]]+)\] "
                r"(?P<scope>[^·\[\]]+) · (?P<method>[^·\[\]]+) · (?P<capital>[^·\[\]]+)$",
                parent_name,
            )
            if struct_match:
                base_method = re.sub(
                    r"(?:自愈)?(?:（Gen \d+）|\(Gen \d+\)|自愈版)",
                    "",
                    struct_match.group("method"),
                ).strip()
                new_method = f"{base_method}自愈(Gen {next_gen})"
                asset = struct_match.group("asset")
                period = struct_match.group("period")
                st_type = struct_match.group("type")
                scope = struct_match.group("scope").strip()
                capital = struct_match.group("capital").strip()
                offspring_name = (
                    f"[{asset}][{period}][{st_type}] {scope} · {new_method} · {capital}"
                )
            else:
                offspring_name = (
                    f"[合约][1H][CTA] #{parent_sid} · 自愈变体(Gen {next_gen}) · 100U"
                )

            base_config = dict(
                strat_data.get("config") or strat_data.get("parameters") or record.parameters or {}
            )
            merged_config = {
                **base_config,
                **mutated_params,
                "_parent_strategy_id": parent_sid,
                "_evolution_generation": next_gen,
                "_healed_from": offspring_id,
            }
            symbols = strat_data.get("symbols") or (
                [strat_data.get("symbol")] if strat_data.get("symbol") else ["BTC-USDT-SWAP"]
            )
            exchange = strat_data.get("exchange") or "okx"

            if not hasattr(self._bitpro_adapter, "strategy_create"):
                return False, None, None

            create_resp = self._bitpro_adapter.strategy_create(
                name=offspring_name,
                script_content=script_content,
                description=(
                    f"HyperTrade self-healed twin offspring from #{parent_sid} (Gen {next_gen})"
                ),
                config=merged_config,
                exchange=exchange,
                symbols=symbols,
                idempotency_key=f"self_heal_{parent_sid}_gen{next_gen}",
            )
            new_strat = (
                create_resp.get("strategy")
                if isinstance(create_resp.get("strategy"), dict)
                else {}
            )
            new_sid = new_strat.get("id")
            if not new_sid:
                logger.warning(
                    "Failed to obtain new strategy ID from BitPro strategy_create: %s",
                    create_resp,
                )
                return False, None, None

            new_sid_int = int(new_sid)

            if not hasattr(self._bitpro_adapter, "paper_configure") or not hasattr(
                self._bitpro_adapter, "paper_start"
            ):
                return False, new_sid_int, None
            key_base = f"self_heal:bitpro:{parent_sid}:gen{next_gen}"
            try:
                configured = self._bitpro_adapter.paper_configure(
                    strategy_id=new_sid_int,
                    initial_equity=10000.0,
                    exchange=exchange,
                    idempotency_key=f"{key_base}:configure",
                )
            except Exception:
                reconciled = _running_snapshot(
                    self._bitpro_adapter, strategy_id=new_sid_int, instance_id=None
                )
                return (reconciled is not None), new_sid_int, reconciled
            configured_paper = (
                configured.get("paper") if isinstance(configured.get("paper"), dict) else {}
            )
            instance_id = str(
                configured_paper.get("instance_id") or configured_paper.get("id") or ""
            )
            if (
                configured.get("status") != "ok"
                or configured_paper.get("configured") is not True
                or not instance_id
            ):
                return False, new_sid_int, None
            try:
                start_resp = self._bitpro_adapter.paper_start(
                    strategy_id=new_sid_int,
                    idempotency_key=f"{key_base}:start",
                )
            except Exception:
                reconciled = _running_snapshot(
                    self._bitpro_adapter,
                    strategy_id=new_sid_int,
                    instance_id=instance_id,
                )
                return (reconciled is not None), new_sid_int, reconciled
            started_paper = (
                start_resp.get("paper") if isinstance(start_resp.get("paper"), dict) else {}
            )
            started_instance = str(
                started_paper.get("instance_id") or started_paper.get("id") or ""
            )
            if (
                start_resp.get("status") != "ok"
                or started_paper.get("started") is not True
                or started_instance != instance_id
            ):
                return False, new_sid_int, None

            logger.info(
                "Successfully deployed self-healed twin strategy #%s (%s) on BitPro",
                new_sid_int,
                offspring_name,
            )
            return True, new_sid_int, instance_id

        except Exception as exc:
            logger.error("Exception deploying self-healed offspring to BitPro: %s", exc)
            return False, None, None

    def _deploy_offspring_to_quantlab(
        self,
        record: StrategyRecord,
        offspring_id: str,
        next_gen: int,
        mutated_params: dict[str, Any],
    ) -> tuple[bool, str | None, str | None]:
        """Deploy offspring as an active paper twin instance on QuantLab workbench."""
        adapter = self._get_quantlab_adapter()
        if adapter is None:
            return False, None, None

        parent_sid = str(record.strategy_id)
        try:
            parent_name = str(record.name)
            offspring_name = f"{parent_name} 自愈变体(Gen {next_gen})"
            raw_symbols = record.parameters.get("symbols") or (
                [record.parameters.get("symbol")]
                if record.parameters.get("symbol")
                else ["600519.SH"]
            )
            symbols = list(raw_symbols)
            timeframe = str(record.parameters.get("timeframe") or "1H")

            merged_config = {
                **record.parameters,
                **mutated_params,
                "_parent_strategy_id": parent_sid,
                "_evolution_generation": next_gen,
                "_healed_from": offspring_id,
                "market_target": "quantlab",
            }

            strategy_code = str(
                record.parameters.get("strategy_code") or record.parameters.get("code") or ""
            )
            if not strategy_code and hasattr(adapter, "get_strategy_source"):
                try:
                    strategy_code = str(adapter.get_strategy_source(parent_sid).code)
                except Exception:
                    strategy_code = ""
            if not strategy_code.strip():
                from hypertrade.research.quantlab_transpiler import QuantLabStrategyTranspiler

                fast_w = int(
                    merged_config.get("fast_window")
                    or merged_config.get("fast_period")
                    or 5
                )
                slow_w = int(
                    merged_config.get("slow_window")
                    or merged_config.get("slow_period")
                    or 20
                )
                normalized_id = offspring_id.title().replace("-", "_").replace(".", "_")
                clean_cls = re.sub(r"[^a-zA-Z0-9_]", "", normalized_id)
                if not clean_cls or clean_cls[0].isdigit():
                    clean_cls = f"Strategy{clean_cls}"
                strategy_code = QuantLabStrategyTranspiler.generate_default_evolution_code(
                    class_name=clean_cls,
                    fast_window=fast_w,
                    slow_window=slow_w,
                )

            if not hasattr(adapter, "strategy_create"):
                return False, None, None

            create_resp = adapter.strategy_create(
                strategy_id=offspring_id,
                name=offspring_name,
                symbols=symbols,
                timeframe=timeframe,
                code=strategy_code,
                config=merged_config,
                mode="paper",
            )
            created_sid = str(create_resp.get("strategy_id") or "").strip()
            if create_resp.get("status") not in ("created", "deployed") or not created_sid:
                return False, None, None
            if not hasattr(adapter, "paper_configure") or not hasattr(adapter, "paper_start"):
                return False, created_sid, None
            key_base = f"self_heal:quantlab:{parent_sid}:gen{next_gen}"
            try:
                configured = adapter.paper_configure(
                    candidate_key=offspring_id,
                    strategy_id=created_sid,
                    capital=100000.0,
                    symbols=symbols,
                    timeframe=timeframe,
                    idempotency_key=f"{key_base}:configure",
                )
            except Exception:
                reconciled = _running_snapshot(
                    adapter, strategy_id=created_sid, instance_id=None
                )
                return (reconciled is not None), created_sid, reconciled
            instance_id = str(configured.get("instance_id") or "").strip()
            if configured.get("status") not in ("configured", "created", "ready", "stopped"):
                return False, created_sid, None
            if not instance_id or str(configured.get("strategy_id") or "") != created_sid:
                return False, created_sid, None
            try:
                start_resp = adapter.paper_start(
                    candidate_key=offspring_id,
                    strategy_id=created_sid,
                    instance_id=instance_id,
                    idempotency_key=f"{key_base}:start",
                )
            except Exception:
                reconciled = _running_snapshot(
                    adapter, strategy_id=created_sid, instance_id=instance_id
                )
                return (reconciled is not None), created_sid, reconciled
            if (
                start_resp.get("status") != "running"
                or str(start_resp.get("instance_id") or "") != instance_id
                or str(start_resp.get("strategy_id") or "") != created_sid
            ):
                return False, created_sid, None

            logger.info(
                "Successfully deployed self-healed twin strategy %s (%s) on QuantLab",
                created_sid,
                offspring_name,
            )
            return True, created_sid, instance_id
        except Exception as exc:
            logger.error("Exception deploying self-healed offspring to QuantLab: %s", exc)
            return False, None, None

    def heal_strategy(self, strategy_id: str) -> HealedOffspring | None:
        """Evolve a mutated offspring for a degraded strategy."""
        record = self._registry.get(strategy_id)
        if not record:
            logger.warning("Cannot heal non-existent strategy: %s", strategy_id)
            return None

        parent_params = dict(record.parameters)
        next_gen = record.generation + 1
        offspring_id = f"{record.strategy_id}_gen{next_gen}"

        mutated_params, new_constraints = mutate_strategy_parameters(
            record.strategy_type,
            parent_params,
            strategy_name=record.name,
        )
        combined_constraints = list(record.reflexion_constraints) + [
            c for c in new_constraints if c not in record.reflexion_constraints
        ]

        target_id = str(
            record.parameters.get("market_target")
            or record.parameters.get("target_id")
            or "bitpro"
        )

        # Only verified candidate results may authorize execution.
        validation_metrics = self._validate_offspring(
            strategy_id=record.strategy_id,
            strategy_type=record.strategy_type,
            mutated_params=mutated_params,
            symbols=(
                record.parameters.get("symbols")
                or ([record.parameters.get("symbol")] if record.parameters.get("symbol") else None)
            ),
            timeframe=record.parameters.get("timeframe"),
            target_id=target_id,
        )

        # Generate 7-dimension causal attribution report
        attribution = generate_7d_attribution_report(
            strategy_name=record.name,
            strategy_type=record.strategy_type,
            parameters=mutated_params,
            metrics=validation_metrics,
            strategy_id=record.strategy_id,
        )

        bitpro_deployed = False
        bitpro_sid = None
        bitpro_iid = None
        quantlab_deployed = False
        quantlab_sid = None
        quantlab_iid = None

        if validation_metrics.get("validation_passed") is not True:
            logger.warning(
                "Self-healing validation did not pass for %s on %s; deployment blocked",
                record.strategy_id,
                target_id,
            )
        elif target_id == "quantlab":
            quantlab_deployed, quantlab_sid, quantlab_iid = self._deploy_offspring_to_quantlab(
                record=record,
                offspring_id=offspring_id,
                next_gen=next_gen,
                mutated_params=mutated_params,
            )
        elif target_id == "bitpro":
            bitpro_deployed, bitpro_sid, bitpro_iid = self._deploy_offspring_to_bitpro(
                record=record,
                offspring_id=offspring_id,
                next_gen=next_gen,
                mutated_params=mutated_params,
            )

        execution_verified = (
            validation_metrics.get("validation_passed") is True
            and (quantlab_deployed or bitpro_deployed)
        )

        # Create and register offspring
        offspring_record = StrategyRecord(
            strategy_id=offspring_id,
            strategy_type=record.strategy_type,
            name=f"{record.name} (Gen {next_gen})",
            description=(
                f"Self-healed offspring evolved from {record.strategy_id} following circuit breaker"
            ),
            parameters=mutated_params,
            stage=(
                StrategyStage.PAPER_OBSERVING
                if execution_verified
                else StrategyStage.INCUBATING
            ),
            generation=next_gen,
            parent_strategy_id=record.strategy_id,
            reflexion_constraints=combined_constraints,
            performance_metrics=validation_metrics,
            is_active=execution_verified,
        )

        self._registry.register(offspring_record)

        # Dispatch Feishu Reflexion notification
        feishu_ok = False
        if execution_verified:
            try:
                win_pct = f"{validation_metrics['win_rate'] * 100:.1f}%"
                sharpe_val = f"{validation_metrics['sharpe_ratio']:.2f}"
                val_source = validation_metrics.get("source", "unknown")
                source_desc = "回测验证"
                if val_source == "bitpro_backtest":
                    source_desc = "BitPro 真实回测"
                elif val_source == "quantlab_backtest":
                    source_desc = "QuantLab 真实回测"

                if quantlab_deployed and quantlab_sid:
                    deploy_desc = f"已上线 QuantLab 孪生模拟盘 (策略 {quantlab_sid})"
                elif bitpro_deployed and bitpro_sid:
                    deploy_desc = f"已上线 BitPro 孪生模拟盘 (策略 #{bitpro_sid})"
                else:
                    deploy_desc = "尚未取得经验证的模拟盘启动回执，保留在孵化阶段"

                evolution_action = (
                    f"策略自愈进化成功：原策略 [{record.strategy_id}] 触发降级熔断，"
                    f"自愈突变体 [{offspring_id}] (Gen {next_gen}) 已通过{source_desc}"
                    f"（胜率 {win_pct}, 夏普 {sharpe_val}），"
                    f"{deploy_desc}。"
                )

                alert = ReflexionAlertPayload(
                    strategy_id=offspring_id,
                    strategy_name=offspring_record.name,
                    strategy_family=record.strategy_type,
                    failure_class="SELF_HEALING_EVOLUTION_COMPLETED",
                    severity="info",
                    trigger_source="self_healing_evolution",
                    observed_metrics=validation_metrics,
                    regime_attribution=[
                        {
                            "regime": "HIGH_VOLATILITY_CHOP",
                            "weight": 0.85,
                            "causal_factor": (
                                f"Parent {record.strategy_id} degraded; healed in Gen {next_gen}"
                            ),
                        }
                    ],
                    negative_constraints=combined_constraints,
                    evolution_action=evolution_action,
                    candidate_id=offspring_id,
                    next_candidate_id=offspring_id,
                )
                delivered, _ = dispatch_reflexion_alert(alert)
                feishu_ok = delivered
            except Exception as exc:
                logger.error("Failed to dispatch Feishu self-healing card: %s", exc)

        healed = HealedOffspring(
            parent_strategy_id=record.strategy_id,
            offspring_strategy_id=offspring_id,
            generation=next_gen,
            strategy_type=record.strategy_type,
            mutated_parameters=mutated_params,
            reflexion_constraints=combined_constraints,
            validation_metrics=validation_metrics,
            registered=True,
            feishu_delivered=feishu_ok,
            attribution_report=attribution,
            bitpro_deployed=bitpro_deployed,
            bitpro_strategy_id=bitpro_sid,
            bitpro_instance_id=bitpro_iid,
            quantlab_deployed=quantlab_deployed,
            quantlab_strategy_id=quantlab_sid,
            quantlab_instance_id=quantlab_iid,
            target_id=target_id,
        )

        with self._lock:
            self._history.append(healed)
            self._persist_history_unlocked()

        return healed

    def heal_bitpro_strategy(
        self,
        strategy_id: int | str,
        snapshot_or_config: dict[str, Any] | None = None,
    ) -> HealedOffspring:
        """Heal a BitPro strategy directly using paper performance telemetry and parameters."""
        str_id = str(strategy_id)
        record = self._registry.get(str_id)
        cfg = snapshot_or_config or {}

        if not record:
            name = str(cfg.get("name") or cfg.get("strategy_name") or f"BitPro Strategy #{str_id}")
            strategy_type = str(
                cfg.get("strategy_type") or cfg.get("strategyType") or "cta_trend_following"
            )
            params = dict(cfg.get("parameters") or cfg.get("config") or {})
            record = StrategyRecord(
                strategy_id=str_id,
                strategy_type=strategy_type,
                name=name,
                description=f"BitPro imported strategy #{str_id}",
                parameters=params,
                stage=StrategyStage.DEGRADED,
                generation=1,
            )
            self._registry.register(record)
        else:
            if record.stage != StrategyStage.DEGRADED:
                self._registry.update_stage(
                    str_id,
                    StrategyStage.DEGRADED,
                    reason="paper_anomaly_heal_trigger",
                )

        healed = self.heal_strategy(str_id)
        if healed is None:
            raise RuntimeError(f"Failed to heal BitPro strategy: {str_id}")
        return healed

    def heal_quantlab_strategy(
        self,
        strategy_id: int | str,
        snapshot_or_config: dict[str, Any] | None = None,
    ) -> HealedOffspring:
        """Heal a QuantLab strategy directly using paper performance telemetry and parameters."""
        str_id = str(strategy_id)
        record = self._registry.get(str_id)
        cfg = snapshot_or_config or {}

        if not record:
            name = str(cfg.get("name") or cfg.get("strategy_name") or f"QuantLab Strategy {str_id}")
            strategy_type = str(
                cfg.get("strategy_type") or cfg.get("strategyType") or "a_share_alpha_trend"
            )
            params = dict(cfg.get("parameters") or cfg.get("config") or {})
            params.setdefault("market_target", "quantlab")
            record = StrategyRecord(
                strategy_id=str_id,
                strategy_type=strategy_type,
                name=name,
                description=f"QuantLab imported strategy {str_id}",
                parameters=params,
                stage=StrategyStage.DEGRADED,
                generation=1,
            )
            self._registry.register(record)
        else:
            if record.stage != StrategyStage.DEGRADED:
                self._registry.update_stage(
                    str_id,
                    StrategyStage.DEGRADED,
                    reason="paper_anomaly_heal_trigger",
                )

        healed = self.heal_strategy(str_id)
        if healed is None:
            raise RuntimeError(f"Failed to heal QuantLab strategy: {str_id}")
        return healed

    def scan_and_heal_all_degraded(self) -> list[HealedOffspring]:
        """Scan registry for DEGRADED strategies without active offspring and trigger healing."""
        all_records = self._registry.list_all()
        degraded = [r for r in all_records if r.stage == StrategyStage.DEGRADED]

        healed_list: list[HealedOffspring] = []
        for rec in degraded:
            # Check if this strategy already has an offspring
            has_child = any(r.parent_strategy_id == rec.strategy_id for r in all_records)
            if has_child:
                continue

            healed = self.heal_strategy(rec.strategy_id)
            if healed:
                healed_list.append(healed)

        return healed_list


def heal_quantlab_strategy(
    strategy_id: int | str,
    snapshot_or_config: dict[str, Any] | None = None,
    engine: SelfHealingEvolutionEngine | None = None,
) -> HealedOffspring:
    """Heal a QuantLab strategy directly using paper telemetry or configuration."""
    eng = engine or SelfHealingEvolutionEngine()
    return eng.heal_quantlab_strategy(strategy_id, snapshot_or_config)
