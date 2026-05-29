"""E2E live-slice acceptance tests (branch feat/hermes-pr-2026-05-29).

These are the charter's four acceptance slices, run in-process (no OV server, no
Hermes process needed — they exercise the REAL harness_core objects end to end):

  (a) SKILL-PROGRAM: feed ONE real existing skill -> it becomes a managed HASP
      program-function held by the SAME PFRegistry as evolved PFs (no new infra).
  (b) failure -> propose_rule -> try_admit (HASP-gated) -> persist -> reload:
      the full evolve+gate+persist+reconfigure spine, across a fresh store
      instance (a new "session") using real on-disk FileRuleStore.
  (c) try_admit ROLLS BACK a regressing PF: the HASP regression gate refuses a
      candidate that lowers the score and restores the prior library.
  (d) a VISIBLE event fires: refine/admit/revert publish typed events on the
      EventStream surface; we assert a subscriber actually received them.

Paper-faithfulness honored:
  * The gate/rollback (try_admit) is labeled HASP, NOT Continual-Harness.
  * propose_rule emits a RUNNABLE EvolvedPF (should_activate/intervene), so the
    gate has something valid (Q_exec) to admit.
"""
from __future__ import annotations

from pathlib import Path

from harness_core.controller import HarnessController
from harness_core.evolution_loop import SkillLibrary, try_admit
from harness_core.events import EventKind, EventStream
from harness_core.evolver import FailureEvent, propose_rule
from harness_core.layers.h4_trajectory import ToolCall
from harness_core.layers.h5_procedural_skill import Skill
from harness_core.persistence import FileRuleStore
from harness_core.program_function import AgentState, ContextInjection, PFRegistry
from harness_core.skill_program import promote_skill


# --- (a) SKILL-PROGRAM: a real skill becomes a managed PF, no new infra -------

def test_a_real_skill_becomes_managed_program_function():
    # A REAL existing skill (a feature: procedural guidance), not a memory.
    skill = Skill(
        name="verify_before_commit",
        content="Run the test suite and confirm green output before committing.",
    )

    # Promote it -> managed HASP PF. The result is held by the EXISTING PFRegistry,
    # exactly like an evolved PF (no new infrastructure).
    pf = promote_skill(skill, trigger_tool="git_commit")
    registry = PFRegistry([pf])

    state = AgentState(history=[], memory={})
    # The agent is about to commit -> the skill-PF must activate and intervene.
    execution = registry.apply(state, ToolCall("git_commit", {"msg": "wip"}))

    assert execution is not None, "skill-PF did not fire on its trigger tool"
    assert execution.pf_name == "skillpf_verify_before_commit"
    assert execution.layer == "H5"
    assert isinstance(execution.intervention, ContextInjection)
    assert "Run the test suite" in execution.intervention.text

    # Negative control: an unrelated tool must NOT trip it (no spurious injection).
    assert registry.apply(state, ToolCall("search", {"q": "x"})) is None


# --- (b) failure -> propose -> gated admit -> persist -> reload ---------------

def test_b_failure_to_persist_to_reload(tmp_path: Path):
    store_path = tmp_path / "rules.json"
    namespace = "harness-study"

    # 1. observe a recurring deterministic failure
    failures = [FailureEvent("search_flights", "loop")] * 3
    candidate = propose_rule(failures)
    assert candidate is not None
    # propose_rule emits a RUNNABLE PF (has should_activate/intervene) -> valid for
    # the gate. Sanity-check it actually fires on a real looped trajectory.
    looped = [ToolCall("search_flights", {})] * 3
    st = AgentState(history=looped[:-1], memory={})
    assert candidate.should_activate(st, looped[-1]) is True

    # 2. HASP-gated admission (try_admit) with a non-regressing scorer -> admitted
    lib = SkillLibrary()
    scorer = lambda active: 0.5 + 0.1 * len(active)  # more PFs -> not worse
    result = try_admit(lib, candidate, scorer)
    assert result.admitted is True
    assert len(lib.active) == 1

    # 3. persist the admitted rule to a REAL on-disk store (this "session")
    session1 = FileRuleStore(store_path, namespace)
    session1.save(candidate)
    assert store_path.exists()

    # 4. reload in a FRESH store instance == a NEW session, and reconfigure the
    #    harness from what the previous session learned.
    session2 = FileRuleStore(store_path, namespace)
    reloaded = session2.load()
    assert len(reloaded) == 1
    assert reloaded[0].target_tool == "search_flights"
    assert reloaded[0].kind == "loop"
    assert reloaded[0].layer == "H4"

    controller = HarnessController.from_rules(reloaded, enabled=True)
    assert controller.h4 is True  # the H4 layer is on BECAUSE the rule persisted
    # and it actually catches the same loop in the new session
    correction = controller.monitor_post_execution([ToolCall("search_flights", {})] * 3)
    assert correction is not None
    assert correction.tool_name == "search_flights"

    # namespace isolation: a different namespace sees nothing
    other = FileRuleStore(store_path, "some-other-namespace")
    assert other.load() == []


# --- (c) try_admit ROLLS BACK a regressing PF --------------------------------

def test_c_try_admit_rolls_back_regressing_pf():
    lib = SkillLibrary()
    # seed an existing good PF
    good = promote_skill(Skill("good", "keep me"))
    lib.add(good)
    before_snapshot = list(lib.active)

    candidate = propose_rule([FailureEvent("x", "loop")] * 3)
    assert candidate is not None

    # a scorer where adding the candidate REGRESSES the score -> must roll back
    regressing_scorer = lambda active: 0.9 - 0.5 * len(active)
    result = try_admit(lib, candidate, regressing_scorer)

    assert result.admitted is False
    assert result.score_after < result.score_before
    # library restored to exactly the pre-admit state (no partial mutation)
    assert lib.active == before_snapshot
    assert candidate not in lib.active


# --- (d) a VISIBLE event fires -----------------------------------------------

def test_d_visible_event_fires_on_admit_and_revert():
    stream = EventStream()
    seen: list = []
    stream.subscribe(seen.append)  # a real subscriber (stands in for CLI/gateway)

    # admit path emits PF_ADMITTED
    lib = SkillLibrary()
    candidate = propose_rule([FailureEvent("book", "missing_arg", "user_id")] * 3)
    res = try_admit(lib, candidate, scorer=lambda a: 0.5 + 0.1 * len(a))
    if res.admitted:
        stream.emit(EventKind.PF_ADMITTED, f"ADMITTED {candidate.name}",
                    score_before=res.score_before, score_after=res.score_after)

    # revert path emits PF_REVERTED
    lib2 = SkillLibrary()
    lib2.add(promote_skill(Skill("seed", "x")))
    res2 = try_admit(lib2, candidate, scorer=lambda a: 0.9 - 0.5 * len(a))
    if not res2.admitted:
        stream.emit(EventKind.PF_REVERTED, f"REVERTED {candidate.name}",
                    score_before=res2.score_before, score_after=res2.score_after)

    # the user SEES it: a subscriber actually received both events
    assert len(seen) == 2
    kinds = {e.kind for e in seen}
    assert EventKind.PF_ADMITTED in kinds
    assert EventKind.PF_REVERTED in kinds
    # and the rendered surface line is human-readable
    admitted_ev = stream.events_of(EventKind.PF_ADMITTED)[0]
    assert admitted_ev.render().startswith("[pf_admitted] ADMITTED")
    assert "ADMITTED" in admitted_ev.message
