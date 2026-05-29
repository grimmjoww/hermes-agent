"""HASP admission gate — paper-behavior tests (exact formulas / thresholds).

Grounded against HASP (arXiv 2605.17734):
  * A_t = 0.15*t + 0.10*m + 0.25*q + 0.50*o  (Sec 3.2 paper weights)
  * conjunctive two-gate: accept iff Q_exec>=eta_exec AND Q_teach>=eta_teach (Sec 3.3)
  * Gamma composes the activated PF set (Sec 3.1)

The numeric thresholds (0.30/0.60/0.42/0.75) are HARNESS operating points, NOT
paper constants — tests pin them as the harness's chosen values.
"""
import math

from harness_core.gate import (
    DEFAULT_LAMBDAS,
    AgenticSignal,
    Composition,
    GateConfig,
    GateDecision,
    GroupKind,
    Lambdas,
    admit,
    agentic_signal,
    assign_group,
    compose,
    Q_exec,
    Q_teach,
    teacher_select,
)
from harness_core.program_function import (
    ActionOverride,
    AgentState,
    ContextInjection,
)
from harness_core.layers.h4_trajectory import ToolCall


# --- A_t agentic signal (paper Sec 3.2) ---------------------------------------

def test_agentic_signal_paper_weights_exact():
    assert agentic_signal(AgenticSignal(1, 1, 1, 1)) == 1.0
    assert agentic_signal(AgenticSignal(1, 0, 0, 0)) == 0.15
    assert agentic_signal(AgenticSignal(0, 1, 0, 0)) == 0.10
    assert agentic_signal(AgenticSignal(0, 0, 1, 0)) == 0.25
    assert agentic_signal(AgenticSignal(0, 0, 0, 1)) == 0.50


def test_agentic_signal_mixed_example():
    a = agentic_signal(AgenticSignal(t=0.8, m=0.4, q=0.6, o=0.9))
    # 0.15*0.8 + 0.10*0.4 + 0.25*0.6 + 0.50*0.9 = 0.12+0.04+0.15+0.45 = 0.76
    assert math.isclose(a, 0.76)


def test_lambdas_sum_to_one():
    assert sum(DEFAULT_LAMBDAS.as_tuple()) == 1.0
    try:
        Lambdas(t=0.5, m=0.5, q=0.5, o=0.5)
        assert False, "non-unit lambda sum should raise"
    except ValueError:
        pass


# --- two-gate admission (conjunctive, paper Sec 3.3) --------------------------

def test_hard_reject_when_qexec_below_0_30():
    # exec short-circuits even with perfect skill -> conjunctive gate proof
    assert admit(q_exec=0.29, q_skill=0.99) == GateDecision.REJECT
    assert admit(q_exec=0.30, q_skill=0.99) != GateDecision.REJECT  # boundary inclusive


def test_accept_when_qskill_at_or_above_0_60():
    assert admit(q_exec=1.0, q_skill=0.60) == GateDecision.ACCEPT  # boundary inclusive
    assert admit(q_exec=1.0, q_skill=0.75) == GateDecision.ACCEPT


def test_revise_band_0_42_to_0_60():
    assert admit(q_exec=1.0, q_skill=0.42) == GateDecision.REVISE  # low inclusive
    assert admit(q_exec=1.0, q_skill=0.59) == GateDecision.REVISE
    assert admit(q_exec=1.0, q_skill=0.60) == GateDecision.ACCEPT  # upper NOT revise


def test_reject_when_qskill_below_0_42():
    assert admit(q_exec=1.0, q_skill=0.41) == GateDecision.REJECT


# --- library grouping + teacher-select ----------------------------------------

def test_group_new_when_similarity_below_0_75():
    assert assign_group(0.74).kind == GroupKind.AMBIGUOUS  # 0.74 in [0.60,0.75)
    assert assign_group(0.59).kind == GroupKind.NEW_GROUP  # below same-group floor


def test_group_same_when_similarity_at_or_above_0_75():
    d = assign_group(0.80, best_group="g1")
    assert d.kind == GroupKind.SAME_GROUP
    assert d.best_group == "g1"
    assert assign_group(0.75).kind == GroupKind.SAME_GROUP  # boundary inclusive


