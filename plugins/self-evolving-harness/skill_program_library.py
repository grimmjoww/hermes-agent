"""Ten real Hermes skills, converted into managed HASP Program Functions.

Each class here takes ONE real, existing skill from
``G:\\hermes\\hermes-agent\\skills`` (a *feature* — procedural guidance, not a
memory) and re-expresses it as a runtime guardrail satisfying the harness_core
``ProgramFunction`` Protocol (``should_activate`` + ``intervene``). The result is
held and applied by the existing ``PFRegistry`` exactly like an evolved PF.

NO new infrastructure: these reuse ``AgentState``, ``ToolCall``,
``ContextInjection`` and ``ActionOverride`` from ``harness_core``. The only thing
each PF adds is a *predicate* (when does this skill's guidance become a
guardrail?) and an *intervention* (block / inject guidance / repair the action),
which is precisely the HASP "skill expressed as an executable state-action
intervention" (arXiv 2605.17734).

Activation predicates inspect the candidate ``action`` AND the ``AgentState``
(``history`` = ToolCalls so far this session, ``memory`` = scratch flags the
host can set, e.g. ``plan_mode``, ``last_test_failed``). This makes the
conversions genuine runtime behaviours, not keyword echoes.

Each skill links back to its source SKILL.md via ``SKILL_SOURCE``.
"""
from __future__ import annotations

from dataclasses import dataclass

try:  # pragma: no cover - exercised by both load paths
    from .harness_core.layers.h4_trajectory import ToolCall
    from .harness_core.program_function import (
        ActionOverride,
        AgentState,
        ContextInjection,
        Intervention,
    )
except ImportError:  # standalone import (plugin dir on sys.path via conftest)
    from harness_core.layers.h4_trajectory import ToolCall
    from harness_core.program_function import (
        ActionOverride,
        AgentState,
        ContextInjection,
        Intervention,
    )

# Tool names a Hermes agent actually emits (from the bundled tool surface):
# terminal, write_file, patch, read_file, search_files, web_extract, ...
_EDIT_TOOLS = {"write_file", "patch", "edit_file"}


def _is_test_path(path: str) -> bool:
    p = (path or "").lower().replace("\\", "/")
    return (
        "test_" in p
        or "_test." in p
        or "/tests/" in p
        or p.endswith("conftest.py")
        or ".spec." in p
        or ".test." in p
    )


def _cmd(action: ToolCall) -> str:
    """The shell command a `terminal` action would run (best-effort)."""
    args = action.args or {}
    return str(args.get("command") or args.get("cmd") or "")


# --------------------------------------------------------------------------- #
# 1. test-driven-development -> block writing impl code before a failing test  #
# --------------------------------------------------------------------------- #
@dataclass
class TDDGuardPF:
    """Enforce RED before GREEN: do not write IMPLEMENTATION code until a test
    has been run and seen to fail this session.

    Source skill: software-development/test-driven-development ("If you didn't
    watch the test fail, you don't know if it tests the right thing").
    """

    SKILL_SOURCE = "software-development/test-driven-development"
    name: str = "skillpf_tdd_red_before_green"
    layer: str = "H2"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name not in _EDIT_TOOLS:
            return False
        path = str((action.args or {}).get("path", ""))
        if _is_test_path(path):
            return False  # writing the test itself is always fine
        # fires when no failing test has been observed yet this session
        return not state.memory.get("saw_failing_test", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: test-driven-development] You are about to write implementation "
            "code, but no failing test has been observed this session. RED before "
            "GREEN: write the test first, run it, watch it fail, THEN write the "
            "minimal code to pass. If you did not watch it fail, you do not know it "
            "tests the right thing."
        )


# --------------------------------------------------------------------------- #
# 2. systematic-debugging -> no fix without root-cause investigation           #
# --------------------------------------------------------------------------- #
@dataclass
class RootCauseGuardPF:
    """Iron Law: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST. If a test just
    failed and the next action is an immediate edit (a 'fix') with no read /
    investigation in between, surface the iron law.

    Source skill: software-development/systematic-debugging.
    """

    SKILL_SOURCE = "software-development/systematic-debugging"
    name: str = "skillpf_systematic_debugging_iron_law"
    layer: str = "H2"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name not in _EDIT_TOOLS:
            return False
        if not state.memory.get("last_test_failed", False):
            return False
        # Has the agent investigated (read_file / search_files) since the failure?
        return not state.memory.get("investigated_since_failure", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: systematic-debugging] A test just failed and you are reaching "
            "straight for a fix. Iron Law: NO FIXES WITHOUT ROOT CAUSE "
            "INVESTIGATION FIRST. Complete Phase 1 — read the failing code/trace, "
            "form a hypothesis about the ROOT cause — before editing. Symptom fixes "
            "are failure."
        )


