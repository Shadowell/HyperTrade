"""Tests for BitPro Race Judge Daemon and Automated Relay Scheduler."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from hypertrade.bitpro.mcp import BitProToolAdapter
from hypertrade.paper.race_judge import (
    RaceJudgeDaemon,
    RacePairRecord,
    build_race_feishu_card,
    dispatch_race_feishu_card,
)


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
