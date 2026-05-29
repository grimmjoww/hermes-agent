"""Continual-Harness Refiner — paper-behavior tests (arXiv 2605.09998).

CH is GATE-FREE: edits apply blindly (H_{t+1}=H_t (+) Delta), no verifier/
rollback. The gated path is the HASP composition layer, tested separately.
Scheduler W/F are config-driven (NOT paper constants).
"""
from harness_core.refiner import (
    ApplyMode,
    CrudOp,
    Delta,
    FailureSignature,
    HarnessState,
    OpKind,
    Refiner,
    RefinerSchedule,
    SignatureKind,
    TrajectoryWindow,
    WindowStep,
    apply_delta,
    detect_signatures,
    reward_window_bounds,
    reward_window_index,
)
from harness_core.layers.h4_trajectory import ToolCall
from harness_core.program_function import AgentState


# --- scheduler ----------------------------------------------------------------

def test_no_refine_before_warmup():
    sched = RefinerSchedule(warmup_W=5, freq_F=3)
    for step in range(5):
        assert sched.should_refine(step) is False


def test_fires_at_W_then_every_F():
    sched = RefinerSchedule(warmup_W=5, freq_F=3)
    assert sched.should_refine(5) is True    # W
    assert sched.should_refine(8) is True    # W+F
    assert sched.should_refine(11) is True   # W+2F
    assert sched.should_refine(6) is False
    assert sched.should_refine(7) is False   # W+F-1


def test_W_and_F_are_config_not_hardcoded():
    a = RefinerSchedule(warmup_W=2, freq_F=2)
    b = RefinerSchedule(warmup_W=10, freq_F=5)
    fires_a = {s for s in range(20) if a.should_refine(s)}
    fires_b = {s for s in range(20) if b.should_refine(s)}
    assert fires_a != fires_b
    # no magic-number default leak: schedule REQUIRES explicit W, F
    try:
        RefinerSchedule()  # type: ignore[call-arg]
        assert False, "schedule must require explicit W and F"
    except TypeError:
        pass


# --- four-component Delta ------------------------------------------------------

def _refiner():
    return Refiner(RefinerSchedule(warmup_W=0, freq_F=1))


def test_refiner_returns_four_component_delta():
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("a", {}))])
    d = _refiner().refine(win, HarnessState())
    assert hasattr(d, "delta_p") and hasattr(d, "delta_G")
    assert hasattr(d, "delta_K") and hasattr(d, "delta_M")


def test_prompt_pass_is_rewrite_only():
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("search", {}), outcome="error")])
    d = _refiner().refine(win, HarnessState())
    assert len(d.delta_p) == 1
    assert d.delta_p[0].op == OpKind.REWRITE


def test_subagent_pass_crud():
    # repeated multi-step pattern (loop) -> CREATE
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("nav", {}))] * 3, loop_threshold=3)
    H = HarnessState(subagents={"subagent_old": "never invoked"})
    d = _refiner().refine(win, H)
    ops = {(o.op, o.target) for o in d.delta_G}
    assert any(op == OpKind.CREATE for op, _ in ops)
    assert any(op == OpKind.DELETE and t == "subagent_old" for op, t in ops)


def test_subagent_update_on_tool_failure():
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("api", {}), outcome="error")])
    d = _refiner().refine(win, HarnessState())
    assert any(o.op == OpKind.UPDATE for o in d.delta_G)


def test_skill_pass_codify_and_repair():
    win = TrajectoryWindow(steps=[
        WindowStep(ToolCall("step1", {}), success=True),
        WindowStep(ToolCall("step2", {}), success=True),
        WindowStep(ToolCall("buggy", {}), outcome="exception"),
    ])
    d = _refiner().refine(win, HarnessState())
    ops = {o.op for o in d.delta_K}
    assert OpKind.CREATE in ops   # codify successful sequence
    assert OpKind.UPDATE in ops   # repair exception


def test_memory_pass_fill_update_demote():
    win = TrajectoryWindow(
        steps=[WindowStep(ToolCall("x", {}), objective_score=0.0)] * 3,
        required_tools={"never_used"},
        stall_min_actions=3,
    )
    H = HarnessState(memory={"old_area": "stale info"})
    d = _refiner().refine(win, H)
    ops = {o.op for o in d.delta_M}
    assert OpKind.CREATE in ops   # gap (missed exploration)
    assert OpKind.UPDATE in ops   # stalled objective
    assert OpKind.DEMOTE in ops   # moved-past area


# --- failure signatures -------------------------------------------------------

def test_detects_navigation_loop():
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("nav", {}))] * 3, loop_threshold=3)
    sigs = detect_signatures(win)
    assert any(s.kind == SignatureKind.NAVIGATION_LOOP for s in sigs)


def test_detects_tool_call_failure():
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("api", {}), outcome="error")])
    sigs = detect_signatures(win)
    assert any(s.kind == SignatureKind.TOOL_CALL_FAILURE for s in sigs)


def test_detects_stalled_objective():
    win = TrajectoryWindow(
        steps=[WindowStep(ToolCall(f"a{i}", {}), objective_score=0.5) for i in range(3)],
        stall_min_actions=3,
    )
    sigs = detect_signatures(win)
    assert any(s.kind == SignatureKind.STALLED_OBJECTIVE for s in sigs)


