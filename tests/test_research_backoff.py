"""A parent whose same-window baseline cannot be sealed is not tried again at once and is not
charged to the day; when BitPro already says it cannot be sealed, no mission is spent on it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.contracts import RULE_TWEAK_PROVIDER, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.research_budget import admit, budget_status
from hypertrade.arc.store import configure_store, get_controller, list_mission_ids, reset_store
from hypertrade.db import ArcMission, Database
from test_evolution_launch import LaunchPaper, launch_service

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
DETERMINISTIC = "incomplete_official_bar_grid"
CRASH = "回测工作进程异常退出（code=-15），详见服务日志"


@pytest.fixture
def service():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    svc = EvolutionService(db)
    svc.configure(
        EvolutionConfig(
            enabled=True,
            launch_enabled=True,
            max_research_per_day=50,
            max_active_research=50,
            exploration_cooldown_hours=2,
        ),
        revision=0,
        actor="test",
    )
    yield svc
    reset_store()


def source_context(
    *, instance="paper-source", policy=None, version="v1", config="c1", strategy_id=44
):
    return {
        "source_instance_id": instance,
        "source_strategy_id": strategy_id,
        "trigger_source": "launch",
        "source_snapshot": {
            "instance_id": instance,
            "strategy_version": version,
            "config_version": config,
            "status": "running",
        },
        **({"variant_policy": {"baseline_backtest": {"policy": policy}}} if policy else {}),
    }


def admitted(service, now, **context):
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="baseline probe",
            provider_name=RULE_TWEAK_PROVIDER,
            evolution_context=source_context(**context),
        )
    )
    result = admit(ctrl, now=now, db=service.db)
    return ctrl, result


def fail(service, ctrl, when, message=DETERMINISTIC):
    live = get_controller(ctrl.mission_id)
    live.apply_event(
        "avo_execution_failed",
        {
            "attempt_id": "att",
            "passed": False,
            "reasons": ["baseline_data_snapshot_unavailable"],
            "message": message,
            "purpose": "development",
        },
    )
    with service.db.session() as session:
        session.get(ArcMission, ctrl.mission_id).updated_at = when


def failed_mission(service, now, message=DETERMINISTIC, **context):
    ctrl, result = admitted(service, now, **context)
    assert result["accepted"], result
    fail(service, ctrl, now + timedelta(minutes=2), message)
    return ctrl


def status_at(service, when):
    config = EvolutionConfig.model_validate(service.status()["config"])
    return budget_status(service.db, config, when)


def only_source(budget):
    (source,) = budget["sources"].values()
    return source


def test_a_mission_that_died_sealing_the_baseline_is_not_charged_to_the_day(service):
    failed_mission(service, NOW, instance="paper-a")
    failed_mission(service, NOW + HOUR, instance="paper-b")
    crashed = failed_mission(service, NOW + 2 * HOUR, message=CRASH, instance="paper-c")

    budget = status_at(service, NOW + 3 * HOUR)

    assert crashed.mission_id in list_mission_ids()
    # Two baseline deaths are given back; a crashed worker is an ordinary failure and stays charged.
    assert (budget["period_used"], budget["period_refunded"], budget["total_used"]) == (1, 2, 3)


def test_the_day_limit_still_holds_for_missions_that_ran(service):
    service.configure(
        EvolutionConfig.model_validate(
            {**service.status()["config"], "max_research_per_day": 1}
        ),
        revision=service.status()["revision"],
        actor="test",
    )
    failed_mission(service, NOW, instance="paper-a")
    _, second = admitted(service, NOW + HOUR, instance="paper-b")
    assert second["accepted"], second  # the dead one was given back
    _, third = admitted(service, NOW + 2 * HOUR, instance="paper-c")
    assert third["reason"] == "period_budget_exhausted"


def test_each_consecutive_baseline_failure_doubles_the_wait_up_to_a_week(service):
    expected = [24, 48, 96, 168, 168]
    now = NOW
    for streak, hours in enumerate(expected, start=1):
        failed_mission(service, now)
        source = only_source(status_at(service, now + 10 * HOUR))
        assert source["failure_streak"] == streak
        assert source["failure_reason"] == DETERMINISTIC
        assert source["cooldown_hours"] == hours
        assert source["reason"] == "source_cooldown"
        # Not eligible an hour before the wait ends, eligible right after it.
        last_failed = now + timedelta(minutes=2)
        _, early = admitted(service, last_failed + timedelta(hours=hours) - HOUR)
        assert early["reason"] == "source_cooldown"
        now = last_failed + timedelta(hours=hours) + HOUR


def test_a_different_outcome_ends_the_streak(service):
    failed_mission(service, NOW)
    failed_mission(service, NOW + 25 * HOUR)
    assert only_source(status_at(service, NOW + 26 * HOUR))["failure_streak"] == 2

    failed_mission(service, NOW + 75 * HOUR, message=CRASH)

    source = only_source(status_at(service, NOW + 76 * HOUR))
    assert (source["failure_streak"], source["failure_reason"]) == (0, None)
    assert source["cooldown_hours"] == 2


def test_only_the_failures_since_the_last_other_outcome_count(service):
    failed_mission(service, NOW)
    failed_mission(service, NOW + 25 * HOUR, message=CRASH)
    failed_mission(service, NOW + 29 * HOUR)

    source = only_source(status_at(service, NOW + 30 * HOUR))

    assert source["failure_streak"] == 1
    assert source["cooldown_hours"] == 24


@pytest.mark.parametrize(
    "changed",
    [{"policy": "strategy_bars_v2"}, {"version": "v2"}, {"config": "c2"}],
    ids=["new_bitpro_policy", "parent_edited", "parent_config_changed"],
)
def test_a_changed_question_is_asked_again_at_once(service, changed):
    failed_mission(service, NOW)

    # Past the ordinary 2h wait, inside the 24h wait for this same question.
    _, same = admitted(service, NOW + 3 * HOUR)
    _, asked_again = admitted(service, NOW + 3 * HOUR, **changed)

    assert same["reason"] == "source_cooldown"
    assert asked_again["accepted"], asked_again


def test_failures_under_an_older_policy_do_not_extend_the_wait_for_the_new_one(service):
    failed_mission(service, NOW)
    failed_mission(service, NOW + 25 * HOUR)
    new_policy = failed_mission(service, NOW + 75 * HOUR, policy="strategy_bars_v2")

    source = only_source(status_at(service, NOW + 76 * HOUR))

    assert new_policy.mission_id in list_mission_ids()
    assert source["failure_streak"] == 1
    assert source["cooldown_hours"] == 24


def test_scan_leaves_a_parent_in_backoff_alone_then_retries_it(service, monkeypatch):
    now = launch_service(service, monkeypatch, launch_enabled=True)
    # Same parent version the scan will read (v1/c1) and no BitPro policy, as in this fake.
    failed_mission(service, now - 3 * HOUR)

    waiting = service.tick(now)
    retried = service.tick(now + 24 * HOUR)

    assert waiting["status"] == "deferred", waiting
    assert waiting["payload"]["budget"]["reason"] == "source_cooldown"
    assert retried["status"] == "research_created", retried


def test_scan_asks_again_at_once_when_the_parent_was_edited_since_it_failed(service, monkeypatch):
    now = launch_service(service, monkeypatch, launch_enabled=True)
    # The failed attempt saw an older version of the parent than the scan reads now (v1).
    failed_mission(service, now - 3 * HOUR, version="v0")

    result = service.tick(now)

    assert result["status"] == "research_created", result


class TwoParents(LaunchPaper):
    """Two running parents with the same version, told apart by id and instance."""

    def paper_strategy_performance(self, **kwargs):
        return {
            "strategies": [
                {"strategy_id": 44, "strategy_name": "a", "mode": "paper", "timeframe": "1H"},
                {"strategy_id": 45, "strategy_name": "b", "mode": "paper", "timeframe": "1H"},
            ]
        }

    @staticmethod
    def _id(kwargs):
        return int(kwargs.get("strategy_id") or 44)

    def paper_snapshot(self, **kwargs):
        body = super().paper_snapshot(**kwargs)
        body["strategy_id"] = self._id(kwargs)
        body["instance_id"] = "paper-source" if self._id(kwargs) == 44 else "paper-other"
        return body

    def strategy_trades(self, **kwargs):
        rows = super().strategy_trades(**kwargs)
        return [{**row, "strategy_id": self._id(kwargs)} for row in rows]

    def strategy_research_variant_policy(self, **kwargs):
        policy = super().strategy_research_variant_policy(**kwargs)
        return {**policy, "parent_strategy_id": self._id(kwargs)}


def test_scan_prefers_the_parent_that_failed_under_an_older_question(service, monkeypatch):
    now = launch_service(service, monkeypatch, client=TwoParents(), launch_enabled=True)
    # 44 failed 10h ago, but on a version it no longer has (so its wait does not apply);
    # 45 was tried 5h ago. Both are free; the one tried least recently goes first.
    failed_mission(service, now - 10 * HOUR, version="v0", strategy_id=44)
    failed_mission(
        service, now - 5 * HOUR, message=CRASH, instance="paper-other", strategy_id=45
    )

    result = service.tick(now)

    assert result["status"] == "research_created", result
    assert result["payload"]["source_strategy_id"] == 44


class SealablePaper(LaunchPaper):
    """BitPro answers `baseline_backtest` in the variant policy."""

    verdict: dict | None = None

    def strategy_research_variant_policy(self, **kwargs):
        policy = super().strategy_research_variant_policy(**kwargs)
        return {**policy, "baseline_backtest": self.verdict} if self.verdict else policy


def scan_with(service, monkeypatch, verdict, *, symbols=None):
    paper = SealablePaper()
    paper.verdict = verdict
    if symbols is not None:
        snapshot = paper.paper_snapshot

        def many(**kwargs):
            body = snapshot(**kwargs)
            body["strategy"] = {"symbols": symbols}
            return body

        paper.paper_snapshot = many
    now = launch_service(service, monkeypatch, client=paper, launch_enabled=True)
    return service.tick(now)


def test_scan_skips_a_parent_bitpro_cannot_seal_and_says_why(service, monkeypatch):
    result = scan_with(
        service,
        monkeypatch,
        {
            "policy": "strategy_bars_v2",
            "supported": False,
            "reason_code": "strategy_warmup_exceeds_policy",
            "warmup_required_bars": 12000,
            "warmup_max_bars": 10000,
        },
    )

    assert result["status"] == "no_action", result
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["skip_reason"] == "baseline_infeasible"
    assert diagnostic["baseline_infeasible"]["reason_code"] == "strategy_warmup_exceeds_policy"
    (blocker,) = [
        b for b in diagnostic["continuation"]["blockers"] if b["code"] == "baseline_infeasible"
    ]
    assert "12000" in blocker["reason"] and "10000" in blocker["reason"]
    assert blocker["resolution"] == "time"
    assert list_mission_ids() == []


def test_scan_skips_a_parent_listed_after_the_window_needs_it(service, monkeypatch):
    listed = int((NOW - timedelta(days=30)).timestamp() * 1000)
    result = scan_with(
        service,
        monkeypatch,
        {
            "policy": "strategy_bars_v2",
            "supported": True,
            "warmup_policy_bars": 500,
            "history_start_ms": listed,
        },
    )

    assert result["status"] == "no_action", result
    infeasible = result["payload"]["diagnostics"][0]["baseline_infeasible"]
    assert infeasible["reason_code"] == "history_shorter_than_window"
    assert infeasible["history_start_ms"] == listed
    assert list_mission_ids() == []


@pytest.mark.parametrize(
    "verdict",
    [
        None,
        {"policy": "strategy_bars_v2", "supported": True, "warmup_policy_bars": 500},
        {
            "policy": "strategy_bars_v2",
            "supported": True,
            "warmup_policy_bars": 500,
            "history_start_ms": int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000),
        },
    ],
    ids=["no_verdict", "no_history_info", "long_history"],
)
def test_scan_proceeds_when_nothing_says_the_baseline_cannot_be_sealed(
    service, monkeypatch, verdict
):
    result = scan_with(service, monkeypatch, verdict)

    assert result["status"] == "research_created", result
    assert "baseline_infeasible" not in result["payload"]["diagnostics"][0]


def test_the_research_window_is_fitted_to_the_parents_own_warmup(service, monkeypatch):
    # 285 symbols of 1H leave 3508 bars each: room for the default 119-day window with the 500-bar
    # floor, but not once the parent's own 1000-bar warmup is taken out of it.
    symbols = [f"C{index}/USDT:USDT" for index in range(285)]
    verdict = {"policy": "strategy_bars_v2", "supported": True, "warmup_policy_bars": 1000}

    result = scan_with(service, monkeypatch, verdict, symbols=symbols)

    assert result["status"] == "research_created", result
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.research_windows is not None
    assert (goal.research_windows.development_days, goal.research_windows.validation_days) == (
        104,
        60,
    )
    bitpro = goal.evolution_context["variant_policy"]["baseline_backtest"]
    assert bitpro["warmup_policy_bars"] == 1000


def test_without_a_verdict_the_500_bar_floor_is_assumed_for_the_window(service, monkeypatch):
    symbols = [f"C{index}/USDT:USDT" for index in range(285)]

    result = scan_with(service, monkeypatch, None, symbols=symbols)

    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.research_windows is not None
    assert goal.research_windows.development_days == 119


def test_a_window_that_only_fails_once_the_parents_warmup_is_counted_is_skipped(
    service, monkeypatch
):
    # 1000 symbols of 1H leave 1000 bars each: a 20-day window fits after the 500-bar floor, but
    # nothing fits after the 1000 bars this parent's own warmup takes.
    symbols = [f"C{index}/USDT:USDT" for index in range(1000)]
    verdict = {"policy": "strategy_bars_v2", "supported": True, "warmup_policy_bars": 1000}

    result = scan_with(service, monkeypatch, verdict, symbols=symbols)

    assert result["status"] == "no_action", result
    infeasible = result["payload"]["diagnostics"][0]["baseline_infeasible"]
    assert infeasible["reason_code"] == "research_window_exceeds_backtest_bounds"
    assert list_mission_ids() == []


def test_a_basket_whose_window_cannot_fit_is_skipped_instead_of_failing_the_cycle(
    service, monkeypatch
):
    symbols = [f"C{index}/USDT:USDT" for index in range(1500)]

    result = scan_with(service, monkeypatch, None, symbols=symbols)

    assert result["status"] == "no_action", result
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["skip_reason"] == "baseline_infeasible"
    infeasible = diagnostic["baseline_infeasible"]
    assert infeasible["reason_code"] == "research_window_exceeds_backtest_bounds"
    assert list_mission_ids() == []


def young_verdict(listed_days_ago: int) -> dict:
    listed = int((NOW - timedelta(days=listed_days_ago)).timestamp() * 1000)
    return {
        "policy": "strategy_bars_v3",
        "supported": True,
        "warmup_policy_bars": 500,
        "warmup_min_bars": 30,
        "history_start_ms": listed,
    }


def test_a_recently_listed_parent_is_researched_on_the_history_it_has(service, monkeypatch):
    # Listed 100 days ago: far too young for 500 bars before a 180-day window, but BitPro seals
    # the history it has. The windows start the first day 30 hourly bars exist (2026-06-07).
    result = scan_with(service, monkeypatch, young_verdict(100))

    assert result["status"] == "research_created", result
    assert "baseline_infeasible" not in result["payload"]["diagnostics"][0]
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    windows = goal.research_windows
    assert windows is not None
    assert (windows.development_days, windows.validation_days) == (63, 32)
    assert windows.window("development")[0].isoformat() == "2026-06-07"
    assert windows.window("final")[1].isoformat() == "2026-09-11"
    # The mission carries BitPro's answer, so the windows can be re-derived from the context.
    assert goal.evolution_context["variant_policy"]["baseline_backtest"]["warmup_min_bars"] == 30


def test_a_parent_too_young_for_two_windows_is_skipped_with_the_day_it_becomes_researchable(
    service, monkeypatch
):
    result = scan_with(service, monkeypatch, young_verdict(20))

    assert result["status"] == "no_action", result
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["skip_reason"] == "baseline_infeasible"
    infeasible = diagnostic["baseline_infeasible"]
    assert infeasible["reason_code"] == "history_shorter_than_window"
    assert "2026-09-25" in infeasible["message"]
    assert list_mission_ids() == []


def test_the_scan_and_the_mission_agree_on_the_windows_of_a_young_parent(service, monkeypatch):
    # 285 symbols of 1H leave room for a 104-day development window (the bar bound); the history
    # of a parent listed 100 days ago leaves 95 usable days, split like the 104:60 it replaces.
    symbols = [f"C{index}/USDT:USDT" for index in range(285)]
    verdict = {**young_verdict(100), "warmup_policy_bars": 1000}

    result = scan_with(service, monkeypatch, verdict, symbols=symbols)

    assert result["status"] == "research_created", result
    windows = get_controller(result["payload"]["mission_id"]).projection.goal.research_windows
    assert windows is not None
    assert (windows.development_days, windows.validation_days) == (60, 35)
    assert windows.window("development")[0].isoformat() == "2026-06-07"


def test_an_older_bitpro_that_seals_the_full_warmup_gets_windows_that_start_after_it(
    service, monkeypatch
):
    # No warmup_min_bars: BitPro seals all 500 hourly bars, so the windows start once the symbol
    # (listed 100 days ago) has them: 2026-06-04 12:00 + 1 day + 500 hours -> 2026-06-27.
    verdict = young_verdict(100)
    del verdict["warmup_min_bars"]

    result = scan_with(service, monkeypatch, verdict)

    assert result["status"] == "research_created", result
    windows = get_controller(result["payload"]["mission_id"]).projection.goal.research_windows
    assert windows is not None
    assert windows.window("development")[0].isoformat() == "2026-06-27"
    assert (windows.development_days, windows.validation_days) == (50, 25)
