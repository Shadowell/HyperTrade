"""
ARC API Router - Single Entry Autonomous Exploration & Event Streaming
"""

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant
from hypertrade.arc.auth import (
    ARCScope,
    OperatorIdentity,
    reject_token_only_approval,
    require_scope,
    resolve_admin_session,
    resolve_service_principal,
    verify_operator_assertion,
)
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    PaperObservationPolicyV1,
    PaperPreauthorizationV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence import (
    HistoricalEvidenceGate,
    build_default_window,
    preflight_window,
)
from hypertrade.arc.evidence_view import (
    build_candidate_detail,
    build_evidence_view,
    build_mission_summary,
)
from hypertrade.arc.findings import ARCReasonCode, AttackFinding
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.live_approval import build_live_approval_package
from hypertrade.arc.live_promote import decide_live_approval, revoke_live_approval
from hypertrade.arc.mcts import ARCParallelMCTSEngine, MCTSNode
from hypertrade.arc.mutation import ARCGeneticMutator
from hypertrade.arc.observation import observe_mission
from hypertrade.arc.pipeline_view import build_pipeline_view
from hypertrade.arc.reflexion import ARCReflexionLedger
from hypertrade.arc.self_test import ARCSelfTestService, SelfTestResult
from hypertrade.arc.skills import ARCSkillDistiller, ARCSkillLibrary
from hypertrade.arc.store import MISSIONS, get_controller, list_mission_ids, save_mission

_ARC_MISSIONS = MISSIONS

router = APIRouter(prefix="/api/v1/arc", tags=["arc"])


class CreateARCMissionRequest(BaseModel):
    objective: str
    symbol: str = "BTC-USDT-SWAP"
    timeframe: str = "1H"
    max_candidates: int = 5
    paper_preauth_approved: bool = True
    parallel_workers: int = 4
    min_paper_hours: int = 24
    min_paper_trades: int = 10
    live_max_capital_u: Decimal = Field(default=Decimal("100"))
    live_mandate_hours: int = 24


class ContinueARCMissionRequest(BaseModel):
    extra_candidates: int = Field(default=3, ge=1, le=50)


class LiveDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str
    force: bool = False


class LiveRevokeRequest(BaseModel):
    reason: str


def _require_operator(
    request: Request,
    *,
    mission_id: str,
    decision: str,
    idempotency_key: str | None,
) -> tuple[OperatorIdentity, str]:
    """Resolve a human actor. A service token is never an identity here.

    Session wins. Otherwise the assertion is verified against this request's
    mission, decision, and idempotency key. ``X-Operator-Id`` is a hint that
    may agree with an already-established identity; it cannot mint one.
    """
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    session_user = resolve_admin_session(request)
    if session_user:
        return (
            OperatorIdentity(operator_id=session_user, identity_source="hypertrade_session"),
            key,
        )
    identity = verify_operator_assertion(
        request,
        mission_id=mission_id,
        decision=decision,
        idempotency_key=key,
    )
    if identity is not None:
        return identity, key
    if resolve_service_principal(request) is not None:
        raise HTTPException(status_code=403, detail="Forbidden")
    raise HTTPException(status_code=401, detail="Not authenticated")


def _actor_label(request: Request) -> str:
    session_user = resolve_admin_session(request)
    if session_user:
        return session_user
    principal = resolve_service_principal(request)
    return principal.label if principal is not None else "operator"