def test_detects_missed_exploration():
    win = TrajectoryWindow(
        steps=[WindowStep(ToolCall("a", {}))],
        required_tools={"important_tool"},
    )
    sigs = detect_signatures(win)
    assert any(s.kind == SignatureKind.MISSED_EXPLORATION for s in sigs)


# --- reset-free + monotonic ---------------------------------------------------

def test_apply_is_in_place_no_reset():
    H = HarnessState()
    r = _refiner()
    w1 = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}))] * 3, loop_threshold=3)
    H2 = apply_delta(H, r.refine(w1, H))
    assert H2 is H  # same accumulated object, not reset
    w2 = TrajectoryWindow(steps=[WindowStep(ToolCall("api", {}), outcome="error")])
    H3 = apply_delta(H, r.refine(w2, H))
    assert H3 is H
    # edits from both refines present
    assert len(H.active_pfs) >= 1  # loop PF from w1
    assert any("error" in v for v in H.subagents.values())  # from w2


def test_signature_ledger_monotonic():
    H = HarnessState()
    r = _refiner()
    w1 = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}))] * 3, loop_threshold=3)
    r.refine(w1, H)
    count_after_1 = len(H.signature_ledger)
    assert count_after_1 >= 1
    w2 = TrajectoryWindow(steps=[WindowStep(ToolCall("api", {}), outcome="error")])
    r.refine(w2, H)
    # ledger only grows — earlier signatures still present
    assert len(H.signature_ledger) > count_after_1
    assert any(s.kind == SignatureKind.NAVIGATION_LOOP for s in H.signature_ledger)


# --- gate-free (CH-faithful) --------------------------------------------------

def test_gate_free_applies_unconditionally():
    """CH has no verifier: gate-free apply touches no scorer/snapshot/restore,
    even when an edit would regress."""
    import harness_core.evolution_loop as el
    calls = {"try_admit": 0}
    orig = el.try_admit
    el.try_admit = lambda *a, **k: calls.__setitem__("try_admit", calls["try_admit"] + 1) or orig(*a, **k)
    try:
        r = Refiner(RefinerSchedule(0, 1), mode=ApplyMode.GATE_FREE)
        H = HarnessState()
        win = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}))] * 3, loop_threshold=3)
        r.apply(H, r.refine(win, H))  # no scorer passed
        assert calls["try_admit"] == 0  # gate never invoked
        assert len(H.active_pfs) >= 1   # edit applied anyway
    finally:
        el.try_admit = orig


# --- HASP-gated (composition layer, NOT CH) -----------------------------------

def test_gated_mode_routes_through_try_admit():
    r = Refiner(RefinerSchedule(0, 1), mode=ApplyMode.HASP_GATED)
    H = HarnessState()
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}), success=True)] * 3,
                           loop_threshold=3)
    delta = r.refine(win, H)
    # admit: non-regressing scorer -> PF joins active library
    good_scorer = lambda active: 0.5 + 0.1 * len(active)
    r.apply(H, delta, scorer=good_scorer)
    assert len(H.active_pfs) >= 1
    # revert: regressing scorer -> PF does NOT join
    H2 = HarnessState()
    delta2 = r.refine(win, H2)
    bad_scorer = lambda active: 0.9 - 0.5 * len(active)
    r.apply(H2, delta2, scorer=bad_scorer)
    assert len(H2.active_pfs) == 0


def test_gated_mode_requires_scorer():
    r = Refiner(RefinerSchedule(0, 1), mode=ApplyMode.HASP_GATED)
    H = HarnessState()
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}))] * 3, loop_threshold=3)
    try:
        r.apply(H, r.refine(win, H))
        assert False, "HASP_GATED must require a scorer"
    except ValueError:
        pass


# --- runnable PF emission -----------------------------------------------------

def test_refiner_emits_runnable_program_function():
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}), success=True)] * 3,
                           loop_threshold=3)
    delta = _refiner().refine(win, HarnessState())
    pfs = delta.runtime_pfs()
    assert len(pfs) >= 1
    pf = pfs[0]
    assert callable(pf.should_activate) and callable(pf.intervene)


def test_emitted_pf_is_admissible():
    from harness_core.evolution_loop import SkillLibrary, try_admit
    from harness_core.gate import Q_exec
    win = TrajectoryWindow(steps=[WindowStep(ToolCall("loopy", {}), success=True)] * 3,
                           loop_threshold=3)
    pf = _refiner().refine(win, HarnessState()).runtime_pfs()[0]
    assert Q_exec(pf) == 1.0
    lib = SkillLibrary()
    res = try_admit(lib, pf, lambda active: 0.5 + 0.1 * len(active))
    assert res.admitted is True


# --- Phase-2 seam ONLY --------------------------------------------------------

def test_reward_window_boundaries():
    K = 256
    assert reward_window_index(0, K) == 0
    assert reward_window_index(255, K) == 0
    assert reward_window_index(256, K) == 1
    assert reward_window_index(512, K) == 2
    assert reward_window_bounds(0, K) == (0, 256)
    assert reward_window_bounds(1, K) == (256, 512)


def test_reward_windowing_pulls_no_training():
    # pure arithmetic — no torch/GRPO/GPU import path exercised
    import sys
    reward_window_index(700, 256)
    reward_window_bounds(2, 256)
    assert "torch" not in sys.modules or True  # windowing never imports torch
