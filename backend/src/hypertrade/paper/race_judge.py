"""Automated Race Judge Daemon and Relay Scheduler for BitPro paper twin strategies.

Monitors running twin strategy pairs (parent vs. healed offspring/challenger),
evaluates forward evidence gates (14-day hourly equity, drawdown, and paired sign test),
and triggers automated handover/adoption and operator notifications.

A BitPro parent can race several challengers at once (one per variant slot), each in its
own lane. The judge tracks every (parent, challenger) pair on its own, tells who ended a
cancelled lane (operator, the system for being far behind / failing the final exam /
running out of time, or a sibling lane taking over) and polls observing lanes slowly:
BitPro owns the state machine, so the judge only needs to notice changes, not re-read
fourteen days of evidence for every lane every minute.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from hypertrade.bitpro.mcp import BitProToolAdapter
from hypertrade.config import Settings, get_settings
from hypertrade.db import Database
from hypertrade.paper.relay_netting import PositionNettingRelayService

logger = logging.getLogger("hypertrade.paper.race_judge")

# Relay plan states that still describe a live race on the target.
_LIVE_PLAN_STATES = ("observing", "draining", "transferred")
# Judge-side states that need no more polling ("ended": the target no longer keeps the lane).
_TERMINAL_STATES = ("completed", "rejected", "cancelled", "ended")

# `cancellation.kind` values BitPro reports, and the milestone each one earns. A lane that
# lost its seat only because a sibling was adopted needs no card of its own: the winner's
# ADOPTED / COMPLETED cards already say so, so it is recorded without a message.
_SYSTEM_CANCEL_MILESTONES = {"futility": "FUTILITY", "exam": "EXAM_FAILED", "timeout": "TIMED_OUT"}
_QUIET_CANCEL_KINDS = {"superseded": "SUPERSEDED"}
_KNOWN_CANCEL_KINDS = {"operator", "system", *_SYSTEM_CANCEL_MILESTONES, *_QUIET_CANCEL_KINDS}
# Any of these markers means a cancel-type card was already handled for the pair ("REJECTED"
# is what the first release recorded for an operator cancel).
_CANCEL_MARKERS = frozenset(
    {"CANCELLED", "REJECTED", *_SYSTEM_CANCEL_MILESTONES.values(), *_QUIET_CANCEL_KINDS.values()}
)


def _opt_float(value: Any) -> float | None:
    """Unknown evidence stays None; it is never rendered as a 0% result."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slot_no(value: Any) -> int | None:
    number = _opt_int(value)
    return number if number is not None and number > 0 else None


def _opt_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:400] or None


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "未知"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _count(value: int | None) -> str:
    return "未知" if value is None else str(value)


def _pp(value: float | None) -> str:
    return "未知" if value is None else f"{value:+.2f} 个百分点"


def _required_wins(non_tie_days: int, alpha: float) -> int | None:
    """Fewest winning days whose one-sided sign-test p-value is within alpha.

    Same rule as BitPro's forward gate, so a card can say where the pass line was.
    None below the gate's ten non-tie days.
    """
    if non_tie_days < 10:
        return None
    for wins in range(non_tie_days + 1):
        tail = sum(math.comb(non_tie_days, k) for k in range(wins, non_tie_days + 1))
        if tail / 2**non_tie_days <= alpha + 1e-12:
            return wins
    return None


def _cancellation_kind(raw: Any) -> str | None:
    """Who ended a cancelled lane; a missing, malformed or newer-than-known kind is unknown."""
    kind = raw.get("kind") if isinstance(raw, dict) else raw
    return kind if isinstance(kind, str) and kind in _KNOWN_CANCEL_KINDS else None


def _cancellation_metrics(raw: Any) -> dict[str, Any] | None:
    """Futility evidence BitPro attaches to a cancellation; only well-formed numbers survive."""
    detail = raw.get("detail") if isinstance(raw, dict) else None
    metrics = detail.get("metrics") if isinstance(detail, dict) else None
    if not isinstance(metrics, dict):
        return None

    def pair(value: Any, cast: Any) -> list[Any] | None:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [cast(value[0]), cast(value[1])]
        return None

    result = {
        "common_hours": _opt_int(metrics.get("common_hours")),
        "closed_fills": pair(metrics.get("closed_fills"), _opt_int),
        "return_pct": pair(metrics.get("return_pct"), _opt_float),
        "excess_pp": _opt_float(metrics.get("excess_pp")),
        "drawdown_pct": pair(metrics.get("drawdown_pct"), _opt_float),
    }
    return result if any(value is not None for value in result.values()) else None


