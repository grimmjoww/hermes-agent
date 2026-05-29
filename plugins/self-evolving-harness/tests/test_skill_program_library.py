"""Tests for the 10 real-Hermes-skill -> HASP ProgramFunction conversions.

One test per conversion. Each asserts (a) the guardrail ACTIVATES on a realistic
agent state where the source skill says it should, (b) the INTERVENTION is the
right kind (ContextInjection / ActionOverride) and carries the skill's guidance,
and (c) it does NOT fire when the precondition is already satisfied (no spurious
guardrail). The registry integration test proves they're managed exactly like
evolved PFs.
"""
from harness_core.layers.h4_trajectory import ToolCall
from harness_core.program_function import (
    ActionOverride,
    AgentState,
    ContextInjection,
    PFExecution,
)
from skill_program_library import (
    ArxivApiGuardPF,
    EmailSendReviewPF,
    GithubAuthGuardPF,
    PRMergeChecksPF,
    PlanModeGuardPF,
    PreCommitReviewPF,
    RootCauseGuardPF,
    SKILL_PROGRAM_FUNCTIONS,
    TDDGuardPF,
    WritePlanBeforeDelegatePF,
    XPostConfirmPF,
    build_skill_pf_registry,
)


def _term(command):
    return ToolCall("terminal", {"command": command})


# 1. test-driven-development
def test_tdd_guard_blocks_impl_before_failing_test():
    pf = TDDGuardPF()
    state = AgentState(memory={})  # no failing test seen
    action = ToolCall("write_file", {"path": "src/feature.py"})
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "RED before GREEN" in out.text
    # does NOT fire once a failing test was observed, nor for the test file itself
    assert not pf.should_activate(AgentState(memory={"saw_failing_test": True}), action)
    assert not pf.should_activate(state, ToolCall("write_file", {"path": "tests/test_feature.py"}))


# 2. systematic-debugging
def test_root_cause_guard_blocks_fix_without_investigation():
    pf = RootCauseGuardPF()
    state = AgentState(memory={"last_test_failed": True, "investigated_since_failure": False})
    action = ToolCall("patch", {"path": "src/bug.py"})
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "ROOT CAUSE" in out.text
    # does NOT fire if the agent already investigated
    assert not pf.should_activate(
        AgentState(memory={"last_test_failed": True, "investigated_since_failure": True}), action
    )


# 3. requesting-code-review
def test_precommit_review_fires_when_two_files_edited():
    pf = PreCommitReviewPF()
    history = [
        ToolCall("write_file", {"path": "a.py"}),
        ToolCall("patch", {"path": "b.py"}),
    ]
    state = AgentState(history=history, memory={})
    action = _term("git commit -m 'feat'")
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "verify its own work" in out.text
    # one file only -> no review gate; already-reviewed -> no gate
    one = AgentState(history=[ToolCall("write_file", {"path": "a.py"})], memory={})
    assert not pf.should_activate(one, action)
    assert not pf.should_activate(AgentState(history=history, memory={"review_done": True}), action)


# 4. github-auth
def test_github_auth_guard_fires_before_first_remote_action():
    pf = GithubAuthGuardPF()
    state = AgentState(memory={})
    action = _term("git push origin main")
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "auth" in out.text.lower()
    # not after auth already checked, not for non-github commands
    assert not pf.should_activate(AgentState(memory={"github_auth_checked": True}), action)
    assert not pf.should_activate(state, _term("ls -la"))


# 5. github-pr-workflow
def test_pr_merge_blocked_until_ci_green():
    pf = PRMergeChecksPF()
    state = AgentState(memory={})
    action = _term("gh pr merge 42 --squash")
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "CI" in out.text
    assert not pf.should_activate(AgentState(memory={"pr_checks_green": True}), action)


# 6. plan
def test_plan_mode_blocks_mutation():
    pf = PlanModeGuardPF()
    state = AgentState(memory={"plan_mode": True})
    # editing a real source file is blocked...
    edit = ToolCall("write_file", {"path": "src/app.py"})
    assert pf.should_activate(state, edit)
    out = pf.intervene(state, edit)
    assert isinstance(out, ContextInjection)
    assert "PLAN MODE" in out.text
    # ...but writing the plan markdown is allowed, and mutation outside plan mode is fine
    assert not pf.should_activate(state, ToolCall("write_file", {"path": ".hermes/plans/x.md"}))
    assert not pf.should_activate(AgentState(memory={}), edit)
    assert pf.should_activate(state, _term("git commit -m x"))


# 7. writing-plans
def test_write_plan_before_delegate():
    pf = WritePlanBeforeDelegatePF()
    state = AgentState(memory={})
    action = ToolCall("spawn_subagent", {"task": "build feature X"})
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "plan" in out.text.lower()
    assert not pf.should_activate(AgentState(memory={"plan_written": True}), action)


# 8. arxiv  (MODIFY_ACTION conversion)
def test_arxiv_guard_repairs_bogus_api_key():
    pf = ArxivApiGuardPF()
    state = AgentState(memory={})
    bad = _term('curl "https://export.arxiv.org/api/query?search_query=all:rwkv&api_key=ZZZ"')
    assert pf.should_activate(state, bad)
    out = pf.intervene(state, bad)
    assert isinstance(out, ActionOverride)
    assert "api_key" not in out.action.args["command"]
    assert "export.arxiv.org/api/query" in out.action.args["command"]
    # clean keyless query does not trip the guard
    assert not pf.should_activate(
        state, _term('curl "https://export.arxiv.org/api/query?id_list=2402.03300"')
    )


# 9. himalaya
def test_email_send_requires_review():
    pf = EmailSendReviewPF()
    state = AgentState(memory={})
    action = _term("himalaya message send")
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "irreversible" in out.text.lower()
    assert not pf.should_activate(AgentState(memory={"email_reviewed": True}), action)
    # reading mail is not a send
    assert not pf.should_activate(state, _term("himalaya envelope list"))


# 10. xurl
def test_x_post_requires_confirmation():
    pf = XPostConfirmPF()
    state = AgentState(memory={})
    action = _term('xurl tweet "shipping the harness"')
    assert pf.should_activate(state, action)
    out = pf.intervene(state, action)
    assert isinstance(out, ContextInjection)
    assert "irreversible" in out.text.lower()
    assert not pf.should_activate(AgentState(memory={"x_post_confirmed": True}), action)
    # searching is read-only, not a post
    assert not pf.should_activate(state, _term('xurl search "rwkv"'))


# Integration: all ten are managed by the existing PFRegistry like evolved PFs.
def test_all_ten_are_registry_managed():
    assert len(SKILL_PROGRAM_FUNCTIONS) == 10
    names = {pf.name for pf in SKILL_PROGRAM_FUNCTIONS}
    assert len(names) == 10  # unique
    reg = build_skill_pf_registry()
    # a TDD-triggering action flows through the registry to a structured record
    out = reg.apply(
        AgentState(memory={}), ToolCall("write_file", {"path": "src/x.py"})
    )
    assert isinstance(out, PFExecution)
    assert out.pf_name == "skillpf_tdd_red_before_green"
    assert isinstance(out.intervention, ContextInjection)
    # every PF advertises which real skill it was converted from
    for pf in SKILL_PROGRAM_FUNCTIONS:
        assert getattr(pf, "SKILL_SOURCE", "").count("/") == 1
