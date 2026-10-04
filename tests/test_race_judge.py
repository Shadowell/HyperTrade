"""Tests for BitPro Race Judge Daemon and Automated Relay Scheduler."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from hypertrade.bitpro.mcp import BitProMcpError, BitProToolAdapter
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
        assert "strategy_id=1" in btn["url"]
        assert "challenger_id=2" in btn["url"]


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


def test_evaluate_pair_eligible_and_auto_adopted(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    proof_sha = "e" * 64
    mock_adapter.paper_relay_status.return_value = {
        "plan": {
            "parent_id": 1,
            "challenger_id": 2,
            "state": "observing",
            "auto_enabled": True,
            "generation": 2,
        },
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
    mock_adapter.paper_relay_control.return_value = {"status": "ok"}

    state_file = tmp_path / "state.json"
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=state_file,
        auto_adopt=True,
    )

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        mock_dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)

        assert rec.eligible is True
        assert rec.state == "draining"
        assert rec.action_taken == "adopted"
        mock_adapter.paper_relay_control.assert_called_with(
            parent_id=1,
            action="adopt",
            challenger_id=2,
            proof_sha256=proof_sha,
        )
        mock_dispatch.assert_called_once()
        assert "ADOPTED" in rec.feishu_notified_states


def test_evaluate_pair_requires_admin_authorization(tmp_path: Path) -> None:
    mock_adapter = MagicMock(spec=BitProToolAdapter)
    proof_sha = "f" * 64
    mock_adapter.paper_relay_status.return_value = {
        "plan": {
            "parent_id": 1,
            "challenger_id": 2,
            "state": "observing",
            "auto_enabled": True,
            "generation": 2,
        },
        "proof": {
            "eligible": True,
            "reason": "前向门禁通过",
            "proof_sha256": proof_sha,
            "observed_points": 337,
            "net_return_pct": [2.0, 7.0],
            "observed_drawdown_pct": [5.0, 3.0],
            "excess_return_pct": 5.0,
            "closed_fills": [30, 32],
            "sign_test_p": 0.02,
        },
    }
    # Simulate BitPro returning 403 because token is not admin
    mock_adapter.paper_relay_control.side_effect = BitProMcpError(
        "接力及自动托管需要管理员明确授权", status_code=403
    )

    state_file = tmp_path / "state.json"
    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        state_file=state_file,
        auto_adopt=True,
    )

    with patch("hypertrade.paper.race_judge.dispatch_race_feishu_card") as mock_dispatch:
        mock_dispatch.return_value = (True, "sent_interactive_card")
        rec = daemon.evaluate_pair(1, 2, generation=2)

        assert rec.eligible is True
        assert rec.requires_admin_authorization is True
        assert rec.action_taken == "needs_admin_approval"
        mock_dispatch.assert_called_once()
        assert "REQUIRES_ADMIN" in rec.feishu_notified_states


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