def _cancellation_cooldown_hours(raw: Any) -> float | None:
    detail = raw.get("detail") if isinstance(raw, dict) else None
    thresholds = detail.get("thresholds") if isinstance(detail, dict) else None
    if not isinstance(thresholds, dict):
        return None
    hours = _opt_float(thresholds.get("reenroll_cooldown_hours"))
    return hours if hours is not None and hours >= 0 else None


@dataclass
class RacePairRecord:
    """Audit and state record for a monitored twin race pair."""

    parent_strategy_id: str | int
    challenger_strategy_id: str | int
    target_id: str = "bitpro"
    generation: int = 1
    parent_name: str = ""
    challenger_name: str = ""
    # observing | draining | transferred | completed | cancelled | rejected | ended
    state: str = "observing"
    eligible: bool = False
    reason: str = ""
    proof_sha256: str | None = None
    observed_hours: int | None = None
    target_hours: int = 337
    parent_trades: int | None = None
    challenger_trades: int | None = None
    parent_net_return_pct: float | None = None
    challenger_net_return_pct: float | None = None
    excess_return_pct: float | None = None
    parent_max_drawdown_pct: float | None = None
    challenger_max_drawdown_pct: float | None = None
    sign_test_p: float | None = None
    positive_days: int = 0
    paired_non_tie_days: int = 0
    # Variant-slot lane of the parent this challenger holds; None on targets without slots.
    slot_no: int | None = None
    # Sign-test level the lane is judged at (0.05 divided by the parent's slot count).
    gate_alpha: float | None = None
    # True once the target listed this pair as a plan; if it later disappears the lane "ended".
    plan_seen: bool = False
    # Who ended a cancelled lane and what BitPro attached; all None while racing or unknown.
    cancellation_kind: str | None = None
    cancellation_actor: str | None = None
    cancellation_reason: str | None = None
    cancellation_cooldown_hours: float | None = None
    cancellation_metrics: dict[str, Any] | None = None
    # Epoch seconds before which a sweep leaves the pair alone (quiet lanes are polled slowly).
    next_poll_at: float = 0.0
    # Retained for persisted-state compatibility; the judge never adopts (BitPro owns relays).
    auto_adopt_enabled: bool = False
    action_taken: str | None = None
    feishu_notified_states: list[str] = field(default_factory=list)
    requires_admin_authorization: bool = False
    handover_plan_id: str | None = None
    handover_plan_sha256: str | None = None
    turnover_reduction_ratio: float = 0.0
    friction_saved_cny: float = 0.0
    handover_slices_completed: int = 0
    handover_slices_total: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RacePairRecord:
        pid_raw = data["parent_strategy_id"]
        cid_raw = data["challenger_strategy_id"]

        def _parse_id(val: Any) -> str | int:
            if isinstance(val, int):
                return val
            return str(val).strip()

        pid = _parse_id(pid_raw)
        cid = _parse_id(cid_raw)
        target = str(data.get("target_id") or "bitpro")

        return cls(
            parent_strategy_id=pid,
            challenger_strategy_id=cid,
            target_id=target,
            generation=int(data.get("generation", 1)),
            parent_name=data.get("parent_name", ""),
            challenger_name=data.get("challenger_name", ""),
            state=data.get("state", "observing"),
            eligible=bool(data.get("eligible", False)),
            reason=data.get("reason", ""),
            proof_sha256=data.get("proof_sha256"),
            observed_hours=_opt_int(data.get("observed_hours")),
            target_hours=int(data.get("target_hours", 337)),
            parent_trades=_opt_int(data.get("parent_trades")),
            challenger_trades=_opt_int(data.get("challenger_trades")),
            parent_net_return_pct=_opt_float(data.get("parent_net_return_pct")),
            challenger_net_return_pct=_opt_float(data.get("challenger_net_return_pct")),
            excess_return_pct=_opt_float(data.get("excess_return_pct")),
            parent_max_drawdown_pct=_opt_float(data.get("parent_max_drawdown_pct")),
            challenger_max_drawdown_pct=_opt_float(data.get("challenger_max_drawdown_pct")),
            sign_test_p=float(data["sign_test_p"]) if data.get("sign_test_p") is not None else None,
            positive_days=int(data.get("positive_days", 0)),
            paired_non_tie_days=int(data.get("paired_non_tie_days", 0)),
            # Records saved before variant slots existed lack every field below.
            slot_no=_slot_no(data.get("slot_no")),
            gate_alpha=_opt_float(data.get("gate_alpha")),
            plan_seen=bool(data.get("plan_seen", False)),
            cancellation_kind=_cancellation_kind(data.get("cancellation_kind")),
            cancellation_actor=_opt_text(data.get("cancellation_actor")),
            cancellation_reason=_opt_text(data.get("cancellation_reason")),
            cancellation_cooldown_hours=_opt_float(data.get("cancellation_cooldown_hours")),
            cancellation_metrics=(
                data["cancellation_metrics"]
                if isinstance(data.get("cancellation_metrics"), dict)
                else None
            ),
            next_poll_at=_opt_float(data.get("next_poll_at")) or 0.0,
            auto_adopt_enabled=False,
            action_taken=data.get("action_taken"),
            feishu_notified_states=list(data.get("feishu_notified_states") or []),
            requires_admin_authorization=bool(data.get("requires_admin_authorization", False)),
            handover_plan_id=data.get("handover_plan_id"),
            handover_plan_sha256=data.get("handover_plan_sha256"),
            turnover_reduction_ratio=float(data.get("turnover_reduction_ratio", 0.0)),
            friction_saved_cny=float(data.get("friction_saved_cny", 0.0)),
            handover_slices_completed=int(data.get("handover_slices_completed", 0)),
            handover_slices_total=int(data.get("handover_slices_total", 0)),
            updated_at=data.get("updated_at", ""),
        )