@router.post("/missions", dependencies=[Depends(require_scope(ARCScope.START))])
async def create_arc_mission(
    request: CreateARCMissionRequest,
    background_tasks: BackgroundTasks,
    request_context: Request,
    _x_operator_id: str | None = Header(default="operator", alias="X-Operator-Id"),
    _idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """
    Create & trigger SOTA ARC autonomous research & evolution loop.
    """
    preauth = (
        PaperPreauthorizationV1(symbols=[request.symbol])
        if request.paper_preauth_approved
        else None
    )
    goal = ARCGoalV1(
        objective=request.objective,
        symbols=[request.symbol],
        timeframes=[request.timeframe],
        budget=ARCBudgetV1(max_candidates=request.max_candidates),
        paper_authorization=preauth,
        observation=PaperObservationPolicyV1(
            min_hours=request.min_paper_hours,
            min_trades=request.min_paper_trades,
        ),
        live_max_capital_u=request.live_max_capital_u,
        live_mandate_hours=request.live_mandate_hours,
    )

    controller = ARCController(goal=goal)
    controller.projection.created_by = _actor_label(request_context)
    save_mission(controller)

    background_tasks.add_task(
        run_autonomous_arc_loop,
        controller.mission_id,
        request.parallel_workers,
    )

    return {
        "mission_id": controller.mission_id,
        "status": controller.projection.state,
        "objective": request.objective,
        "timeframe": request.timeframe,
        "parallel_workers": request.parallel_workers,
        "message": (
            f"Production-Grade SOTA ARC Autonomous Exploration Loop started "
            f"with {request.parallel_workers} parallel Rollout workers"
        ),
    }


@router.get("/evidence/preflight", dependencies=[Depends(require_scope(ARCScope.READ))])
async def arc_evidence_preflight(
    symbol: str = "BTC-USDT-SWAP", timeframe: str = "1H"
) -> dict[str, Any]:
    """What evidence a mission on this symbol could obtain, before one is started.

    A mission whose window is missing completes on advisories, which reads as success;
    this is how an operator finds that out first instead of afterwards.
    """
    return preflight_window(symbol=symbol, timeframe=timeframe)


@router.get("/missions", dependencies=[Depends(require_scope(ARCScope.READ))])
async def list_arc_missions(
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for mission_id in list_mission_ids(state=state):
        ctrl = get_controller(mission_id)
        if ctrl is None:
            continue
        summaries.append(build_mission_summary(ctrl.projection))
    summaries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"missions": summaries[:limit]}


@router.get("/missions/{mission_id}", dependencies=[Depends(require_scope(ARCScope.READ))])
async def get_arc_mission(mission_id: str) -> dict[str, Any]:
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    return ctrl.projection.model_dump(mode="json")


@router.get(
    "/missions/{mission_id}/progress",
    dependencies=[Depends(require_scope(ARCScope.READ))],
)
async def get_arc_mission_progress(mission_id: str) -> dict[str, Any]:
    """Pipeline position of a running mission, for a console that polls it."""
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    return build_pipeline_view(ctrl.projection)


@router.get(
    "/missions/{mission_id}/evidence",
    dependencies=[Depends(require_scope(ARCScope.READ))],
)
async def get_arc_mission_evidence(mission_id: str) -> dict[str, Any]:
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    return build_evidence_view(ctrl.projection)


@router.get(
    "/missions/{mission_id}/candidates/{attempt_id}",
    dependencies=[Depends(require_scope(ARCScope.READ))],
)
async def get_arc_mission_candidate(mission_id: str, attempt_id: str) -> dict[str, Any]:
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    detail = build_candidate_detail(ctrl.projection, attempt_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="ARC candidate not found")
    return detail


@router.post(
    "/missions/{mission_id}/continue",
    dependencies=[Depends(require_scope(ARCScope.START))],
)
async def continue_arc_mission(
    mission_id: str,
    request: ContinueARCMissionRequest,
    background_tasks: BackgroundTasks,
    request_context: Request,
    _x_operator_id: str | None = Header(default=None, alias="X-Operator-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    actor = _actor_label(request_context)
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    if ctrl.projection.state in {
        "paper_observing",
        "live_approval_ready",
        "approved_pending_effect",
        "live_canary",
    }:
        return {
            "mission_id": mission_id,
            "status": ctrl.projection.state,
            "message": "research already finished; continue does not reset history",
        }
    ctrl.apply_event(
        "budget_extended",
        {
            "extra_candidates": request.extra_candidates,
            "operator_id": actor,
            "idempotency_key": key,
        },
    )
    background_tasks.add_task(run_autonomous_arc_loop, mission_id)
    return {
        "mission_id": mission_id,
        "status": ctrl.projection.state,
        "max_candidates": (
            ctrl.projection.goal.budget.max_candidates if ctrl.projection.goal else None
        ),
    }


@router.get(
    "/missions/{mission_id}/live-approval",
    dependencies=[Depends(require_scope(ARCScope.READ))],
)
async def get_live_approval(mission_id: str) -> dict[str, Any]:
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    if ctrl.projection.state == "paper_observing":
        observe_mission(ctrl)
    package = ctrl.projection.live_approval or build_live_approval_package(ctrl.projection)
    return package.model_dump(mode="json")


@router.post(
    "/missions/{mission_id}/live-approval/decide",
    dependencies=[Depends(reject_token_only_approval)],
)
async def decide_live_approval_endpoint(
    mission_id: str,
    request: LiveDecisionRequest,
    request_context: Request,
    _x_operator_id: str | None = Header(default=None, alias="X-Operator-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    identity, key = _require_operator(
        request_context,
        mission_id=mission_id,
        decision=request.decision,
        idempotency_key=idempotency_key,
    )
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    if ctrl.projection.live_approval is None:
        package = build_live_approval_package(ctrl.projection)
        ctrl.apply_event("live_approval_ready", {"package": package.model_dump(mode="json")})
    try:
        return decide_live_approval(
            ctrl,
            decision=request.decision,
            reason=request.reason,
            operator_id=identity.operator_id,
            identity_source=identity.identity_source,
            idempotency_key=key,
            force=request.force,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/missions/{mission_id}/live-approval/revoke",
    dependencies=[Depends(reject_token_only_approval)],
)
async def revoke_live_approval_endpoint(
    mission_id: str,
    request: LiveRevokeRequest,
    request_context: Request,
    _x_operator_id: str | None = Header(default=None, alias="X-Operator-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    identity, key = _require_operator(
        request_context,
        mission_id=mission_id,
        decision="revoke",
        idempotency_key=idempotency_key,
    )
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    return revoke_live_approval(
        ctrl,
        operator_id=identity.operator_id,
        identity_source=identity.identity_source,
        reason=request.reason,
        idempotency_key=key,
    )


# How much of the candidate budget goes to seeding structurally different hypotheses
# rather than to repairing them. Leaves room for at least one generation of mutation.
_MAX_SEED_WIDTH = 3
_RESEARCH_DONE = {
    "paper_observing",
    "live_approval_ready",
    "approved_pending_effect",
    "live_canary",
}


def _findings_from_self_test(result: SelfTestResult) -> list[AttackFinding]:
    findings: list[AttackFinding] = []
    text = " ".join(result.reasons).lower()
    if "sharpe" in text:
        findings.append(
            AttackFinding(
                ARCReasonCode.OOS_SHARPE_TOO_LOW,
                "success_criteria",
                result.message or "BitPro self-test sharpe below success_criteria",
            )
        )
    if "drawdown" in text:
        findings.append(
            AttackFinding(
                ARCReasonCode.OOS_DRAWDOWN_EXCEEDED,
                "success_criteria",
                result.message or "BitPro self-test drawdown exceeds success_criteria",
            )
        )
    if "trades" in text:
        findings.append(
            AttackFinding(
                ARCReasonCode.OOS_SAMPLE_TOO_SMALL,
                "success_criteria",
                result.message or "BitPro self-test trades below success_criteria",
            )
        )
    if "net_return" in text:
        findings.append(
            AttackFinding(
                ARCReasonCode.FRICTION_NEGATIVE_NET_RETURN,
                "success_criteria",
                result.message or "BitPro self-test net return below success_criteria",
            )
        )
    if not findings:
        # A reason that names no success criterion is a platform failure: the call to
        # BitPro raised, was rejected, or came back without a result reference. Blaming
        # the candidate for that discards a sound strategy and writes a false lesson.
        platform = any(reason.startswith("bitpro_") for reason in result.reasons)
        findings.append(
            AttackFinding(
                ARCReasonCode.BITPRO_SELF_TEST_UNAVAILABLE
                if platform
                else ARCReasonCode.EVIDENCE_REPLAY_FAILED,
                "bitpro_self_test",
                result.message or "; ".join(result.reasons) or "BitPro self-test failed",
            )
        )
    return findings


def run_autonomous_arc_loop(mission_id: str, parallel_workers: int = 4) -> None:
    """
    Production SOTA Autonomous Execution Engine Loop with Multi-Agent Parallel Rollouts:
    Goal -> Parallel MCTS Nodes -> Blue Proposals -> Red Attacks -> Reflexion ->
    AST Mutation -> Voyager Skill Distillation -> BitPro self-test -> Auto Paper Observe

    The loop searches until a candidate survives review or the candidate budget runs
    out. Local replay is a cheap pre-filter. Paper launch requires BitPro backtest
    refs and goal.success_criteria.
    """
    ctrl = get_controller(mission_id)
    if not ctrl:
        return

    goal = ctrl.projection.goal
    if not goal:
        return
    if ctrl.projection.state in _RESEARCH_DONE:
        return

    if not any(event.event_type == "goal_compiled" for event in ctrl.projection.events):
        ctrl.apply_event("goal_compiled", {"goal": goal.model_dump()})
        goal = ctrl.projection.goal
        if not goal:
            return
    budget = goal.budget

    symbol = goal.symbols[0] if goal.symbols else "BTC-USDT-SWAP"
    timeframe = goal.timeframes[0] if goal.timeframes else "1H"
    window = build_default_window()
    preflight = preflight_window(symbol=symbol, timeframe=timeframe, window=window)
    # A missing window used to be an advisory on each candidate. The loop then treated
    # projected Sharpe as a pass and minted a local paper id, so the mission completed
    # looking successful. Missing data is an operator problem: stop before spending
    # the candidate budget.
    if not preflight.get("evidence_possible"):
        ctrl.apply_event(
            "operator_needed",
            {"reason": "evidence_window_unavailable", "preflight": preflight},
        )
        return

    blue_team = BlueTeamQuant()
    engine = ARCAdversarialEngine(evidence_gate=HistoricalEvidenceGate(window))
    mutator = ARCGeneticMutator()
    reflexion_ledger = ARCReflexionLedger()
    reflexion_ledger._records.extend(ctrl.projection.reflexion_history)
    mcts_engine = ARCParallelMCTSEngine(parallel_workers=parallel_workers)
    skill_library = ARCSkillLibrary()
    skill_distiller = ARCSkillDistiller()
    incubation_resolver = ARCPaperIncubationResolver()

    reviews: dict[str, tuple[dict[str, Any], list[Any]]] = {}

    def eval_candidate(cand: ARCCandidateAttemptV1) -> tuple[bool, float]:
        survived, metrics, findings = engine.run_adversarial_session(cand)
        reviews[cand.attempt_id] = (metrics, list(findings))
        return survived, float(metrics.get("ranking_sharpe", 0.0))

    def repair(cand: ARCCandidateAttemptV1) -> list[ARCCandidateAttemptV1]:
        """Diagnose one casualty and propose its repaired successor."""
        if budget.is_exhausted():
            return []
        metrics, findings = reviews.get(cand.attempt_id, ({}, []))
        reflexion = reflexion_ledger.diagnose_and_record_failure(
            attempt=cand,
            failure_class="red_team_attack_failed",
            observed_metrics=metrics,
            findings=findings,
        )
        ctrl.apply_event("reflexion_recorded", {"reflexion": reflexion.model_dump()})

        mutated = mutator.mutate_attempt(cand, reflexion_ledger.get_history())
        if mutated.strategy_code == cand.strategy_code:
            return []
        ctrl.apply_event("candidate_proposed", {"attempt": mutated.model_dump()})
        ctrl.apply_event(
            "candidate_mutated",
            {"attempt_id": mutated.attempt_id, "strategy_code": mutated.strategy_code},
        )
        return [mutated]

    validated = next(
        (
            item
            for item in ctrl.projection.attempts
            if item.state == "validated" and item.bitpro_backtest_id
        ),
        None,
    )

    frontier: list[MCTSNode] = []
    if validated is None:
        if not ctrl.projection.attempts:
            seed_width = max(1, min(_MAX_SEED_WIDTH, budget.max_candidates - 1))
            seeds = blue_team.propose_diverse_frontier(
                goal.objective, symbol, seed_width, timeframe=timeframe
            )
            root_id: str | None = None
            for seed in seeds:
                ctrl.apply_event("candidate_proposed", {"attempt": seed.model_dump()})
                if root_id is None:
                    root = mcts_engine.add_root(seed)
                    root_id = root.node_id
                    frontier.append(root)
                else:
                    frontier.append(mcts_engine.add_child(root_id, seed))
        else:
            rejected = [item for item in ctrl.projection.attempts if item.state == "rejected"]
            source = rejected[-1] if rejected else ctrl.projection.attempts[-1]
            root = mcts_engine.add_root(source)
            for cand in rejected[-3:] or [source]:
                mutated = mutator.mutate_attempt(cand, reflexion_ledger.get_history())
                if mutated.strategy_code == cand.strategy_code or budget.is_exhausted():
                    continue
                ctrl.apply_event("candidate_proposed", {"attempt": mutated.model_dump()})
                ctrl.apply_event(
                    "candidate_mutated",
                    {
                        "attempt_id": mutated.attempt_id,
                        "strategy_code": mutated.strategy_code,
                    },
                )
                frontier.append(mcts_engine.add_child(root.node_id, mutated))
            if not frontier:
                extra = max(1, min(_MAX_SEED_WIDTH, budget.max_candidates - budget.candidates_used))
                # Spend a re-seed on hypotheses the mission has not tried. Without this
                # the walk restarted at the head of the catalogue and re-proposed the
                # families it had just rejected.
                tried = {
                    str(item.strategy_spec.get("family") or "")
                    for item in ctrl.projection.attempts
                }
                for seed in blue_team.propose_diverse_frontier(
                    goal.objective,
                    symbol,
                    extra,
                    timeframe=timeframe,
                    exclude_families=tried,
                ):
                    if budget.is_exhausted():
                        break
                    ctrl.apply_event("candidate_proposed", {"attempt": seed.model_dump()})
                    frontier.append(mcts_engine.add_child(root.node_id, seed))

        while frontier and validated is None:
            rollouts = mcts_engine.simulate(frontier, eval_candidate)
            for node, survived, _score in rollouts:
                metrics, _ = reviews.get(node.attempt.attempt_id, ({}, []))
                ctrl.apply_event(
                    "red_team_tested",
                    {
                        "attempt_id": node.attempt.attempt_id,
                        "passed": survived,
                        "metrics": metrics,
                    },
                )

            survivors = sorted(
                ((score, node.attempt) for node, survived, score in rollouts if survived),
                key=lambda pair: pair[0],
                reverse=True,
            )
            oos_survivors = [
                pair
                for pair in survivors
                if reviews.get(pair[1].attempt_id, ({}, []))[0].get("ranking_basis")
                == "out_of_sample"
            ]
            if survivors and not oos_survivors:
                metrics, _ = reviews.get(survivors[0][1].attempt_id, ({}, []))
                ctrl.apply_event(
                    "operator_needed",
                    {
                        "reason": "no_out_of_sample_evidence",
                        "attempt_id": survivors[0][1].attempt_id,
                        "ranking_basis": metrics.get("ranking_basis"),
                    },
                )
                return
            for _score, candidate in oos_survivors:
                survivor_metrics, _ = reviews.get(candidate.attempt_id, ({}, []))
                if survivor_metrics.get("ranking_basis") != "out_of_sample":
                    continue
                self_test = ARCSelfTestService().run(candidate, goal)
                ctrl.apply_event(
                    "bitpro_self_tested",
                    {
                        "attempt_id": candidate.attempt_id,
                        "passed": self_test.passed,
                        "validation_id": self_test.validation_id,
                        "bitpro_strategy_id": self_test.bitpro_strategy_id,
                        "backtest_id": self_test.backtest_id,
                        "metrics": self_test.metrics,
                        "reasons": self_test.reasons,
                        "success_criteria": goal.success_criteria.model_dump(mode="json"),
                    },
                )
                if self_test.passed:
                    validated = next(
                        item
                        for item in ctrl.projection.attempts
                        if item.attempt_id == candidate.attempt_id
                    )
                    break
                reflexion = reflexion_ledger.diagnose_and_record_failure(
                    attempt=candidate,
                    failure_class="bitpro_self_test_failed",
                    observed_metrics=self_test.metrics,
                    findings=_findings_from_self_test(self_test),
                )
                ctrl.apply_event("reflexion_recorded", {"reflexion": reflexion.model_dump()})

            if validated is not None:
                break

            next_generation: list[MCTSNode] = []
            for node, _, _ in rollouts:
                next_generation.extend(mcts_engine.expand(node.node_id, repair))
            frontier = next_generation

    if validated is None:
        if ctrl.projection.state != "needs_operator":
            ctrl.apply_event("operator_needed", {"reason": "no_validated_candidate"})
        return

    if not validated.bitpro_backtest_id or not validated.validation_id:
        ctrl.apply_event(
            "operator_needed",
            {
                "reason": "bitpro_self_test_incomplete",
                "attempt_id": validated.attempt_id,
            },
        )
        return

    if validated.state != "validated":
        ctrl.apply_event(
            "candidate_validated",
            {
                "attempt_id": validated.attempt_id,
                "validation_id": validated.validation_id,
                "bitpro_strategy_id": validated.bitpro_strategy_id,
                "backtest_id": validated.bitpro_backtest_id,
            },
        )
        validated = next(
            item
            for item in ctrl.projection.attempts
            if item.attempt_id == validated.attempt_id
        )

    for skill in skill_distiller.distill_skills_from_candidate(validated):
        skill_library.register_skill(skill)

    if not goal.paper_authorization:
        ctrl.apply_event("operator_needed", {"reason": "paper_preauthorization_missing"})
        return

    ok, paper_inst_id, strat_name, msg = incubation_resolver.resolve_and_provision_paper_trading(
        validated, goal.paper_authorization
    )
    if ok and paper_inst_id:
        ctrl.apply_event(
            "paper_started",
            {
                "attempt_id": validated.attempt_id,
                "paper_instance_id": paper_inst_id,
                "strategy_name": strat_name,
                "message": msg,
            },
        )
        return
    ctrl.apply_event(
        "operator_needed",
        {"reason": "paper_provision_failed", "message": msg},
    )