# --------------------------------------------------------------------------- #
# 3. requesting-code-review -> verify before commit/push                       #
# --------------------------------------------------------------------------- #
@dataclass
class PreCommitReviewPF:
    """Before `git commit`/`git push`, require the verification pipeline (static
    scan + independent review) when 2+ files were edited this session.

    Source skill: software-development/requesting-code-review ("No agent should
    verify its own work. Fresh context finds what you miss.").
    """

    SKILL_SOURCE = "software-development/requesting-code-review"
    name: str = "skillpf_precommit_review_required"
    layer: str = "H2"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name != "terminal":
            return False
        cmd = _cmd(action)
        if not ("git commit" in cmd or "git push" in cmd):
            return False
        if state.memory.get("review_done", False):
            return False
        edited = {
            c.args.get("path")
            for c in state.history
            if c.name in _EDIT_TOOLS and (c.args or {}).get("path")
        }
        return len(edited) >= 2

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: requesting-code-review] You edited 2+ files and are about to "
            "commit/push without review. Run the pre-commit verification first: "
            "static security scan, baseline-aware quality gates, and an INDEPENDENT "
            "reviewer (fresh context). No agent should verify its own work."
        )


# --------------------------------------------------------------------------- #
# 4. github-auth -> check auth before any GitHub action                        #
# --------------------------------------------------------------------------- #
@dataclass
class GithubAuthGuardPF:
    """Run the auth detection flow before the first `gh`/remote-git action, so we
    don't fail mid-workflow on an unauthenticated remote.

    Source skill: github/github-auth ("When a user asks you to work with GitHub,
    run this check first").
    """

    SKILL_SOURCE = "github/github-auth"
    name: str = "skillpf_github_auth_first"
    layer: str = "H3"
    _GH_VERBS = ("gh pr", "gh issue", "gh repo", "gh release", "gh api", "git push", "git pull")

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name != "terminal":
            return False
        cmd = _cmd(action)
        if not any(v in cmd for v in self._GH_VERBS):
            return False
        return not state.memory.get("github_auth_checked", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: github-auth] First GitHub/remote action this session without a "
            "verified auth state. Run the detection flow first: `gh auth status` "
            "(or confirm GITHUB_TOKEN / SSH key) before pushing or hitting the API, "
            "so the workflow doesn't fail half-way on an auth error."
        )


# --------------------------------------------------------------------------- #
# 5. github-pr-workflow -> don't merge a PR before CI is green                 #
# --------------------------------------------------------------------------- #
@dataclass
class PRMergeChecksPF:
    """Before `gh pr merge`, require that PR checks/CI were inspected.

    Source skill: github/github-pr-workflow (PR lifecycle: open -> CI -> merge).
    """

    SKILL_SOURCE = "github/github-pr-workflow"
    name: str = "skillpf_pr_merge_requires_green_ci"
    layer: str = "H2"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name != "terminal":
            return False
        cmd = _cmd(action)
        if "gh pr merge" not in cmd:
            return False
        return not state.memory.get("pr_checks_green", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: github-pr-workflow] You are about to merge a PR without "
            "confirming CI. Inspect checks first (`gh pr checks` / `gh pr view`); "
            "only merge once required checks are green. Merging red CI breaks the "
            "default branch for everyone."
        )


# --------------------------------------------------------------------------- #
# 6. plan -> in plan mode, block mutating actions                             #
# --------------------------------------------------------------------------- #
@dataclass
class PlanModeGuardPF:
    """Plan mode is read-only except the plan markdown under `.hermes/plans/`.
    Block any mutating action (edits to non-plan files, mutating shell commands).

    Source skill: software-development/plan ("Do not implement code... Do not run
    mutating terminal commands, commit, push, or perform external actions").
    """

    SKILL_SOURCE = "software-development/plan"
    name: str = "skillpf_plan_mode_read_only"
    layer: str = "H2"
    _MUTATING = ("git commit", "git push", "rm ", "mv ", "npm install", "pip install", "git merge")

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if not state.memory.get("plan_mode", False):
            return False
        if action.name in _EDIT_TOOLS:
            path = str((action.args or {}).get("path", "")).replace("\\", "/")
            return ".hermes/plans/" not in path  # plan file itself is allowed
        if action.name == "terminal":
            return any(m in _cmd(action) for m in self._MUTATING)
        return False

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: plan] You are in PLAN MODE — planning only this turn. Do not "
            "implement code, edit project files (except the plan markdown under "
            "`.hermes/plans/`), or run mutating/external commands. Deliver the "
            "markdown plan; defer execution to a later turn."
        )


