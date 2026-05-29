"""Evolution loop — regression-gated PF admission with rollback.

Addresses the "saturate early and don't roll back" failure mode: a candidate PF
is admitted to the active library ONLY if it does not regress the score
(HASP: "admit only after validation"). If it regresses, it is rolled back.
This keeps the self-evolution loop from accumulating harmful rules.
"""
from harness_core.evolution_loop import SkillLibrary, try_admit


def test_admits_pf_that_improves():
    lib = SkillLibrary()
    scorer = lambda active: 0.8 if active else 0.5  # adding any PF helps
    res = try_admit(lib, "pf_A", scorer)
    assert res.admitted is True
    assert res.score_after >= res.score_before
    assert "pf_A" in lib.active


def test_rolls_back_pf_that_regresses():
    lib = SkillLibrary()
    scorer = lambda active: 0.3 if active else 0.5  # adding the PF hurts
    res = try_admit(lib, "pf_B", scorer)
    assert res.admitted is False
    assert "pf_B" not in lib.active  # rolled back — library unchanged


def test_neutral_pf_is_not_admitted_keep_library_minimal():
    lib = SkillLibrary()
    scorer = lambda active: 0.5  # no change either way
    res = try_admit(lib, "pf_C", scorer, require_strict_improvement=True)
    assert res.admitted is False  # no regression, but no gain -> don't bloat


def test_snapshot_restore_enables_rollback_between_tests():
    lib = SkillLibrary()
    lib.add("x")
    snap = lib.snapshot()
    lib.add("y")
    lib.restore(snap)
    assert lib.active == ["x"]  # reverted to snapshot (reset between tests)


def test_rollback_is_total_library_identical_to_snapshot():
    """HASP gate: on reject, the active list is restored element-for-element to
    its exact pre-admission contents (total rollback, not partial)."""
    lib = SkillLibrary()
    lib.add("a")
    lib.add("b")
    expected = list(lib.active)
    scorer = lambda active: 0.2 if "cand" in active else 0.9  # candidate regresses
    res = try_admit(lib, "cand", scorer)
    assert res.admitted is False
    assert lib.active == expected  # exact element-for-element match
    assert "cand" not in lib.active


def test_admit_result_reports_scores_on_revert():
    """Gate decision is observable: both scores populated so the visible surface
    can emit 'REVERTED (0.90 -> 0.20)'."""
    lib = SkillLibrary()
    scorer = lambda active: 0.2 if "cand" in active else 0.9
    res = try_admit(lib, "cand", scorer)
    assert res.score_before == 0.9
    assert res.score_after == 0.2
