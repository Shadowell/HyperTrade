"""Automated Race Judge Daemon and Relay Scheduler for BitPro paper twin strategies.

Monitors running twin strategy pairs (parent vs. healed offspring/challenger),
evaluates forward evidence gates (14-day hourly equity, drawdown, and paired sign test),
and triggers automated handover/adoption and operator notifications.
"""

from __future__ import annotations

import json
import logging
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


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "未知"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _count(value: int | None) -> str:
    return "未知" if value is None else str(value)


@dataclass
class RacePairRecord:
    """Audit and state record for a monitored twin race pair."""

    parent_strategy_id: str | int
    challenger_strategy_id: str | int
    target_id: str = "bitpro"
    generation: int = 1
    parent_name: str = ""
    challenger_name: str = ""
    state: str = "observing"  # observing | draining | transferred | completed | rejected
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
    }
    title_map = {
        "ELIGIBLE": "🏁 【BitPro 策略接力已达标】前向门禁全量通过",
        "ADOPTED": "🚀 【BitPro 策略接力已触发】配额交接，母体转入 Draining",
        "COMPLETED": "🏆 【BitPro 策略接力圆满完成】Gen N 晋升 Primary 主力",
        "REQUIRES_ADMIN": "⚠️ 【BitPro 策略接力待授权】前向门禁已达标需管理员采纳",
        "REJECTED": "❌ 【BitPro 策略接力未通过】挑战者被淘汰",
        # 操作者主动终止不是门禁判负，不能写成“挑战者被淘汰”。
        "CANCELLED": "⏹ 【BitPro 策略接力已取消】操作者终止赛马，母体继续担任主力",
    }

    card_color = color_map.get(milestone, "blue")
    card_title = title_map.get(milestone, f"🏁 【BitPro 策略赛马更新】{milestone}")

    p_val_str = (
        f"{record.sign_test_p:.4f} (<= 0.05 显著)" if record.sign_test_p is not None else "计算中"
    )

    content_lines = [
        f"**母体策略 ID**: #{record.parent_strategy_id} {record.parent_name}".strip(),
        (
            f"**挑战者 ID**: #{record.challenger_strategy_id} "
            f"(Gen {record.generation}) {record.challenger_name}".strip()
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
        content_lines.append(
            "🛑 **执行动作**: 操作者已在 BitPro 取消该场接力，挑战者不再参与交接；"
            "再次赛马需操作者重新放行候选。"
        )

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

    def discover_active_pairs(self) -> list[tuple[str, str | int, str | int, int]]:
        """Find all deployed twin pairings from self-healing history or state."""
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
        list_plans = getattr(self.bitpro_adapter, "paper_relay_plans", None)
        if callable(list_plans):
            try:
                for plan in list_plans() or []:
                    if not isinstance(plan, dict) or plan.get("state") not in _LIVE_PLAN_STATES:
                        continue
                    plan_pid, plan_cid = plan.get("parent_id"), plan.get("challenger_id")
                    if isinstance(plan_pid, int) and isinstance(plan_cid, int):
                        pairs[("bitpro", plan_pid, plan_cid)] = int(plan.get("generation") or 1)
            except Exception as exc:
                logger.warning("Failed to list BitPro relay plans: %s", exc)

        for rec in self._records.values():
            if rec.state not in ("completed", "rejected", "cancelled"):
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
            record.state = str(plan.get("state") or record.state)
            record.generation = int(plan.get("generation") or record.generation)
            auto_enabled = bool(status_data.get("auto_enabled", plan.get("auto_enabled")))
        else:
            auto_enabled = False
        record.action_taken = None

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
        elif record.state == "cancelled" and not {"CANCELLED", "REJECTED"} & set(
            record.feishu_notified_states
        ):
            # An operator cancel is not a gate verdict. "REJECTED" is the marker the first
            # release recorded for this event; honour it so that card is not sent twice.
            ok, _ = dispatch_race_feishu_card(record, "CANCELLED")
            if ok:
                record.feishu_notified_states.append("CANCELLED")

        record.updated_at = datetime.now(UTC).isoformat()
        self._persist_state()
        return record

    def scan_and_judge_all(self) -> list[RacePairRecord]:
        """Run one evaluation sweep across all active twin pairs."""
        pairs = self.discover_active_pairs()
        results: list[RacePairRecord] = []
        for target_id, pid, cid, gen in pairs:
            try:
                rec = self.evaluate_pair(pid, cid, gen, target_id=target_id)
                results.append(rec)
            except Exception as exc:
                logger.exception("Error evaluating pair (%s, %s): %s", pid, cid, exc)
        return results

    def get_records(self) -> list[dict[str, Any]]:
        """Return all persisted race judge records."""
        return [rec.to_dict() for rec in self._records.values()]