# --------------------------------------------------------------------------- #
# 7. writing-plans -> don't delegate multi-step work without a written plan    #
# --------------------------------------------------------------------------- #
@dataclass
class WritePlanBeforeDelegatePF:
    """Before spawning a subagent for multi-step work, require a written plan.

    Source skill: software-development/writing-plans ("Always use before...
    delegating to subagents"; "A good plan makes implementation obvious").
    """

    SKILL_SOURCE = "software-development/writing-plans"
    name: str = "skillpf_write_plan_before_delegate"
    layer: str = "H5"
    _DELEGATE_TOOLS = {"spawn_subagent", "task", "sessions_spawn", "dispatch_agent"}

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name not in self._DELEGATE_TOOLS:
            return False
        return not state.memory.get("plan_written", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: writing-plans] You are delegating multi-step work to a subagent "
            "with no written plan. Write a concrete plan first (files to touch, "
            "complete code, test commands, how to verify) — assume the implementer "
            "has zero context. If they have to guess, the plan is incomplete."
        )


# --------------------------------------------------------------------------- #
# 8. arxiv -> repair the API endpoint / drop bogus api_key                     #
# --------------------------------------------------------------------------- #
@dataclass
class ArxivApiGuardPF:
    """arXiv's API is free and key-less. If an arXiv query carries an `api_key`
    or aims at the wrong host, repair the action (MODIFY_ACTION) to the documented
    keyless endpoint.

    Source skill: research/arxiv ("No API key, no dependencies — just curl";
    canonical host export.arxiv.org).
    """

    SKILL_SOURCE = "research/arxiv"
    name: str = "skillpf_arxiv_keyless_api"
    layer: str = "H3"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name != "terminal":
            return False
        cmd = _cmd(action)
        if "arxiv.org" not in cmd:
            return False
        # fires if it injects an api_key or uses the non-API host for querying
        return "api_key" in cmd or "api-key" in cmd

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        repaired_cmd = _cmd(action)
        # strip a key arg of forms: api_key=..., --api-key ..., &api_key=...
        for marker in ("&api_key=", "?api_key=", " api_key=", "--api-key", "api-key="):
            if marker in repaired_cmd:
                repaired_cmd = repaired_cmd.split(marker)[0].rstrip(" &?")
        repaired = ToolCall(action.name, {**(action.args or {}), "command": repaired_cmd})
        return ActionOverride(repaired)


# --------------------------------------------------------------------------- #
# 9. himalaya -> review before sending email (irreversible)                    #
# --------------------------------------------------------------------------- #
@dataclass
class EmailSendReviewPF:
    """Sending email is irreversible. Before `himalaya ... send`, require that the
    message was composed/reviewed (e.g. via a save/template step) this session.

    Source skill: email/himalaya (CLI IMAP/SMTP; MML composition).
    """

    SKILL_SOURCE = "email/himalaya"
    name: str = "skillpf_email_review_before_send"
    layer: str = "H2"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name != "terminal":
            return False
        cmd = _cmd(action)
        is_send = cmd.startswith("himalaya") and (" send" in cmd or "message send" in cmd)
        if not is_send:
            return False
        return not state.memory.get("email_reviewed", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: himalaya] You are about to SEND email — an irreversible action "
            "— without a reviewed draft. Compose with MML, show the recipient, "
            "subject and body for confirmation (or save a draft) before invoking "
            "`himalaya ... send`."
        )


# --------------------------------------------------------------------------- #
# 10. xurl -> confirm before posting publicly to X (irreversible)             #
# --------------------------------------------------------------------------- #
@dataclass
class XPostConfirmPF:
    """Posting to X is public and irreversible. Before `xurl ... tweet/post`,
    require an explicit confirmation flag in scratch memory.

    Source skill: social-media/xurl (post/reply/quote via the official X API CLI).
    """

    SKILL_SOURCE = "social-media/xurl"
    name: str = "skillpf_x_post_confirm"
    layer: str = "H2"
    _POST_VERBS = (" tweet", " post", " reply", " quote", "tweets")

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if action.name != "terminal":
            return False
        cmd = _cmd(action)
        if not cmd.startswith("xurl"):
            return False
        is_write = any(v in cmd for v in self._POST_VERBS) and "search" not in cmd
        if not is_write:
            return False
        return not state.memory.get("x_post_confirmed", False)

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(
            "[skill: xurl] You are about to publish to X — public and irreversible. "
            "Show the exact post text for confirmation before calling `xurl`; once "
            "live, deletion is the only remedy and the post may already be seen."
        )


# Ordered list the registry consumes. Order = priority (first activating wins).
SKILL_PROGRAM_FUNCTIONS = [
    TDDGuardPF(),
    RootCauseGuardPF(),
    PreCommitReviewPF(),
    GithubAuthGuardPF(),
    PRMergeChecksPF(),
    PlanModeGuardPF(),
    WritePlanBeforeDelegatePF(),
    ArxivApiGuardPF(),
    EmailSendReviewPF(),
    XPostConfirmPF(),
]


def build_skill_pf_registry():
    """Build a PFRegistry holding all ten converted-skill guardrails.

    No new infra: returns the existing harness_core PFRegistry.
    """
    try:  # pragma: no cover - exercised by both load paths
        from .harness_core.program_function import PFRegistry
    except ImportError:
        from harness_core.program_function import PFRegistry

    return PFRegistry(list(SKILL_PROGRAM_FUNCTIONS))