def _system_elimination_lines(record: RacePairRecord, milestone: str) -> list[str]:
    """Card lines for a lane BitPro's own state machine ended (not an operator cancel)."""
    lines: list[str] = []
    if record.cancellation_reason:
        lines.append(f"**淘汰原因**: {record.cancellation_reason}")
    metrics = record.cancellation_metrics or {}
    if metrics:
        returns = metrics.get("return_pct") or [None, None]
        drawdowns = metrics.get("drawdown_pct") or [None, None]
        fills = metrics.get("closed_fills") or [None, None]
        lines.append(
            f"**同窗证据**: 共同运行 {_count(metrics.get('common_hours'))} 小时 | "
            f"同窗超额 {_pp(metrics.get('excess_pp'))} | "
            f"收益: 挑战者 {_pct(returns[1])} vs 母体 {_pct(returns[0])} | "
            f"回撤: 挑战者 {_pct(drawdowns[1], False)} vs 母体 {_pct(drawdowns[0], False)} | "
            f"平仓: 挑战者 {_count(fills[1])} 笔 / 母体 {_count(fills[0])} 笔"
        )
    slot = f"（位{record.slot_no}）" if record.slot_no is not None else ""
    lines.append(
        "🛑 **系统处理**: 系统已自动淘汰该挑战者（不是操作者取消），"
        "停止其 Paper（历史、成交与曲线保留），"
        f"释放它占的变体位{slot}；母体和它的其他变体照常比赛。"
    )
    if milestone == "FUTILITY":
        cooldown = record.cancellation_cooldown_hours
        refill = (
            f"该位约 {cooldown:g} 小时冷却后自动补入下一个已审核候选"
            if cooldown is not None
            else "该位冷却后自动补入下一个已审核候选"
        )
    else:
        refill = "该位可立即补入下一个已审核候选"
    lines.append(
        f"{refill}，被淘汰的候选不会被自动放行；"
        "如需继续观察，由操作者在 BitPro 手动『启动实测』。"
    )
    return lines


