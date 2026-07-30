"""
ARC API Router - Single Entry Autonomous Exploration & Event Streaming
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant
from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.mcts import ARCMCTSEngine
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

    background_tasks.add_task(run_autonomous_arc_loop, controller.mission_id)

    return {
        "mission_id": controller.mission_id,
        "status": controller.projection.state,
        "objective": request.objective,
        "message": "Production-Grade SOTA ARC Autonomous Exploration Loop started",
    }


@router.get("/missions/{mission_id}")
async def get_arc_mission(mission_id: str) -> dict[str, Any]:
    if mission_id not in _ARC_MISSIONS:
        raise HTTPException(status_code=404, detail="ARC Mission not found")
    ctrl = _ARC_MISSIONS[mission_id]
    return ctrl.projection.model_dump()


def run_autonomous_arc_loop(mission_id: str) -> None:
    """
    Production SOTA Autonomous Execution Engine Loop:
    Goal -> MCTS Node -> Blue Proposal -> Red Attack -> Multi-Regime Causal Reflexion ->
    AST Mutation -> Verification -> Voyager Skill Distillation -> Auto Paper Launch
    """
    ctrl = _ARC_MISSIONS.get(mission_id)
    if not ctrl:
        return

    goal = ctrl.projection.goal
    if not goal:
        return

    ctrl.apply_event("goal_compiled", {"goal": goal.model_dump()})

    blue_team = BlueTeamQuant()
    engine = ARCAdversarialEngine()
    mutator = ARCGeneticMutator()
    reflexion_ledger = ARCReflexionLedger()
    mcts_engine = ARCMCTSEngine()
    skill_library = ARCSkillLibrary()
    skill_distiller = ARCSkillDistiller()
    incubation_resolver = ARCPaperIncubationResolver()

    # 1. Initial Blue Team Proposal & MCTS Tree Root Initialization
    symbol = goal.symbols[0] if goal.symbols else "BTC-USDT-SWAP"
    initial_attempt = blue_team.propose_initial_strategy(goal.objective, symbol)
    ctrl.apply_event("candidate_proposed", {"attempt": initial_attempt.model_dump()})
    mcts_engine.add_root(initial_attempt)

    # 2. First Red Team Attack
    passed, metrics, reasons = engine.run_adversarial_session(initial_attempt)
    ctrl.apply_event(
        "red_team_tested",
        {
            "attempt_id": initial_attempt.attempt_id,
            "passed": passed,
            "metrics": metrics,
        },
    )
    mcts_engine.backpropagate(
        initial_attempt.attempt_id, metrics.get("sharpe_after_attack", 0.0)
    )

    if not passed:
        # 3. Multi-Regime Causal Reflexion & Diagnosis
        reflexion = reflexion_ledger.diagnose_and_record_failure(
            attempt=initial_attempt,
            failure_class="red_team_attack_failed",
            observed_metrics=metrics,
            raw_reasons=reasons,
        )
        ctrl.apply_event("reflexion_recorded", {"reflexion": reflexion.model_dump()})

        # 4. MCTS Node Expansion & AST Mutation Guided by Reflexion
        best_node = mcts_engine.select_best_node_to_expand()
        parent_id = best_node.node_id if best_node else initial_attempt.attempt_id

        mutated_attempt = mutator.mutate_attempt(
            initial_attempt, reflexion_ledger.get_history()
        )
        ctrl.apply_event(
            "candidate_proposed", {"attempt": mutated_attempt.model_dump()}
        )
        ctrl.apply_event(
            "candidate_mutated",
            {
                "attempt_id": mutated_attempt.attempt_id,
                "strategy_code": mutated_attempt.strategy_code,
            },
        )
        mcts_engine.add_child(parent_id, mutated_attempt)

        # 5. Second Red Team Attack on Mutated Attempt
        passed2, metrics2, reasons2 = engine.run_adversarial_session(mutated_attempt)
        ctrl.apply_event(
            "red_team_tested",
            {
                "attempt_id": mutated_attempt.attempt_id,
                "passed": passed2,
                "metrics": metrics2,
            },
        )
        mcts_engine.backpropagate(
            mutated_attempt.attempt_id, metrics2.get("sharpe_after_attack", 1.5)
        )

        if passed2:
            mutated_attempt.state = "validated"
            ctrl.apply_event(
                "candidate_validated",
                {
                    "attempt_id": mutated_attempt.attempt_id,
                    "validation_id": f"val_{mutated_attempt.attempt_id}",
                },
            )

            # 6. Voyager-Style Automated Skill Distillation
            distilled_skills = skill_distiller.distill_skills_from_candidate(
                mutated_attempt
            )
            for skill in distilled_skills:
                skill_library.register_skill(skill)

            # 7. Auto Paper Incubation
            if goal.paper_authorization:
                ok, paper_inst_id, msg = (
                    incubation_resolver.resolve_and_provision_paper_trading(
                        mutated_attempt, goal.paper_authorization
                    )
                )
                if ok and paper_inst_id:
                    ctrl.apply_event(
                        "paper_started",
                        {
                            "attempt_id": mutated_attempt.attempt_id,
                            "paper_instance_id": paper_inst_id,
                        },
                    )
                    ctrl.apply_event("mission_completed", {})
                else:
                    ctrl.apply_event("operator_needed", {})
            else:
                ctrl.apply_event("operator_needed", {})
        else:
            ctrl.apply_event("operator_needed", {})
    else:
        initial_attempt.state = "validated"
        ctrl.apply_event(
            "candidate_validated",
            {
                "attempt_id": initial_attempt.attempt_id,
                "validation_id": f"val_{initial_attempt.attempt_id}",
            },
        )

        distilled_skills = skill_distiller.distill_skills_from_candidate(
            initial_attempt
        )
        for skill in distilled_skills:
            skill_library.register_skill(skill)

        if goal.paper_authorization:
            ok, paper_inst_id, msg = (
                incubation_resolver.resolve_and_provision_paper_trading(
                    initial_attempt, goal.paper_authorization
                )
            )
            if ok and paper_inst_id:
                ctrl.apply_event(
                    "paper_started",
                    {
                        "attempt_id": initial_attempt.attempt_id,
                        "paper_instance_id": paper_inst_id,
                    },
                )
                ctrl.apply_event("mission_completed", {})
