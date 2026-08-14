"""
ARC API Router - Single Entry Autonomous Exploration & Event Streaming
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    PaperPreauthorizationV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence import (
    HistoricalEvidenceGate,
    build_default_window,
    preflight_window,
)
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.mcts import ARCParallelMCTSEngine, MCTSNode
from hypertrade.arc.mutation import ARCGeneticMutator
from hypertrade.arc.reflexion import ARCReflexionLedger
from hypertrade.arc.skills import ARCSkillDistiller, ARCSkillLibrary

router = APIRouter(prefix="/api/v1/arc", tags=["arc"])

_ARC_MISSIONS: dict[str, ARCController] = {}


class CreateARCMissionRequest(BaseModel):
    objective: str
    symbol: str = "BTC-USDT-SWAP"
    max_candidates: int = 5
    paper_preauth_approved: bool = True
    parallel_workers: int = 4


@router.post("/missions")
async def create_arc_mission(
    request: CreateARCMissionRequest, background_tasks: BackgroundTasks
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
        budget=ARCBudgetV1(max_candidates=request.max_candidates),
        paper_authorization=preauth,
    )

    controller = ARCController(goal=goal)
    _ARC_MISSIONS[controller.mission_id] = controller

    background_tasks.add_task(
        run_autonomous_arc_loop,
        controller.mission_id,
        request.parallel_workers,
    )

    return {
        "mission_id": controller.mission_id,
        "status": controller.projection.state,
        "objective": request.objective,
        "parallel_workers": request.parallel_workers,
        "message": (
            f"Production-Grade SOTA ARC Autonomous Exploration Loop started "
            f"with {request.parallel_workers} parallel Rollout workers"
        ),
    }


@router.get("/evidence/preflight")
async def arc_evidence_preflight(
    symbol: str = "BTC-USDT-SWAP", timeframe: str = "1H"
) -> dict[str, Any]:
    """What evidence a mission on this symbol could obtain, before one is started.

    A mission whose window is missing completes on advisories, which reads as success;
    this is how an operator finds that out first instead of afterwards.
    """
    return preflight_window(symbol=symbol, timeframe=timeframe)


@router.get("/missions/{mission_id}")
async def get_arc_mission(mission_id: str) -> dict[str, Any]:
    if mission_id not in _ARC_MISSIONS:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    ctrl = _ARC_MISSIONS[mission_id]
    return ctrl.projection.model_dump()


# How much of the candidate budget goes to seeding structurally different hypotheses
# rather than to repairing them. Leaves room for at least one generation of mutation.
_MAX_SEED_WIDTH = 3


def run_autonomous_arc_loop(mission_id: str, parallel_workers: int = 4) -> None:
    """
    Production SOTA Autonomous Execution Engine Loop with Multi-Agent Parallel Rollouts:
    Goal -> Parallel MCTS Nodes -> Blue Proposals -> Red Attacks -> Reflexion ->
    AST Mutation -> Voyager Skill Distillation -> Auto Paper Launch

    The loop searches until a candidate survives review or the candidate budget runs
    out. It used to be a hand-unrolled two-step script: one proposal, one mutation, and
    then it gave up regardless of how much budget the operator had granted.
    """
    ctrl = _ARC_MISSIONS.get(mission_id)
    if not ctrl:
        return

    goal = ctrl.projection.goal
    if not goal:
        return

    ctrl.apply_event("goal_compiled", {"goal": goal.model_dump()})
    # The projection rebuilds the goal from the event payload, so the pre-event object
    # is a detached copy whose budget counters never advance. Reading budget off that
    # copy let the loop propose past its allowance without ever seeing it exhausted.
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
    mcts_engine = ARCParallelMCTSEngine(parallel_workers=parallel_workers)
    skill_library = ARCSkillLibrary()
    skill_distiller = ARCSkillDistiller()
    incubation_resolver = ARCPaperIncubationResolver()

    # 1. Seed the MCTS tree with structurally different hypotheses, not one template.
    #    One slot is always held back so a rejected frontier still gets one repair pass.
    seed_width = max(1, min(_MAX_SEED_WIDTH, budget.max_candidates - 1))
    seeds = blue_team.propose_diverse_frontier(goal.objective, symbol, seed_width)
    root_id: str | None = None
    frontier: list[MCTSNode] = []
    for seed in seeds:
        ctrl.apply_event("candidate_proposed", {"attempt": seed.model_dump()})
        if root_id is None:
            root = mcts_engine.add_root(seed)
            root_id = root.node_id
            frontier.append(root)
        else:
            frontier.append(mcts_engine.add_child(root_id, seed))

    # The rollout contract only carries (passed, score), so the review detail each
    # candidate needs for reflexion is captured here and read back by attempt id.
    reviews: dict[str, tuple[dict[str, Any], list[Any]]] = {}

    def eval_candidate(cand: ARCCandidateAttemptV1) -> tuple[bool, float]:
        survived, metrics, findings = engine.run_adversarial_session(cand)
        reviews[cand.attempt_id] = (metrics, list(findings))
        # `ranking_sharpe` is the held-out result where the window allowed one, and only
        # falls back to the declared projection when it did not. MCTS backpropagates this
        # value, so it decides which subtree the remaining budget is spent on.
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
            # Nothing the reviewer objected to is expressible as a parameter change;
            # re-testing an identical body would only burn budget.
            return []
        ctrl.apply_event("candidate_proposed", {"attempt": mutated.model_dump()})
        ctrl.apply_event(
            "candidate_mutated",
            {"attempt_id": mutated.attempt_id, "strategy_code": mutated.strategy_code},
        )
        return [mutated]

    validated: ARCCandidateAttemptV1 | None = None
    while frontier and validated is None:
        # 2. Simulation: the engine rolls the generation out and backpropagates values.
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
        if survivors:
            validated = survivors[0][1]
            break

        # 3. Expansion: reflexion-guided repair of every casualty in this generation.
        next_generation: list[MCTSNode] = []
        for node, _, _ in rollouts:
            next_generation.extend(mcts_engine.expand(node.node_id, repair))
        frontier = next_generation

    if validated is None:
        ctrl.apply_event("operator_needed", {})
        return

    survivor_metrics, _ = reviews.get(validated.attempt_id, ({}, []))
    # Projected Sharpe is what the candidate declared about itself. Paper launch
    # requires a held-out measurement, not an advisory-shaped pass.
    if survivor_metrics.get("ranking_basis") != "out_of_sample":
        ctrl.apply_event(
            "operator_needed",
            {
                "reason": "no_out_of_sample_evidence",
                "attempt_id": validated.attempt_id,
                "ranking_basis": survivor_metrics.get("ranking_basis"),
            },
        )
        return

    validated.state = "validated"
    ctrl.apply_event(
        "candidate_validated",
        {
            "attempt_id": validated.attempt_id,
            "validation_id": f"val_{validated.attempt_id}",
        },
    )

    # 4. Voyager-Style Automated Skill Distillation
    for skill in skill_distiller.distill_skills_from_candidate(validated):
        skill_library.register_skill(skill)

    # 5. Auto Paper Incubation. Paper launch stays gated on explicit pre-authorization.
    if not goal.paper_authorization:
        ctrl.apply_event("operator_needed", {})
        return

    ok, paper_inst_id, strat_name, _msg = incubation_resolver.resolve_and_provision_paper_trading(
        validated, goal.paper_authorization
    )
    if ok and paper_inst_id:
        ctrl.apply_event(
            "paper_started",
            {
                "attempt_id": validated.attempt_id,
                "paper_instance_id": paper_inst_id,
                "strategy_name": strat_name,
            },
        )
        ctrl.apply_event("mission_completed", {})
    else:
        ctrl.apply_event("operator_needed", {})