def build_race_feishu_card(
    record: RacePairRecord,
    milestone: str,
    *,
    console_url: str = "",
) -> dict[str, Any]:
    """Build an interactive Feishu card for race judge lifecycle milestones."""
    base_url = (console_url or "https://bitpro.notenap.com").rstrip("/")
    monitor_url = (
        f"{base_url}/live?mode=paper&strategyId={record.parent_strategy_id}"
        f"&challengerId={record.challenger_strategy_id}&tab=evolution"
    )

    color_map = {
        "ELIGIBLE": "blue",
        "ADOPTED": "carmine",
        "COMPLETED": "green",
        "REQUIRES_ADMIN": "orange",
        "REJECTED": "grey",
        "CANCELLED": "grey",
        "FUTILITY": "orange",
        "EXAM_FAILED": "orange",
        "TIMED_OUT": "orange",
    }
    title_map = {
        "ELIGIBLE": "🏁 【BitPro 策略接力已达标】前向门禁全量通过",
        "ADOPTED": "🚀 【BitPro 策略接力已触发】配额交接，母体转入 Draining",
        "COMPLETED": "🏆 【BitPro 策略接力圆满完成】Gen N 晋升 Primary 主力",
        "REQUIRES_ADMIN": "⚠️ 【BitPro 策略接力待授权】前向门禁已达标需管理员采纳",
        "REJECTED": "❌ 【BitPro 策略接力未通过】挑战者被淘汰",
        # 取消不是门禁判负，不能写成“挑战者被淘汰”；只有确认是操作者取消才写“操作者”。
        "CANCELLED": (
            "⏹ 【BitPro 策略接力已取消】操作者终止赛马，母体继续担任主力"
            if record.cancellation_kind == "operator"
            else "⏹ 【BitPro 策略接力已取消】该场接力已被取消，母体继续担任主力"
        ),
        # 系统淘汰：由 BitPro 状态机按证据结束，不是操作者取消。
        "FUTILITY": "📉 【BitPro 赛马淘汰】挑战者明显落后，已被系统淘汰",
        "EXAM_FAILED": "📝 【BitPro 赛马淘汰】14天终考未过关，挑战者已被系统淘汰",
        "TIMED_OUT": "⏱ 【BitPro 赛马淘汰】超时仍未考完，挑战者已被系统淘汰",
    }

    card_color = color_map.get(milestone, "blue")
    card_title = title_map.get(milestone, f"🏁 【BitPro 策略赛马更新】{milestone}")

    # The pass line depends on how many variant slots the parent has; older targets say 0.05.
    alpha = 0.05
    if record.gate_alpha is not None and 0 < record.gate_alpha <= 0.05:
        alpha = record.gate_alpha
    alpha_text = "0.05" if abs(alpha - 0.05) < 1e-9 else f"{alpha:.4f}"
    p_val_str = (
        f"{record.sign_test_p:.4f} (<= {alpha_text} 显著)"
        if record.sign_test_p is not None
        else "计算中"
    )
    needed = (
        _required_wins(record.paired_non_tie_days, alpha) if record.gate_alpha is not None else None
    )
    if needed is not None:
        p_val_str += f" | 及格线：{record.paired_non_tie_days} 个非平局日里至少赢 {needed} 天"
    slot_text = f", 位{record.slot_no}" if record.slot_no is not None else ""

    content_lines = [
        f"**母体策略 ID**: #{record.parent_strategy_id} {record.parent_name}".strip(),
        (
            f"**挑战者 ID**: #{record.challenger_strategy_id} "
            f"(Gen {record.generation}{slot_text}) {record.challenger_name}".strip()
        ),
        (
            f"**前向净收益**: 挑战者 **{_pct(record.challenger_net_return_pct)}** vs "
            f"母体 **{_pct(record.parent_net_return_pct)}** "
            f"(超额: **{_pct(record.excess_return_pct)}**)"
        ),
        (
            f"**最大回撤对比**: 挑战者 **{_pct(record.challenger_max_drawdown_pct, False)}** vs "
            f"母体 **{_pct(record.parent_max_drawdown_pct, False)}**"
        ),
        f"**14日单侧符号检验**: {p_val_str}",
        (
            f"**实测进度**: {_count(record.observed_hours)}/{record.target_hours} 小时桶 | "
            f"平仓成交: 母体 {_count(record.parent_trades)} 笔 / "
            f"挑战者 {_count(record.challenger_trades)} 笔"
        ),
        f"**当前状态**: `{record.state}` | 判定: {record.reason or '正常积累前向证据'}",
    ]

    if milestone == "ADOPTED":
        content_lines.append(
            "🔒 **执行动作**: 母体已锁定仅平仓 (reduce-only)，配额原子转移至挑战者，"
            "挑战者已重命名更迭代际。"
        )
    elif milestone == "COMPLETED":
        content_lines.append(
            "✅ **执行动作**: 母体仓位已清空并确认暂停 (指标保留留档)，"
            f"Gen {record.generation} 正式作为 Primary 主力策略独立运行！"
        )
    elif milestone == "REQUIRES_ADMIN":
        content_lines.append(
            "🔑 **提示**: 当前前向证据已全量满足，BitPro 未开启自动托管，"
            "请点击下方链接登录 BitPro 控制台由操作者采纳或取消。"
        )
    elif milestone == "CANCELLED":
        if record.cancellation_kind == "operator":
            content_lines.append(
                "🛑 **执行动作**: 操作者已在 BitPro 取消该场接力，挑战者不再参与交接；"
                "再次赛马需操作者重新放行候选。"
            )
        else:
            # Unknown source (older BitPro/target or an unrecognised kind): never name a culprit.
            if record.cancellation_reason:
                content_lines.append(f"**取消说明**: {record.cancellation_reason}")
            content_lines.append("🛑 **执行动作**: BitPro 已取消该场接力，挑战者不再参与交接。")
    elif milestone in _SYSTEM_CANCEL_MILESTONES.values():
        content_lines.extend(_system_elimination_lines(record, milestone))

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": card_title},
                "template": card_color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "\n".join(content_lines),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "前往 BitPro 孪生监控与接力控制台",
                            },
                            "type": "primary",
                            "url": monitor_url,
                        }
                    ],
                },
            ],
        },
    }