def test_group_ambiguous_band_defers_to_teacher_select():
    assert assign_group(0.68).kind == GroupKind.AMBIGUOUS  # [0.60,0.75)
    assert assign_group(0.60).kind == GroupKind.AMBIGUOUS  # lower boundary inclusive


def test_teacher_select_picks_highest_agentic_signal():
    class _PF:
        def __init__(self, name):
            self.name = name

    pfA, pfB, pfC = _PF("pfA"), _PF("pfB"), _PF("pfC")
    signals = {pfA: 0.9, pfB: 0.7, pfC: 0.9}
    qteach = {pfA: 0.5, pfB: 0.5, pfC: 0.5}
    winner1 = teacher_select([pfA, pfB, pfC], lambda p: signals[p], lambda p: qteach[p])
    winner2 = teacher_select([pfA, pfB, pfC], lambda p: signals[p], lambda p: qteach[p])
    assert winner1 is winner2  # deterministic
    # tie between pfA & pfC on signal+qteach -> lexical name -> pfA
    assert winner1 is pfA


# --- Gamma multi-PF composition (paper Sec 3.1) -------------------------------

def _state():
    return AgentState(history=[], memory={})


def test_gamma_compose_action_override_dominates_context():
    class _OverridePF:
        name, layer = "ov", "H2"
        def intervene(self, s, a):
            return ActionOverride(ToolCall("fixed", {"ok": 1}))

    class _CtxPF:
        name, layer = "ctx", "H5"
        def intervene(self, s, a):
            return ContextInjection("be careful")

    comp = compose([_OverridePF(), _CtxPF()], _state(), ToolCall("x", {}))
    assert isinstance(comp, Composition)
    assert comp.action_out == ToolCall("fixed", {"ok": 1})
    assert "be careful" in comp.context_out  # c_t preserves guidance


def test_gamma_compose_multiple_overrides_teacher_wins():
    class _PF:
        def __init__(self, name, repl):
            self.name, self.layer, self._repl = name, "H2", repl
        def intervene(self, s, a):
            return ActionOverride(ToolCall(self._repl, {}))

    teacher = _PF("teacher", "by_teacher")
    other = _PF("other", "by_other")
    signals = {teacher: 0.9, other: 0.3}
    comp = compose([other, teacher], _state(), ToolCall("x", {}),
                   signal_of=lambda p: signals[p])
    assert comp.action_out == ToolCall("by_teacher", {})
    names = {m["pf_name"] for m in comp.meta}
    assert names == {"teacher", "other"}  # kappa_t lists both


def test_gamma_compose_single_pf_matches_registry_first_wins():
    class _CtxPF:
        name, layer = "ctx", "H5"
        def intervene(self, s, a):
            return ContextInjection("guidance")

    comp = compose([_CtxPF()], _state(), ToolCall("x", {}))
    assert comp.action_out is None
    assert comp.context_out == "guidance"


# --- Q_exec executability + provenance -----------------------------------------

def test_qexec_rejects_pf_with_illegal_return_type():
    class _BadReturnPF:
        name, layer = "bad", "H2"
        def should_activate(self, s, a):
            return True
        def intervene(self, s, a):
            return {"not": "an intervention"}  # illegal type

    score = Q_exec(_BadReturnPF())
    assert score < 0.30  # below hard-reject floor
    assert admit(q_exec=score, q_skill=0.99) == GateDecision.REJECT


def test_qexec_full_score_for_valid_pf():
    class _GoodPF:
        name, layer = "good", "H2"
        def should_activate(self, s, a):
            return True
        def intervene(self, s, a):
            return ContextInjection("ok")

    assert Q_exec(_GoodPF()) == 1.0


def test_qteach_is_pluggable():
    class _PF:
        name = "p"
    assert Q_teach(_PF(), lambda pf: 0.73) == 0.73


def test_threshold_provenance_documented():
    doc = GateConfig.__doc__ or ""
    assert "harness operating point" in doc
    assert "NOT a HASP-published" in doc
