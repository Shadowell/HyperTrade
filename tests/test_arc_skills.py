"""
Test ARC Voyager-Style Automated Skill Distillation & Library
"""

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.skills import ARCSkillDistiller, ARCSkillLibrary


def test_arc_skill_distillation_and_registration():
    distiller = ARCSkillDistiller()
    library = ARCSkillLibrary()

    code_with_helper = """class CustomStrategy:
    lookback = 20

    def compute_volatility_channel(self, candles):
        prices = [c['close'] for c in candles]
        return max(prices) - min(prices)

    def next_signal(self, candles):
        vol = self.compute_volatility_channel(candles)
        return "buy" if vol > 10 else "hold"
"""

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_val_999",
        candidate_id="cand_val_999",
        state="validated",
        hypothesis="Strategy with custom helper function",
        strategy_code=code_with_helper,
    )

    skills = distiller.distill_skills_from_candidate(attempt)
    assert len(skills) > 0

    for s in skills:
        library.register_skill(s)

    assert len(library.list_skills()) > 0
    prompt_fmt = library.format_skills_for_prompt()
    assert (
        "compute_volatility_channel" in prompt_fmt
        or "calculate_adaptive_volatility_stop" in prompt_fmt
    )


def test_skill_library_rebuilds_from_persisted_events():
    """Voyager 回路：skill_registered 事件重建技能库，注册即遗忘语义被移除。"""
    from types import SimpleNamespace

    from hypertrade.arc.router import _rebuild_skill_library
    from hypertrade.arc.skills import ARCSkill

    skill = ARCSkill(
        skill_id="skill_adaptive_stop_abc123",
        name="calculate_adaptive_volatility_stop",
        description="Distilled adaptive stop",
        code_snippet="def calculate_adaptive_volatility_stop(p, dd=0.08):\n    return p * (1 - dd)",
        provenance_candidate_id="cand_abc123",
        tags=["ast_distilled"],
    )
    events = [
        SimpleNamespace(event_type="skill_registered", payload={"skill": skill.model_dump()}),
        SimpleNamespace(event_type="candidate_proposed", payload={}),
        SimpleNamespace(event_type="skill_registered", payload={"skill": {"corrupt": True}}),
    ]

    library = _rebuild_skill_library(events)

    assert library.get_skill(skill.skill_id) is not None
    # Corrupt legacy event skipped without blocking the rebuild.
    assert len(library.list_skills()) == 1


def test_skill_prompt_digest_is_bounded():
    from hypertrade.arc.skills import ARCSkill, ARCSkillLibrary

    library = ARCSkillLibrary()
    for index in range(12):
        library.register_skill(
            ARCSkill(
                skill_id=f"skill_{index:02d}",
                name=f"helper_{index}",
                description="x" * 40,
                code_snippet="def helper():\n    return 1",
                provenance_candidate_id=f"cand_{index}",
            )
        )

    digest = library.format_skills_for_prompt(max_skills=5, max_chars=2400)

    assert "Available Validated Modular Skills" in digest
    assert len(digest) <= 2400
    # Newest skills win the bounded window.
    assert "helper_11" in digest
    assert "helper_00" not in digest
