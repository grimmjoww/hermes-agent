"""Evolver — turn observed failures into a RUNNABLE Program Function.

Core of the self-evolution loop. The dominant (tool, kind) failure is mapped to
the EARLIEST lifecycle layer that can catch it, and emitted as a runnable
EvolvedPF (should_activate + intervene) — NOT a passive description string — so
the HASP Q_exec gate has a valid candidate to admit.

GATE BOUNDARY: propose_rule is the Continual-Harness proposer, GATE-FREE. The
Q_exec admission + rollback is HASP (evolution_loop.try_admit).
"""
from harness_core.evolver import EvolvedPF, FailureEvent, ProposedRule, propose_rule
from harness_core.evolution_loop import SkillLibrary, try_admit
from harness_core.gate import Q_exec
from harness_core.program_function import (
    ActionOverride,
    AgentState,
    ContextInjection,
    PFExecution,
    PFRegistry,
)
from harness_core.layers.h4_trajectory import ToolCall


# --- existing metadata-mapping behavior (kept green) --------------------------

def test_dominant_loop_failure_proposes_h4_rule():
    fails = [FailureEvent("search_flights", "loop")] * 3 + [FailureEvent("book", "missing_arg")]
    r = propose_rule(fails)
    assert isinstance(r, ProposedRule)
    assert r.layer == "H4"
    assert r.target_tool == "search_flights"


def test_dominant_missing_arg_proposes_h2_rule():
    fails = [FailureEvent("book_flight", "missing_arg", "user_id")] * 3 + [FailureEvent("x", "loop")]
    r = propose_rule(fails)
    assert r.layer == "H2"
    assert r.target_tool == "book_flight"


def test_unknown_tool_failure_maps_to_h2():
    fails = [FailureEvent("teleport", "unknown_tool")] * 2
    r = propose_rule(fails)
    assert r.layer == "H2"


def test_wrong_tool_convention_maps_to_h3():
    fails = [FailureEvent("update_seat", "wrong_convention")] * 2
    r = propose_rule(fails)
    assert r.layer == "H3"


def test_no_failures_proposes_nothing():
    assert propose_rule([]) is None


# --- runnable-PF behavior (charter critical path) ----------------------------

def test_propose_rule_returns_runnable_program_function():
    r = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    assert callable(r.should_activate)
    assert callable(r.intervene)
    assert isinstance(r.name, str) and r.name
    assert isinstance(r.layer, str) and r.layer


def test_proposed_pf_activates_on_its_target_failure():
    r = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    r.threshold = 3
    state = AgentState(history=[ToolCall("search_flights", {})] * 2, memory={})
    assert r.should_activate(state, ToolCall("search_flights", {})) is True
    # broken trailing run -> no activation
    broken = AgentState(history=[ToolCall("search_flights", {}), ToolCall("other", {})], memory={})
    assert r.should_activate(broken, ToolCall("search_flights", {})) is False
    # different tool -> no activation
    assert r.should_activate(state, ToolCall("other", {})) is False


def test_proposed_pf_intervene_returns_a_real_intervention():
    r = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    state = AgentState(history=[ToolCall("search_flights", {})] * 3, memory={})
    out = r.intervene(state, ToolCall("search_flights", {}))
    assert isinstance(out, (ActionOverride, ContextInjection))
    assert "search_flights" in out.text


def test_missing_arg_pf_is_h2_and_repairs_or_injects():
    r = propose_rule([FailureEvent("book_flight", "missing_arg", "user_id")] * 3)
    assert r.layer == "H2"
    assert r.required_arg == "user_id"
    assert r.should_activate(AgentState(), ToolCall("book_flight", {})) is True
    assert r.should_activate(AgentState(), ToolCall("book_flight", {"user_id": "u1"})) is False
    # injection names the missing arg
    inj = r.intervene(AgentState(), ToolCall("book_flight", {}))
    assert isinstance(inj, ContextInjection)
    assert "user_id" in inj.text
    # repair via memory -> ActionOverride
    rep = r.intervene(AgentState(memory={"user_id": "u1"}), ToolCall("book_flight", {}))
    assert isinstance(rep, ActionOverride)
    assert rep.action.args["user_id"] == "u1"


def test_proposed_pf_runs_through_pfregistry():
    r = propose_rule([FailureEvent("book_flight", "missing_arg", "user_id")] * 3)
    out = PFRegistry([r]).apply(AgentState(), ToolCall("book_flight", {}))
    assert isinstance(out, PFExecution)
    assert out.pf_name == r.name
    assert out.layer == r.layer
    assert out.original_action.name == "book_flight"
    assert out.intervention is not None


def test_proposed_pf_is_admissible_through_gate_with_mock_qexec():
    r = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    lib = SkillLibrary()
    # mock Q_exec scorer: rewards a genuinely executable PF in the active set
    def scorer(active):
        if not active:
            return 0.5
        return 0.5 + sum(0.25 for pf in active if Q_exec(pf) >= 0.60)
    res = try_admit(lib, r, scorer)
    assert res.admitted is True
    assert r in lib.active


def test_emitted_pf_has_full_qexec_score():
    r = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    assert Q_exec(r) == 1.0  # runnable, legal return type


def test_layer_metadata_flows_into_from_rules():
    from harness_core.controller import HarnessController
    loop_pf = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    arg_pf = propose_rule([FailureEvent("book_flight", "missing_arg", "user_id")] * 3)
    c = HarnessController.from_rules([loop_pf, arg_pf], enabled=True)
    assert c.h4 is True   # loop PF
    assert c.h2 is True   # missing_arg PF