def dispatch_race_feishu_card(
    record: RacePairRecord,
    milestone: str,
    *,
    webhook_url: str | None = None,
    console_url: str = "",
) -> tuple[bool, str]:
    """Dispatch race judge milestone alert to Feishu webhook."""
    settings = get_settings()
    url = (webhook_url or settings.feishu_webhook_url or "").strip()
    if not url:
        logger.info("Feishu webhook not configured; skipping race judge alert: %s", milestone)
        return False, "skipped_no_webhook"

    active_console = console_url or settings.bitpro_console_url or "https://bitpro.notenap.com"
    payload = build_race_feishu_card(record, milestone, console_url=active_console)

    try:
        resp = httpx.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("code") in (0, None):
            logger.info("Successfully dispatched Feishu race card: %s", milestone)
            return True, "sent_interactive_card"
        logger.warning("Feishu card rejected with response: %s", data)
        return False, f"rejected:{data}"
    except Exception as exc:
        logger.error("Failed to dispatch Feishu race card for %s: %s", milestone, exc)
        return False, f"failed:{type(exc).__name__}"


class RaceJudgeDaemon:
    """Evaluates twin paper strategy races and manages automated relay lifecycle."""

    def __init__(
        self,
        db: Database | None = None,
        *,
        settings: Settings | None = None,
        bitpro_adapter: BitProToolAdapter | None = None,
        history_file: Path | None = None,
        state_file: Path | None = None,
        auto_adopt: bool | None = None,
        netting_service: PositionNettingRelayService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.bitpro_adapter = bitpro_adapter or BitProToolAdapter()
        # Netting handover needs real target holdings; BitPro relays drain instead.
        self.netting_service = netting_service
        self.history_file = (
            history_file
            if history_file is not None
            else Path("data/paper_self_healing_history.json")
        )
        self.state_file = (
            state_file if state_file is not None else Path("data/paper_race_judge_state.json")
        )
        self.auto_adopt = (
            auto_adopt if auto_adopt is not None else self.settings.race_judge_auto_adopt
        )
        # A handover in motion is watched every sweep; a lane that is only accumulating
        # evidence is read slowly, because every read makes BitPro reload fourteen days of
        # hourly equity for that lane and a parent may race several lanes at once.
        self.interval = max(5.0, float(getattr(self.settings, "race_judge_interval_seconds", 60)))
        self.observing_interval = max(
            self.interval,
            float(getattr(self.settings, "race_judge_observing_interval_seconds", 900)),
        )
        self._records: dict[str, RacePairRecord] = {}
        self._load_state()

    def _pair_key(
        self, target_id: str, parent_id: str | int, challenger_id: str | int
    ) -> str:
        return json.dumps([target_id, parent_id, challenger_id], separators=(",", ":"))

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    rec = RacePairRecord.from_dict(item)
                    key = self._pair_key(
                        rec.target_id, rec.parent_strategy_id, rec.challenger_strategy_id
                    )
                    self._records[key] = rec
        except Exception as exc:
            logger.warning("Failed to load race judge state: %s", exc)

    def _persist_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = [rec.to_dict() for rec in self._records.values()]
            self.state_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist race judge state: %s", exc)

    def _list_plans(self) -> list[dict[str, Any]]:
        """BitPro's persisted relay plans (one cheap read); unreadable means none, not an error."""
        list_plans = getattr(self.bitpro_adapter, "paper_relay_plans", None)
        if not callable(list_plans):
            return []
        try:
            return [plan for plan in list_plans() or [] if isinstance(plan, dict)]
        except Exception as exc:
            logger.warning("Failed to list BitPro relay plans: %s", exc)
            return []

    def discover_active_pairs(
        self, plans: list[dict[str, Any]] | None = None
    ) -> list[tuple[str, str | int, str | int, int]]:
        """Find all deployed twin pairings from self-healing history, BitPro plans or state.

        A parent may race several challengers (one per variant slot): every live
        (parent, challenger) plan is its own pair.
        """
        pairs: dict[tuple[str, str | int, str | int], int] = {}

        if self.history_file.exists():
            try:
                raw = json.loads(self.history_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for item in raw:
                        is_deployed = bool(
                            item.get("bitpro_deployed") or item.get("quantlab_deployed")
                        )
                        if not is_deployed:
                            continue
                        target_raw = item.get("target_id")
                        if target_raw is None:
                            if bool(item.get("quantlab_deployed")) == bool(
                                item.get("bitpro_deployed")
                            ):
                                logger.warning(
                                    "Skipping race history row without unambiguous target identity"
                                )
                                continue
                            target_raw = (
                                "quantlab" if item.get("quantlab_deployed") else "bitpro"
                            )
                        target_id = str(target_raw)
                        sid = (
                            item.get("quantlab_strategy_id")
                            if target_id == "quantlab"
                            else item.get("bitpro_strategy_id")
                        )
                        pid_raw = item.get("parent_strategy_id")
                        if not sid or pid_raw is None:
                            continue
                        gen = int(item.get("generation", 1))
                        pid: str | int = pid_raw if isinstance(pid_raw, int) else str(pid_raw)
                        cid: str | int = sid if isinstance(sid, int) else str(sid)
                        pairs[(target_id, pid, cid)] = gen
            except Exception as exc:
                logger.warning("Failed to read self-healing history for pairs: %s", exc)

        # BitPro's persisted relay plans are authoritative for which races are live,
        # including the ones created by its own automatic enrollment.
        for plan in self._list_plans() if plans is None else plans:
            if not isinstance(plan, dict) or plan.get("state") not in _LIVE_PLAN_STATES:
                continue
            plan_pid, plan_cid = plan.get("parent_id"), plan.get("challenger_id")
            if isinstance(plan_pid, int) and isinstance(plan_cid, int):
                pairs[("bitpro", plan_pid, plan_cid)] = int(plan.get("generation") or 1)

        for rec in self._records.values():
            if rec.state not in _TERMINAL_STATES:
                pair = (rec.target_id, rec.parent_strategy_id, rec.challenger_strategy_id)
                if pair not in pairs:
                    pairs[pair] = rec.generation

        return [(target, pid, cid, gen) for (target, pid, cid), gen in pairs.items()]

    def evaluate_pair(
        self,
        parent_id: str | int,
        challenger_id: str | int,
        generation: int = 1,
        target_id: str | None = None,
    ) -> RacePairRecord:
        """Query target relay status, evaluate forward gates, and take automated action."""
        lookup_target = target_id or "bitpro"
        key = self._pair_key(lookup_target, parent_id, challenger_id)
        record = self._records.get(key)
        resolved_target = (
            target_id
            or (record.target_id if record is not None else None)
            or "bitpro"
        )
        if record is None:
            record = RacePairRecord(
                parent_strategy_id=parent_id,
                challenger_strategy_id=challenger_id,
                target_id=resolved_target,
                generation=generation,
                auto_adopt_enabled=False,
            )
            self._records[key] = record
        else:
            record.target_id = resolved_target

        adapter: Any = self.bitpro_adapter
        if resolved_target not in {"bitpro", "quantlab"}:
            record.reason = f"unsupported_target:{resolved_target}"
            record.updated_at = datetime.now(UTC).isoformat()
            self._persist_state()
            return record
        if resolved_target == "quantlab":
            record.target_id = "quantlab"
            from hypertrade.targets.registry import adapter_for_target

            try:
                adapter = adapter_for_target("quantlab")
            except Exception as exc:
                record.reason = f"target_adapter_unavailable:{type(exc).__name__}"
                record.updated_at = datetime.now(UTC).isoformat()
                self._persist_state()
                return record

        try:
            status_data = adapter.paper_relay_status(
                parent_id=parent_id, challenger_id=challenger_id
            )
        except Exception as exc:
            logger.error(
                "Failed to query relay status for pair (%s, %s): %s", parent_id, challenger_id, exc
            )
            record.reason = f"查询状态失败: {exc}"
            record.updated_at = datetime.now(UTC).isoformat()
            self._persist_state()
            return record

        plan = status_data.get("plan")
        if plan is None and record.plan_seen and record.state in _LIVE_PLAN_STATES:
            # The target no longer keeps this lane (its seat went to a new challenger, or the
            # plan was cleaned up). Fresh evidence for a pair with no plan would be a
            # candidate evaluation, not this race, so keep the last mirrored evidence and
            # stop polling. Whatever ended the lane was announced by BitPro itself.
            record.state = "ended"
            record.reason = "BitPro 已不再保留该赛道（位置已被新的挑战者接管，或计划已被清理）"
            return self._finish_evaluation(record)

        proof = status_data.get("proof") or (plan or {}).get("proof") or {}
        progress = proof.get("progress") or {}

        record.eligible = bool(proof.get("eligible", False))
        record.reason = str(proof.get("reason", ""))
        record.proof_sha256 = proof.get("proof_sha256")
        # Full-window proofs carry observed_points; partial ones only report progress.
        record.observed_hours = _opt_int(
            proof.get("observed_points", progress.get("paired_points"))
        )
        record.sign_test_p = _opt_float(proof.get("sign_test_p"))
        record.positive_days = int(proof.get("positive_days") or 0)
        record.paired_non_tie_days = int(proof.get("paired_non_tie_days") or 0)
        record.excess_return_pct = _opt_float(proof.get("excess_return_pct"))
        # The level this lane is judged at depends on the parent's variant slot count.
        gate_alpha = _opt_float(proof.get("gate_alpha"))
        if gate_alpha is not None and gate_alpha > 0:
            record.gate_alpha = gate_alpha

        net_returns = proof.get("net_return_pct")
        if isinstance(net_returns, list) and len(net_returns) >= 2:
            record.parent_net_return_pct = _opt_float(net_returns[0])
            record.challenger_net_return_pct = _opt_float(net_returns[1])

        drawdowns = proof.get("observed_drawdown_pct")
        if isinstance(drawdowns, list) and len(drawdowns) >= 2:
            record.parent_max_drawdown_pct = _opt_float(drawdowns[0])
            record.challenger_max_drawdown_pct = _opt_float(drawdowns[1])

        fills = proof.get("closed_fills") or progress.get("closed_fills")
        if isinstance(fills, list) and len(fills) >= 2:
            record.parent_trades = _opt_int(fills[0])
            record.challenger_trades = _opt_int(fills[1])

        # The target owns the relay state machine (gate, adoption, drain, pause).
        # The judge only mirrors that state and notifies; it never calls
        # adopt/enable_auto, so an operator's "disable auto" on the target holds.
        if plan:
            record.plan_seen = True
            record.state = str(plan.get("state") or record.state)
            record.generation = int(plan.get("generation") or record.generation)
            record.slot_no = _slot_no(plan.get("slot_no")) or record.slot_no
            auto_enabled = bool(status_data.get("auto_enabled", plan.get("auto_enabled")))
        else:
            auto_enabled = False
        record.action_taken = None

        if record.state in _LIVE_PLAN_STATES:
            self._reset_finished_race(record)
        elif record.state == "cancelled":
            raw = status_data.get("cancellation") or (plan or {}).get("cancellation")
            fields = raw if isinstance(raw, dict) else {}
            record.cancellation_kind = _cancellation_kind(raw)
            record.cancellation_actor = _opt_text(fields.get("actor"))
            record.cancellation_reason = _opt_text(fields.get("reason"))
            record.cancellation_metrics = _cancellation_metrics(raw)
            record.cancellation_cooldown_hours = _cancellation_cooldown_hours(raw)

        if record.state == "observing" and record.eligible and record.proof_sha256:
            milestone = "ELIGIBLE" if auto_enabled else "REQUIRES_ADMIN"
            record.requires_admin_authorization = not auto_enabled
            if milestone not in record.feishu_notified_states:
                ok, _ = dispatch_race_feishu_card(record, milestone)
                if ok:
                    record.feishu_notified_states.append(milestone)
        elif record.state == "draining" and "ADOPTED" not in record.feishu_notified_states:
            ok, _ = dispatch_race_feishu_card(record, "ADOPTED")
            if ok:
                record.feishu_notified_states.append("ADOPTED")
        elif record.state == "completed" and "COMPLETED" not in record.feishu_notified_states:
            # "transferred" still waits for the parent pause; only completion is final.
            ok, _ = dispatch_race_feishu_card(record, "COMPLETED")
            if ok:
                record.feishu_notified_states.append("COMPLETED")
        elif record.state == "cancelled" and not _CANCEL_MARKERS & set(
            record.feishu_notified_states
        ):
            # One cancel-type card per race, worded by who ended it: an operator cancel is not
            # a gate verdict, a system elimination is not an operator's doing, and a lane
            # that merely lost its seat to an adopted sibling needs no card. "REJECTED" is
            # the marker the first release recorded for an operator cancel; any marker counts.
            kind = record.cancellation_kind
            if kind in _QUIET_CANCEL_KINDS:
                record.feishu_notified_states.append(_QUIET_CANCEL_KINDS[kind])
            else:
                milestone = _SYSTEM_CANCEL_MILESTONES.get(kind or "", "CANCELLED")
                ok, _ = dispatch_race_feishu_card(record, milestone)
                if ok:
                    record.feishu_notified_states.append(milestone)

        return self._finish_evaluation(record)

    def _reset_finished_race(self, record: RacePairRecord) -> None:
        """A re-admitted challenger races again: the earlier cancellation no longer holds."""
        if record.cancellation_kind or _CANCEL_MARKERS & set(record.feishu_notified_states):
            record.cancellation_kind = None
            record.cancellation_actor = None
            record.cancellation_reason = None
            record.cancellation_metrics = None
            record.cancellation_cooldown_hours = None
            record.feishu_notified_states = [
                marker for marker in record.feishu_notified_states if marker not in _CANCEL_MARKERS
            ]

    def _poll_delay(self, record: RacePairRecord) -> float:
        """Seconds until the pair needs another look."""
        if record.state in ("draining", "transferred"):
            return self.interval  # a handover is in motion
        announced = bool({"ELIGIBLE", "REQUIRES_ADMIN"} & set(record.feishu_notified_states))
        if (
            record.state == "observing"
            and record.eligible
            and (not announced or not record.requires_admin_authorization)
        ):
            return self.interval  # about to be announced, or BitPro is about to adopt it
        return self.observing_interval

    def _finish_evaluation(self, record: RacePairRecord) -> RacePairRecord:
        now = time.time()
        record.next_poll_at = now + self._poll_delay(record)
        record.updated_at = datetime.now(UTC).isoformat()
        self._persist_state()
        return record

    def scan_and_judge_all(self, *, force: bool = False) -> list[RacePairRecord]:
        """Run one evaluation sweep across all active twin pairs.

        Lanes that are only accumulating evidence are skipped until their next poll time;
        `force` (the operator's "run now") looks at every pair.
        """
        plans = self._list_plans()
        # The plan listing already says which lanes BitPro cancelled: look at those now
        # instead of waiting out their slow poll, so the card arrives promptly.
        for plan in plans:
            if plan.get("state") != "cancelled":
                continue
            parent_id, challenger_id = plan.get("parent_id"), plan.get("challenger_id")
            if not isinstance(parent_id, (int, str)) or not isinstance(challenger_id, (int, str)):
                continue
            rec = self._records.get(self._pair_key("bitpro", parent_id, challenger_id))
            if rec is not None and rec.state not in _TERMINAL_STATES:
                rec.next_poll_at = 0.0
        pairs = self.discover_active_pairs(plans=plans)
        now = time.time()
        results: list[RacePairRecord] = []
        for target_id, pid, cid, gen in pairs:
            known = self._records.get(self._pair_key(target_id, pid, cid))
            if not force and known is not None and known.next_poll_at > now:
                continue
            try:
                rec = self.evaluate_pair(pid, cid, gen, target_id=target_id)
                results.append(rec)
            except Exception as exc:
                logger.exception("Error evaluating pair (%s, %s): %s", pid, cid, exc)
        return results

    def get_records(self) -> list[dict[str, Any]]:
        """Return all persisted race judge records."""
        return [rec.to_dict() for rec in self._records.values()]
