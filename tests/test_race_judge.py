"""Tests for BitPro Race Judge Daemon and Automated Relay Scheduler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypertrade.arc.evolution_models import ArcForwardOutcome
from hypertrade.arc.forward_outcomes import ForwardOutcomeLedger
from hypertrade.bitpro.mcp import BitProToolAdapter
from hypertrade.db import Database
from hypertrade.paper.race_judge import (
    RaceJudgeDaemon,
    RacePairRecord,
    build_race_feishu_card,
    dispatch_race_feishu_card,
)
from sqlalchemy import select


def test_race_pair_record_serialization() -> None:
    rec = RacePairRecord(
        parent_strategy_id=10,
        challenger_strategy_id=20,
        generation=2,
        parent_name="Parent CTA",
        challenger_name="Challenger CTA",
        state="observing",
        eligible=False,
        reason="小时桶不足",
        proof_sha256="abc123",
        observed_hours=120,
        target_hours=337,
        parent_trades=15,
        challenger_trades=18,
        parent_net_return_pct=5.5,
        challenger_net_return_pct=9.2,
        excess_return_pct=3.7,
        parent_max_drawdown_pct=4.1,
        challenger_max_drawdown_pct=3.2,
        sign_test_p=0.032,
        positive_days=11,
        paired_non_tie_days=13,
        auto_adopt_enabled=True,
    )
    data = rec.to_dict()
    assert data["parent_strategy_id"] == 10
    assert data["challenger_strategy_id"] == 20
    assert data["excess_return_pct"] == 3.7
    assert data["sign_test_p"] == 0.032

    reconstructed = RacePairRecord.from_dict(data)
    assert reconstructed.parent_strategy_id == 10
    assert reconstructed.challenger_strategy_id == 20
    assert reconstructed.generation == 2
    assert reconstructed.sign_test_p == 0.032


def test_build_race_feishu_card() -> None:
    rec = RacePairRecord(
        parent_strategy_id=1,
        challenger_strategy_id=2,
        generation=2,
        parent_net_return_pct=2.0,
        challenger_net_return_pct=6.5,
        excess_return_pct=4.5,
        parent_max_drawdown_pct=5.0,
        challenger_max_drawdown_pct=3.8,
        sign_test_p=0.025,
        observed_hours=337,
        parent_trades=35,
        challenger_trades=40,
        state="draining",
        reason="前向门禁通过",
    )
    for milestone, expected_color in [
        ("ELIGIBLE", "blue"),
        ("ADOPTED", "carmine"),
        ("COMPLETED", "green"),
        ("REQUIRES_ADMIN", "orange"),
    ]:
        card = build_race_feishu_card(rec, milestone, console_url="https://bitpro.test")
        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["template"] == expected_color
        btn = card["card"]["elements"][2]["actions"][0]
        assert "strategyId=1" in btn["url"]
        assert "challengerId=2" in btn["url"]


def test_dispatch_race_feishu_card_skipped_no_webhook() -> None:
    rec = RacePairRecord(parent_strategy_id=1, challenger_strategy_id=2)
    delivered, status = dispatch_race_feishu_card(rec, "ELIGIBLE", webhook_url="")
    assert delivered is False
    assert status == "skipped_no_webhook"


def test_dispatch_race_feishu_card_success() -> None:
    rec = RacePairRecord(parent_strategy_id=1, challenger_strategy_id=2)
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "msg": "success"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        delivered, status = dispatch_race_feishu_card(
            rec, "ADOPTED", webhook_url="https://feishu.example/webhook"
        )
        assert delivered is True
        assert status == "sent_interactive_card"


def test_discover_active_pairs(tmp_path: Path) -> None:
    history_file = tmp_path / "paper_history.json"
    history_file.write_text(
        json.dumps(
            [
                {
                    "parent_strategy_id": "100",
                    "offspring_strategy_id": "offspring_1",
                    "generation": 2,
                    "bitpro_deployed": True,
                    "bitpro_strategy_id": 105,
                },
                {
                    "parent_strategy_id": "200",
                    "offspring_strategy_id": "offspring_2",
                    "generation": 1,
                    "bitpro_deployed": False,  # Not deployed to BitPro
                    "bitpro_strategy_id": None,
                },
            ]
        ),
        encoding="utf-8",
    )

    state_file = tmp_path / "state.json"
    daemon = RaceJudgeDaemon(
        history_file=history_file,
        state_file=state_file,
    )
    pairs = daemon.discover_active_pairs()
    assert pairs == [("bitpro", "100", 105, 2)]


def test_discovery_namespaces_same_opaque_ids_by_target(tmp_path: Path) -> None:
    history_file = tmp_path / "paper_history.json"
    history_file.write_text(
        json.dumps(
            [
                {
                    "target_id": "bitpro",
                    "parent_strategy_id": "42",
                    "bitpro_deployed": True,
                    "bitpro_strategy_id": 99,
                    "generation": 2,
                },
                {
                    "target_id": "quantlab",
                    "parent_strategy_id": "42",
                    "quantlab_deployed": True,
                    "quantlab_strategy_id": "99",
                    "generation": 3,
                },
            ]
        ),
        encoding="utf-8",
    )
    daemon = RaceJudgeDaemon(
        history_file=history_file, state_file=tmp_path / "state.json"
    )
    assert daemon.discover_active_pairs() == [
        ("bitpro", "42", 99, 2),
        ("quantlab", "42", "99", 3),
    ]


def test_quantlab_adapter_failure_never_falls_back_to_bitpro(tmp_path: Path) -> None:
    bitpro = MagicMock(spec=BitProToolAdapter)
    daemon = RaceJudgeDaemon(
        bitpro_adapter=bitpro, state_file=tmp_path / "state.json"
    )
    with patch(
        "hypertrade.targets.registry.adapter_for_target",
        side_effect=RuntimeError("quantlab unavailable"),
    ):
        record = daemon.evaluate_pair("42", "99", target_id="quantlab")
    assert record.target_id == "quantlab"
    assert record.reason == "target_adapter_unavailable:RuntimeError"
    bitpro.paper_relay_status.assert_not_called()


def test_unknown_target_never_dispatches_to_bitpro(tmp_path: Path) -> None:
    bitpro = MagicMock(spec=BitProToolAdapter)
    daemon = RaceJudgeDaemon(
        bitpro_adapter=bitpro, state_file=tmp_path / "state.json"
    )
    record = daemon.evaluate_pair("42", "99", target_id="unknown-market")
    assert record.reason == "unsupported_target:unknown-market"
    bitpro.paper_relay_status.assert_not_called()


def test_evaluate_pair_observing_accumulating(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = {
        "plan": {
            "parent_id": 1,
            "challenger_id": 2,
            "state": "observing",
            "auto_enabled": True,
            "generation": 2,
        },
        "proof": {
            "eligible": False,
            "reason": "观测小时桶不足 120/337",
            "proof_sha256": "hash_123",
            "observed_points": 120,
            "net_return_pct": [3.0, 5.0],
            "observed_drawdown_pct": [4.0, 3.5],
            "excess_return_pct": 2.0,
            "closed_fills": [12, 15],
            "sign_test_p": 0.12,
        },
    }

    state_file = tmp_path / "state.json"
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=state_file,
        auto_adopt=True,
    )

    rec = daemon.evaluate_pair(1, 2, generation=2)
    assert rec.state == "observing"
    assert rec.eligible is False
    assert rec.observed_hours == 120
    assert rec.parent_net_return_pct == 3.0
    assert rec.challenger_net_return_pct == 5.0
    assert rec.excess_return_pct == 2.0
    assert rec.sign_test_p == 0.12
    assert "不足" in rec.reason


def _eligible_status(proof_sha: str, *, auto_enabled: bool) -> dict:
    return {
        "plan": {
            "parent_id": 1,
            "challenger_id": 2,
            "state": "observing",
            "auto_enabled": auto_enabled,
            "generation": 2,
        },
        "auto_enabled": auto_enabled,
        "proof": {
            "eligible": True,
            "reason": "前向门禁通过",
            "proof_sha256": proof_sha,
            "observed_points": 337,
            "net_return_pct": [4.0, 9.5],
            "observed_drawdown_pct": [4.5, 3.2],
            "excess_return_pct": 5.5,
            "closed_fills": [35, 42],
            "sign_test_p": 0.015,
        },
    }


def test_eligible_race_is_announced_never_adopted_by_judge(tmp_path: Path) -> None:
    """BitPro is the only relay controller: even auto_adopt=True never writes."""
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = _eligible_status("e" * 64, auto_enabled=True)
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=tmp_path / "state.json",
        auto_adopt=True,
    )

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        mock_dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)

    assert rec.eligible is True
    assert rec.state == "observing"
    assert rec.action_taken is None
    assert rec.handover_plan_id is None
    mock_adapter.paper_relay_control.assert_not_called()
    assert "ELIGIBLE" in rec.feishu_notified_states


def test_operator_disabled_auto_gets_admin_prompt_not_adoption(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = _eligible_status("f" * 64, auto_enabled=False)
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=tmp_path / "state.json",
        auto_adopt=True,
    )

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        mock_dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)

    assert rec.requires_admin_authorization is True
    mock_adapter.paper_relay_control.assert_not_called()
    mock_dispatch.assert_called_once()
    assert "REQUIRES_ADMIN" in rec.feishu_notified_states


def test_unknown_evidence_is_not_rendered_as_zero(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = {
        "plan": {"parent_id": 1, "challenger_id": 2, "state": "observing", "generation": 2},
        "proof": {
            "eligible": False,
            "reason": "等待完整前向证据",
            "progress": {"paired_points": 40},
        },
    }
    daemon = RaceJudgeDaemon(bitpro_adapter=mock_adapter, state_file=tmp_path / "state.json")
    rec = daemon.evaluate_pair(1, 2, generation=2)
    assert rec.observed_hours == 40
    assert rec.parent_net_return_pct is None and rec.excess_return_pct is None
    card = build_race_feishu_card(rec, "ELIGIBLE")
    text = card["card"]["elements"][0]["text"]["content"]
    assert "未知" in text and "+0.00%" not in text


def test_discovery_reads_live_bitpro_relay_plans(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_plans.return_value = [
        {"parent_id": 7, "challenger_id": 8, "state": "observing", "generation": 3},
        {"parent_id": 9, "challenger_id": 10, "state": "completed", "generation": 2},
        {"parent_id": 11, "challenger_id": 12, "state": "cancelled", "generation": 2},
    ]
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=tmp_path / "state.json",
        history_file=tmp_path / "missing-history.json",
    )
    assert daemon.discover_active_pairs() == [("bitpro", 7, 8, 3)]


def test_evaluate_pair_completed_lifecycle(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = {
        "plan": {
            "parent_id": 1,
            "challenger_id": 2,
            "state": "completed",
            "generation": 2,
        },
        "proof": {"eligible": True, "observed_points": 337},
    }

    state_file = tmp_path / "state.json"
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=state_file,
    )

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        mock_dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)

        assert rec.state == "completed"
        mock_dispatch.assert_called_once()
        assert "COMPLETED" in rec.feishu_notified_states


def _cancelled_status() -> dict:
    return {
        "plan": {"parent_id": 1, "challenger_id": 2, "state": "cancelled", "generation": 2},
        "proof": {"eligible": False, "reason": "等待完整前向证据"},
    }


def test_operator_cancel_is_announced_once_as_cancelled_not_eliminated(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = _cancelled_status()
    daemon = RaceJudgeDaemon(bitpro_adapter=mock_adapter, state_file=tmp_path / "state.json")

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        mock_dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)
        daemon.evaluate_pair(1, 2, generation=2)

    assert rec.state == "cancelled"
    mock_dispatch.assert_called_once()
    assert mock_dispatch.call_args.args[1] == "CANCELLED"
    assert rec.feishu_notified_states == ["CANCELLED"]
    mock_adapter.paper_relay_control.assert_not_called()


def test_cancel_card_already_sent_under_legacy_marker_is_not_repeated(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    mock_adapter.paper_relay_status.return_value = _cancelled_status()
    daemon = RaceJudgeDaemon(bitpro_adapter=mock_adapter, state_file=tmp_path / "state.json")
    legacy = RacePairRecord(
        parent_strategy_id=1,
        challenger_strategy_id=2,
        target_id="bitpro",
        generation=2,
        feishu_notified_states=["REJECTED"],
    )
    daemon._records[daemon._pair_key("bitpro", 1, 2)] = legacy

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        daemon.evaluate_pair(1, 2, generation=2)

    mock_dispatch.assert_not_called()


def test_cancel_card_says_cancelled_and_never_claims_the_challenger_was_eliminated() -> None:
    rec = RacePairRecord(parent_strategy_id=1, challenger_strategy_id=2, state="cancelled")
    card = build_race_feishu_card(rec, "CANCELLED", console_url="https://bitpro.test")

    title = card["card"]["header"]["title"]["content"]
    text = card["card"]["elements"][0]["text"]["content"]
    assert card["card"]["header"]["template"] == "grey"
    assert "已取消" in title and "淘汰" not in title
    assert "取消" in text and "淘汰" not in text


def test_bitpro_tool_adapter_relay_methods() -> None:
    client_mock = MagicMock()
    adapter = BitProToolAdapter(client=client_mock)

    client_mock.call_tool.return_value = {"success": True, "data": {"plan": None}}
    res = adapter.paper_relay_status(parent_id=5, challenger_id=6)
    assert res == {"success": True, "data": {"plan": None}}
    client_mock.call_tool.assert_called_with(
        "paper_relay_status", {"parent_id": 5, "challenger_id": 6}
    )

    client_mock.call_tool.return_value = {"success": True, "data": {"status": "ok"}}
    res2 = adapter.paper_relay_control(
        parent_id=5, action="adopt", challenger_id=6, proof_sha256="abc" * 21 + "a"
    )
    assert res2 == {"success": True, "data": {"status": "ok"}}
    client_mock.call_tool.assert_called_with(
        "paper_relay_control",
        {
            "parent_id": 5,
            "action": "adopt",
            "challenger_id": 6,
            "proof_sha256": "abc" * 21 + "a",
        },
    )


# --- Variant slots: who ended a lane, lane numbers, the per-slot pass line, slow polling ---


def _lane_status(
    cancellation: object = None, *, state: str = "cancelled", slot_no: int | None = 2
) -> dict:
    status: dict = {
        "plan": {
            "parent_id": 1,
            "challenger_id": 2,
            "state": state,
            "generation": 2,
            **({"slot_no": slot_no} if slot_no is not None else {}),
        },
        "proof": {"eligible": False, "reason": "超额、回撤或配对置信门禁未通过"},
    }
    if cancellation is not None:
        status["cancellation"] = cancellation
    return status


def _futility_cancellation() -> dict:
    return {
        "actor": "system:futility",
        "by_system": True,
        "kind": "futility",
        "state_before": "observing",
        "reason": "系统淘汰（无望）：同窗超额-7.66个百分点；已连续24小时满足淘汰条件",
        "cancelled_at": "2026-10-20T08:00:00+00:00",
        "detail": {
            "kind": "futility",
            "metrics": {
                "common_hours": 96,
                "closed_fills": [30, 22],
                "return_pct": [-1.78, -9.44],
                "excess_pp": -7.66,
                "drawdown_pct": [3.1, 11.2],
                "window": ["2026-10-16", "2026-10-20"],
            },
            "thresholds": {"reenroll_cooldown_hours": 24},
            "held_hours": 25.0,
        },
    }


def _daemon(tmp_path: Path, adapter: MagicMock) -> RaceJudgeDaemon:
    return RaceJudgeDaemon(
        bitpro_adapter=adapter,
        state_file=tmp_path / "state.json",
        history_file=tmp_path / "missing-history.json",
    )


def _card_text(rec: RacePairRecord, milestone: str) -> tuple[str, str]:
    card = build_race_feishu_card(rec, milestone, console_url="https://bitpro.test")
    title = card["card"]["header"]["title"]["content"]
    return title, card["card"]["elements"][0]["text"]["content"]


def test_system_futility_cancel_gets_its_own_card_not_the_operator_wording(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _daemon(tmp_path, adapter)

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)
        daemon.evaluate_pair(1, 2, generation=2)

    dispatch.assert_called_once()  # one cancel-type card per race
    assert dispatch.call_args.args[1] == "FUTILITY"
    assert rec.feishu_notified_states == ["FUTILITY"]
    assert rec.cancellation_kind == "futility" and rec.slot_no == 2
    title, text = _card_text(rec, "FUTILITY")
    card = build_race_feishu_card(rec, "FUTILITY")
    assert card["card"]["header"]["template"] == "orange"
    # It may tell the operator how to re-admit a candidate, but never claims they cancelled.
    assert "系统淘汰" in title and "操作者终止" not in title + text
    assert "操作者已在 BitPro 取消" not in text
    assert "不是操作者取消" in text and "位2" in text
    assert "共同运行 96 小时" in text and "-7.66 个百分点" in text and "-9.44%" in text
    assert "冷却后" in text and "24" in text and "不会被自动放行" in text
    adapter.paper_relay_control.assert_not_called()


def test_exam_and_timeout_cancel_cards_carry_the_reason_and_refill_at_once() -> None:
    for kind, milestone, label in (
        ("exam", "EXAM_FAILED", "终考未过关"),
        ("timeout", "TIMED_OUT", "超时"),
    ):
        rec = RacePairRecord(
            parent_strategy_id=1,
            challenger_strategy_id=2,
            state="cancelled",
            slot_no=3,
            cancellation_kind=kind,
            cancellation_reason=f"系统淘汰（{label}）：赢3/14天，及格线需赢12天",
        )
        title, text = _card_text(rec, milestone)
        assert label in title and "操作者终止" not in title + text
        assert "操作者已在 BitPro 取消" not in text and "不是操作者取消" in text
        assert "及格线需赢12天" in text and "位3" in text
        assert "立即补入" in text and "冷却" not in text


def test_lane_that_lost_its_seat_to_an_adopted_sibling_is_recorded_without_a_card(
    tmp_path: Path,
) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(
        {"actor": "system:superseded", "by_system": True, "kind": "superseded", "reason": "x"}
    )
    daemon = _daemon(tmp_path, adapter)
    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        rec = daemon.evaluate_pair(1, 2, generation=2)
        daemon.evaluate_pair(1, 2, generation=2)
    dispatch.assert_not_called()
    assert rec.feishu_notified_states == ["SUPERSEDED"] and rec.cancellation_kind == "superseded"


def test_operator_cancellation_keeps_the_operator_wording(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(
        {"actor": "admin", "by_system": False, "kind": "operator", "reason": "手动取消"}
    )
    daemon = _daemon(tmp_path, adapter)
    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)
    assert dispatch.call_args.args[1] == "CANCELLED"
    title, text = _card_text(rec, "CANCELLED")
    assert "操作者终止赛马" in title
    assert "操作者已在 BitPro 取消该场接力" in text and "再次赛马需操作者重新放行候选" in text
    assert "淘汰" not in title + text


def test_unknown_cancellation_source_gets_neutral_wording(tmp_path: Path) -> None:
    for raw in (None, "garbage", {"kind": "from-a-newer-bitpro", "by_system": True}, {"kind": 7}):
        adapter = MagicMock(spec=BitProToolAdapter)
        adapter.paper_relay_status.return_value = _lane_status(raw)
        daemon = _daemon(tmp_path / f"{abs(hash(str(raw)))}", adapter)
        with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
            dispatch.return_value = (True, "sent_interactive_card")
            rec = daemon.evaluate_pair(1, 2, generation=2)
        assert dispatch.call_args.args[1] == "CANCELLED"
        assert rec.cancellation_kind is None
        title, text = _card_text(rec, "CANCELLED")
        assert "已取消" in title and "取消" in text
        assert "操作者" not in title + text and "淘汰" not in title + text


def test_state_file_saved_before_variant_slots_still_loads(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    legacy = RacePairRecord(parent_strategy_id=1, challenger_strategy_id=2, generation=2).to_dict()
    for key in (
        "slot_no",
        "gate_alpha",
        "plan_seen",
        "cancellation_kind",
        "cancellation_actor",
        "cancellation_reason",
        "cancellation_cooldown_hours",
        "cancellation_metrics",
        "next_poll_at",
    ):
        legacy.pop(key)
    state_file.write_text(json.dumps([legacy]), encoding="utf-8")
    daemon = RaceJudgeDaemon(
        bitpro_adapter=MagicMock(spec=BitProToolAdapter), state_file=state_file
    )
    [loaded] = daemon._records.values()
    assert loaded.slot_no is None and loaded.plan_seen is False and loaded.next_poll_at == 0.0
    assert loaded.cancellation_kind is None and loaded.cancellation_metrics is None


def test_cancel_card_sent_under_a_legacy_marker_is_not_repeated_for_system_kinds(
    tmp_path: Path,
) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _daemon(tmp_path, adapter)
    daemon._records[daemon._pair_key("bitpro", 1, 2)] = RacePairRecord(
        parent_strategy_id=1,
        challenger_strategy_id=2,
        generation=2,
        feishu_notified_states=["REJECTED"],
    )
    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        daemon.evaluate_pair(1, 2, generation=2)
    dispatch.assert_not_called()


def test_card_shows_the_lane_the_level_and_the_pass_line() -> None:
    rec = RacePairRecord(
        parent_strategy_id=1,
        challenger_strategy_id=2,
        generation=2,
        slot_no=3,
        gate_alpha=0.05 / 3,
        sign_test_p=0.0065,
        positive_days=12,
        paired_non_tie_days=14,
        state="observing",
    )
    _, text = _card_text(rec, "ELIGIBLE")
    assert "Gen 2, 位3" in text
    assert "<= 0.0167 显著" in text and "至少赢 12 天" in text
    # A target without variant slots keeps the old wording: level 0.05, no lane, no pass line.
    legacy = RacePairRecord(
        parent_strategy_id=1, challenger_strategy_id=2, generation=2, sign_test_p=0.025
    )
    _, legacy_text = _card_text(legacy, "ELIGIBLE")
    challenger_line = legacy_text.split("**挑战者 ID**")[1].split("\n")[0]
    assert "<= 0.05 显著" in legacy_text and "位" not in challenger_line
    assert "及格线" not in legacy_text


def test_lane_that_vanished_from_the_target_is_ended_not_polled_forever(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(None, state="observing")
    adapter.paper_relay_plans.return_value = [
        {"parent_id": 1, "challenger_id": 2, "state": "observing", "generation": 2}
    ]
    daemon = _daemon(tmp_path, adapter)
    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        daemon.evaluate_pair(1, 2, generation=2)
        # Its seat was refilled: the target keeps no plan for this challenger any more.
        adapter.paper_relay_status.return_value = {
            "plan": None,
            "proof": {"eligible": True, "reason": "candidate evidence", "proof_sha256": "a" * 64},
        }
        adapter.paper_relay_plans.return_value = []
        rec = daemon.evaluate_pair(1, 2, generation=2)
    dispatch.assert_not_called()
    assert rec.state == "ended" and "不再保留该赛道" in rec.reason
    assert rec.eligible is False  # candidate evidence for a pair without a plan is not this race
    assert daemon.discover_active_pairs() == []


def test_pair_the_target_never_listed_is_not_declared_ended(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = {"plan": None, "proof": {"eligible": False}}
    daemon = _daemon(tmp_path, adapter)
    rec = daemon.evaluate_pair(1, 2, generation=2)
    assert rec.state == "observing" and rec.plan_seen is False


def test_quiet_lanes_are_read_slowly_and_handovers_every_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("hypertrade.paper.race_judge.time.time", lambda: clock[0])
    plans = [
        {"parent_id": 1, "challenger_id": 11, "state": "observing", "generation": 2, "slot_no": 1},
        {"parent_id": 1, "challenger_id": 12, "state": "observing", "generation": 2, "slot_no": 2},
        {"parent_id": 2, "challenger_id": 21, "state": "draining", "generation": 2, "slot_no": 1},
    ]
    states = {11: "observing", 12: "observing", 21: "draining"}
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_plans.return_value = plans
    adapter.paper_relay_status.side_effect = lambda parent_id, challenger_id=None: {
        "plan": {
            "parent_id": parent_id,
            "challenger_id": challenger_id,
            "state": states[challenger_id],
            "generation": 2,
        },
        "proof": {"eligible": False, "reason": "观测小时桶不足"},
    }
    daemon = _daemon(tmp_path, adapter)
    daemon.interval, daemon.observing_interval = 60.0, 900.0

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")):
        assert len(daemon.scan_and_judge_all()) == 3  # first sight: everything is read
        calls = adapter.paper_relay_status.call_count
        clock[0] += 61
        swept = daemon.scan_and_judge_all()
        assert [r.challenger_strategy_id for r in swept] == [21]  # only the handover in motion
        assert adapter.paper_relay_status.call_count == calls + 1
        clock[0] += 900
        assert len(daemon.scan_and_judge_all()) == 3  # quiet lanes are due again
        assert len(daemon.scan_and_judge_all(force=True)) == 3  # "run now" ignores the schedule


def test_a_cancelled_plan_in_the_listing_is_read_at_once_not_after_the_slow_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [2_000_000.0]
    monkeypatch.setattr("hypertrade.paper.race_judge.time.time", lambda: clock[0])
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_plans.return_value = [
        {"parent_id": 1, "challenger_id": 2, "state": "observing", "generation": 2}
    ]
    adapter.paper_relay_status.return_value = _lane_status(None, state="observing")
    daemon = _daemon(tmp_path, adapter)
    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        dispatch.return_value = (True, "sent_interactive_card")
        daemon.scan_and_judge_all()
        # BitPro eliminates the lane; the listing shows it cancelled well before the next slow poll.
        adapter.paper_relay_plans.return_value = [
            {"parent_id": 1, "challenger_id": 2, "state": "cancelled", "generation": 2}
        ]
        adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
        clock[0] += 120
        swept = daemon.scan_and_judge_all()
    assert [r.state for r in swept] == ["cancelled"]
    assert dispatch.call_args.args[1] == "FUTILITY"


def test_a_readmitted_challenger_can_be_announced_again(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _daemon(tmp_path, adapter)
    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        dispatch.return_value = (True, "sent_interactive_card")
        daemon.evaluate_pair(1, 2, generation=2)
        # The operator re-admits the same challenger: a new race, a new plan.
        adapter.paper_relay_status.return_value = _lane_status(None, state="observing")
        rec = daemon.evaluate_pair(1, 2, generation=2)
        assert rec.cancellation_kind is None and rec.feishu_notified_states == []
        adapter.paper_relay_status.return_value = _lane_status(
            {"actor": "admin", "by_system": False, "kind": "operator", "reason": "r"}
        )
        daemon.evaluate_pair(1, 2, generation=2)
    assert [call.args[1] for call in dispatch.call_args_list] == ["FUTILITY", "CANCELLED"]


def test_quantlab_target_without_a_cancellation_field_is_not_an_error(tmp_path: Path) -> None:
    quantlab = MagicMock()
    quantlab.paper_relay_status.return_value = _lane_status(None)
    daemon = _daemon(tmp_path, MagicMock(spec=BitProToolAdapter))
    with (
        patch("hypertrade.targets.registry.adapter_for_target", return_value=quantlab),
        patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch,
    ):
        dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2, target_id="quantlab")
    assert rec.target_id == "quantlab" and rec.state == "cancelled"
    assert rec.cancellation_kind is None and dispatch.call_args.args[1] == "CANCELLED"


# --- Forward outcome ledger: every finished lane is booked exactly once ---


def _ledger_daemon(tmp_path: Path, adapter: MagicMock) -> RaceJudgeDaemon:
    db = Database("sqlite:///:memory:")
    db.create_all()
    return RaceJudgeDaemon(
        db=db,
        bitpro_adapter=adapter,
        state_file=tmp_path / "state.json",
        history_file=tmp_path / "missing-history.json",
    )


def _outcome_rows(daemon: RaceJudgeDaemon) -> list[ArcForwardOutcome]:
    assert daemon.db is not None
    with daemon.db.session() as session:
        return list(session.scalars(select(ArcForwardOutcome)))


def _utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; the judge always stores UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


_ARCHIVED_EXAM = {
    "actor": "system:exam",
    "by_system": True,
    "kind": "exam",
    "reason": "终考未过关",
    "cancelled_at": "2026-10-20T08:00:00+00:00",
    "detail": {"kind": "exam", "positive_days": 3},
}


def test_futility_elimination_is_recorded_once_in_the_outcome_ledger(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _ledger_daemon(tmp_path, adapter)

    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ):
        rec = daemon.evaluate_pair(1, 2, generation=2)
        assert rec.outcome_recorded is True
        again = daemon.evaluate_pair(1, 2, generation=2)

    [row] = _outcome_rows(daemon)  # a second poll does not add a row
    assert row.verdict == "lost_futility"
    assert row.metrics_json["cancellation_metrics"]
    assert _utc(row.ended_at) == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    assert again.outcome_recorded is True


def test_completed_lane_is_recorded_as_a_win_when_the_plan_updates(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    status = _lane_status(None, state="completed")
    status["plan"]["updated_at"] = "2026-10-19T12:00:00+00:00"
    adapter.paper_relay_status.return_value = status
    daemon = _ledger_daemon(tmp_path, adapter)

    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ):
        daemon.evaluate_pair(1, 2, generation=2)

    [row] = _outcome_rows(daemon)
    assert row.verdict == "won" and row.verdict_source == "race_judge"
    assert _utc(row.ended_at) == datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def test_refilled_seat_with_an_archive_is_mirrored_and_recorded(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    observing = _lane_status(None, state="observing")
    observing["proof"] = {"eligible": False, "reason": "观测中", "excess_return_pct": -1.5}
    adapter.paper_relay_status.return_value = observing
    daemon = _ledger_daemon(tmp_path, adapter)

    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ) as dispatch:
        daemon.evaluate_pair(1, 2, generation=2)
        # BitPro eliminated the lane and refilled its seat before the next poll.
        adapter.paper_relay_status.return_value = {
            "plan": None,
            "proof": {"eligible": True, "excess_return_pct": 9.9, "proof_sha256": "b" * 64},
            "cancellation": _ARCHIVED_EXAM,
        }
        rec = daemon.evaluate_pair(1, 2, generation=2)

    assert rec.state == "cancelled" and rec.cancellation_kind == "exam"
    dispatch.assert_called_once()
    assert dispatch.call_args.args[1] == "EXAM_FAILED"
    [row] = _outcome_rows(daemon)
    assert row.verdict == "lost_exam"
    assert _utc(row.ended_at) == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    # The no-plan proof is a fresh candidate evaluation, not this race's evidence.
    assert row.metrics_json["excess_return_pct"] == -1.5
    assert row.metrics_json["cancellation_reason"] == "终考未过关"


def test_refilled_seat_without_an_archive_ends_neutrally_without_a_card(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(None, state="observing")
    daemon = _ledger_daemon(tmp_path, adapter)

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as dispatch:
        daemon.evaluate_pair(1, 2, generation=2)
        adapter.paper_relay_status.return_value = {
            "plan": None,
            "proof": {},
            "cancellation": None,
        }
        rec = daemon.evaluate_pair(1, 2, generation=2)

    dispatch.assert_not_called()
    assert rec.state == "ended" and rec.outcome_recorded is True
    [row] = _outcome_rows(daemon)
    assert row.verdict == "ended_unknown" and row.ended_at is None


def test_judge_without_a_database_announces_but_records_nothing(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _daemon(tmp_path, adapter)

    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ) as dispatch:
        rec = daemon.evaluate_pair(1, 2, generation=2)

    assert dispatch.call_args.args[1] == "FUTILITY"
    assert rec.outcome_recorded is False
    assert daemon.backfill_outcomes() == 0


def test_a_failing_ledger_never_blocks_the_card_or_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _ledger_daemon(tmp_path, adapter)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("ledger down")

    original = ForwardOutcomeLedger.record
    monkeypatch.setattr(ForwardOutcomeLedger, "record", _boom)
    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ) as dispatch:
        rec = daemon.evaluate_pair(1, 2, generation=2)

    assert dispatch.call_count == 1 and rec.outcome_recorded is False
    persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert persisted[0]["state"] == "cancelled"

    # The next evaluation retries once the ledger recovers.
    monkeypatch.setattr(ForwardOutcomeLedger, "record", original)
    reloaded = RaceJudgeDaemon(
        db=daemon.db,
        bitpro_adapter=adapter,
        state_file=tmp_path / "state.json",
        history_file=tmp_path / "missing-history.json",
    )
    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ):
        retried = reloaded.evaluate_pair(1, 2, generation=2)

    assert retried.outcome_recorded is True
    [row] = _outcome_rows(reloaded)
    assert row.verdict == "lost_futility"


def test_legacy_finished_lanes_are_backfilled_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "state.json"
    legacy = RacePairRecord(
        parent_strategy_id=1, challenger_strategy_id=2, generation=2, state="completed"
    ).to_dict()
    legacy.pop("outcome_recorded")  # a state file written before the ledger existed
    state_file.write_text(json.dumps([legacy]), encoding="utf-8")
    db = Database("sqlite:///:memory:")
    db.create_all()
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_plans.return_value = []
    daemon = RaceJudgeDaemon(
        db=db,
        bitpro_adapter=adapter,
        state_file=state_file,
        history_file=tmp_path / "missing-history.json",
    )

    calls: list[dict[str, Any]] = []
    original = ForwardOutcomeLedger.record

    def _counting(self: ForwardOutcomeLedger, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(ForwardOutcomeLedger, "record", _counting)
    daemon.scan_and_judge_all()
    daemon.scan_and_judge_all()  # backfill runs once per process

    assert len(calls) == 1 and calls[0]["source"] == "backfill"
    [row] = _outcome_rows(daemon)
    assert row.verdict == "won" and row.verdict_source == "backfill"


def test_a_readmitted_challenger_clears_the_recorded_outcome(tmp_path: Path) -> None:
    adapter = MagicMock(spec=BitProToolAdapter)
    adapter.paper_relay_status.return_value = _lane_status(_futility_cancellation())
    daemon = _ledger_daemon(tmp_path, adapter)

    with patch(
        "hypertrade.paper.race_judge.dispatch_race_feishu_card", return_value=(True, "ok")
    ):
        first = daemon.evaluate_pair(1, 2, generation=2)
        assert first.outcome_recorded is True
        # The operator re-admits the same challenger: a new race on the same pair.
        adapter.paper_relay_status.return_value = _lane_status(None, state="observing")
        again = daemon.evaluate_pair(1, 2, generation=2)

    assert again.state == "observing" and again.outcome_recorded is False
    [row] = _outcome_rows(daemon)
    assert row.verdict == "lost_futility"  # the ledger keeps the earlier race's verdict
