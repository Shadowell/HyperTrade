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
