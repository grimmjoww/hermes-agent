"""Continual-Harness Refiner — the GATE-FREE proposer.

Faithful to Continual-Harness (arXiv 2605.09998):
  * Scheduler — "every F steps after a warm-up of W steps, a Refiner reads the
    recent trajectory window for failure signatures and emits per-component
    edits." W and F are NOT in the paper main text (Appendix D.1 only gives the
    co-learning K=256), so they MUST be config-driven, never hardcoded.
  * 4-pass CRUD, one pass per component, paper-verbatim operations:
      (i)   prompt p   — rewrites the prompt p
      (ii)  sub-agents G — creates entries for repeated multi-step patterns,
            edits existing entries, deletes entries not invoked productively
      (iii) skills K    — codifies skills from successful sequences, repairs
            executable code that raised exceptions, deletes stale
      (iv)  memory M    — adds entries to fill gaps, updates stale entries,
            demotes importance for areas the agent moved past
    Passes run in fixed order p, G, K, M.
  * Reset-free monotonic accumulation — H_{t+1} = H_t (+) Delta, applied
    in-place, non-destructive; "failure signatures observed earlier remain
    available to all subsequent refinement passes" -> a monotonic ledger.
  * Failure signatures over the window tau_{t-F:t}: navigation loops, tool-call
    failures, stalled objectives, missed exploration opportunities.

GATE-FREE: the paper describes NO verifier/rollback — edits enter context on the
next step unconditionally (H_{t+1} = H_t (+) Delta). The regression-gate +
rollback (evolution_loop.try_admit) is the HASP COMPOSITION LAYER, NOT CH. This
module supports BOTH a gate-free mode (CH-faithful, default) and a HASP-gated
mode (composition layer); the gate-free path never references the scorer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from harness_core.evolver import EvolvedPF
from harness_core.layers.h4_trajectory import ToolCall, detect_repeat_loop


# --- scheduler (config-driven; W/F NOT from paper) ---------------------------

@dataclass(frozen=True)
class RefinerSchedule:
    """Refine every F steps after a warm-up of W steps (Continual-Harness).

    W (warmup) and F (frequency) are operator-tunable config — NOT paper values.
    The paper's main text gives neither; only Appendix D.1's co-learning K=256.
    """

    warmup_W: int
    freq_F: int

    def __post_init__(self) -> None:
        if self.warmup_W < 0 or self.freq_F < 1:
            raise ValueError("warmup_W must be >= 0 and freq_F >= 1")

    def should_refine(self, step: int) -> bool:
        """True iff step >= W and (step - W) % F == 0 (fires at W, W+F, W+2F)."""
        if step < self.warmup_W:
            return False
        return (step - self.warmup_W) % self.freq_F == 0


# --- failure signatures (4 classes over the window) --------------------------

class SignatureKind(str, Enum):
    NAVIGATION_LOOP = "navigation_loop"
    TOOL_CALL_FAILURE = "tool_call_failure"
    STALLED_OBJECTIVE = "stalled_objective"
    MISSED_EXPLORATION = "missed_exploration"


@dataclass(frozen=True)
class FailureSignature:
    kind: SignatureKind
    evidence: str


@dataclass
class WindowStep:
    """One step in the trajectory window tau_{t-F:t}."""

    call: ToolCall
    outcome: str = "ok"        # "ok" | "error" | "exception"
    objective_score: float = 0.0
    success: bool = False      # was this a productive/successful step


@dataclass
class TrajectoryWindow:
    """The last F steps of trajectory (tau_{t-F:t}) the Refiner reads."""

    steps: list[WindowStep] = field(default_factory=list)
    available_tools: set[str] = field(default_factory=set)
    required_tools: set[str] = field(default_factory=set)
    loop_threshold: int = 3
    stall_min_actions: int = 3


def detect_signatures(window: TrajectoryWindow) -> list[FailureSignature]:
    """Detect the 4 Continual-Harness failure-signature classes over the window.

    Detection logic is NOT formalized in the paper; these are minimal heuristics
    for the paper's named classes.
    """
    sigs: list[FailureSignature] = []
    calls = [s.call for s in window.steps]

    # (1) navigation_loop — reuse detect_repeat_loop (identical trailing run).
    if detect_repeat_loop(calls, threshold=window.loop_threshold) is not None:
        sigs.append(FailureSignature(
            SignatureKind.NAVIGATION_LOOP,
            evidence=f"{calls[-1].name} repeated {window.loop_threshold}x",
        ))

    # (2) tool_call_failure — any step whose outcome is error/exception.
    for s in window.steps:
        if s.outcome in ("error", "exception"):
            sigs.append(FailureSignature(
                SignatureKind.TOOL_CALL_FAILURE,
                evidence=f"{s.call.name} -> {s.outcome}",
            ))
            break

    # (3) stalled_objective — score unchanged across the window despite >= N actions.
    if len(window.steps) >= window.stall_min_actions:
        scores = {s.objective_score for s in window.steps}
        if len(scores) == 1:
            sigs.append(FailureSignature(
                SignatureKind.STALLED_OBJECTIVE,
                evidence=f"objective flat at {next(iter(scores))} over {len(window.steps)} actions",
            ))

    # (4) missed_exploration — a required/available tool never invoked in window.
    invoked = {c.name for c in calls}
    never = (window.required_tools | window.available_tools) - invoked
    if window.required_tools and (window.required_tools - invoked):
        missed = sorted(window.required_tools - invoked)
        sigs.append(FailureSignature(
            SignatureKind.MISSED_EXPLORATION,
            evidence=f"required tool(s) never invoked: {', '.join(missed)}",
        ))
    elif never and window.required_tools == set() and window.available_tools:
        # only available (not strictly required) -> still a missed-exploration hint
        missed = sorted(never)
        sigs.append(FailureSignature(
            SignatureKind.MISSED_EXPLORATION,
            evidence=f"available tool(s) never invoked: {', '.join(missed)}",
        ))

    return sigs


# --- 4-component Delta (CRUD ops) --------------------------------------------

class OpKind(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    DEMOTE = "demote"  # memory: demote importance (a soft delete)
    REWRITE = "rewrite"  # prompt: rewrite-only


@dataclass
class CrudOp:
    op: OpKind
    target: str          # entity name / id the op applies to
    payload: str = ""    # new content / guidance
    pf: Optional[object] = None  # runnable PF for runtime-behavior edits


@dataclass
class Delta:
    """Delta = (delta_p, delta_G, delta_K, delta_M) — per-component edit lists."""

    delta_p: list[CrudOp] = field(default_factory=list)  # prompt
    delta_G: list[CrudOp] = field(default_factory=list)  # sub-agents
    delta_K: list[CrudOp] = field(default_factory=list)  # skills
    delta_M: list[CrudOp] = field(default_factory=list)  # memory

    def all_ops(self) -> list[CrudOp]:
        return self.delta_p + self.delta_G + self.delta_K + self.delta_M

    def runtime_pfs(self) -> list[object]:
        return [op.pf for op in self.all_ops() if op.pf is not None]


# --- HarnessState (reset-free, with monotonic signature ledger) --------------

@dataclass
class HarnessState:
    """H_t — accumulates edits in-place across refines (reset-free).

    The signature ledger only GROWS: signatures from earlier windows remain
    visible to later passes (Continual-Harness monotonic accumulation).
    """

    prompt: str = ""
    subagents: dict = field(default_factory=dict)
    skills: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    signature_ledger: list = field(default_factory=list)  # monotonic
    active_pfs: list = field(default_factory=list)


def apply_delta(H: HarnessState, delta: Delta) -> HarnessState:
    """H_{t+1} = H_t (+) Delta — in-place, non-destructive accumulation.

    CREATE/REWRITE = merge/replace; UPDATE = replace; DELETE/DEMOTE = mark.
    The SAME HarnessState object is returned (never reset per episode).
    """
    # prompt: rewrite-only
    for op in delta.delta_p:
        if op.op in (OpKind.REWRITE, OpKind.CREATE, OpKind.UPDATE):
            H.prompt = op.payload

    for store, ops in ((H.subagents, delta.delta_G), (H.skills, delta.delta_K), (H.memory, delta.delta_M)):
        for op in ops:
            if op.op in (OpKind.CREATE, OpKind.UPDATE):
                store[op.target] = op.payload
            elif op.op == OpKind.DELETE:
                store.pop(op.target, None)
            elif op.op == OpKind.DEMOTE:
                if op.target in store:
                    store[op.target] = f"[demoted] {store[op.target]}"

    for pf in delta.runtime_pfs():
        H.active_pfs.append(pf)

    return H


# --- the Refiner -------------------------------------------------------------

class ApplyMode(str, Enum):
    GATE_FREE = "gate_free"      # Continual-Harness faithful (default)
    HASP_GATED = "hasp_gated"    # composition layer routes PFs through try_admit


class Refiner:
    """Pure proposer: (window, H) -> Delta, then apply (mode-dependent).

    GATE_FREE mode applies Delta unconditionally (CH-faithful); it has zero
    reference to the scorer/snapshot/restore. HASP_GATED mode routes each
    emitted runtime PF through the HASP gate (try_admit) before it joins the
    active library.
    """

    def __init__(self, schedule: RefinerSchedule, mode: ApplyMode = ApplyMode.GATE_FREE) -> None:
        self.schedule = schedule
        self.mode = mode

    def refine(self, window: TrajectoryWindow, H: HarnessState) -> Delta:
        """Read the window for failure signatures, emit per-component edits.

        Records detected signatures into H's monotonic ledger BEFORE building the
        passes, so signatures from earlier refines remain visible.
        """
        sigs = detect_signatures(window)
        for sig in sigs:
            H.signature_ledger.append(sig)

        delta = Delta()
        self._pass_prompt(delta, window, H, sigs)
        self._pass_subagents(delta, window, H, sigs)
        self._pass_skills(delta, window, H, sigs)
        self._pass_memory(delta, window, H, sigs)
        return delta

    # PASS p (i): rewrite-only
    def _pass_prompt(self, delta, window, H, sigs) -> None:
        if sigs:
            sig_names = ", ".join(s.kind.value for s in sigs)
            delta.delta_p.append(CrudOp(
                OpKind.REWRITE, target="prompt",
                payload=f"{H.prompt}\n[refined: guard against {sig_names}]".strip(),
            ))

    # PASS G (ii): CREATE repeated patterns, UPDATE for failures, DELETE unproductive
    def _pass_subagents(self, delta, window, H, sigs) -> None:
        loop = next((s for s in sigs if s.kind == SignatureKind.NAVIGATION_LOOP), None)
        if loop is not None:
            tool = window.steps[-1].call.name if window.steps else "?"
            delta.delta_G.append(CrudOp(OpKind.CREATE, target=f"subagent_{tool}",
                                        payload="multi-step pattern captured"))
        for s in sigs:
            if s.kind == SignatureKind.TOOL_CALL_FAILURE:
                delta.delta_G.append(CrudOp(OpKind.UPDATE, target="error_handler",
                                            payload=s.evidence))
        # DELETE sub-agents not invoked productively
        invoked = {st.call.name for st in window.steps if st.success}
        for name in list(H.subagents):
            base = name.replace("subagent_", "")
            if base not in invoked:
                delta.delta_G.append(CrudOp(OpKind.DELETE, target=name))

    # PASS K (iii): codify successes, repair exception-raising code
    def _pass_skills(self, delta, window, H, sigs) -> None:
        has_loop = any(s.kind == SignatureKind.NAVIGATION_LOOP for s in sigs)
        successes = [st for st in window.steps if st.success]
        if successes:
            # Codify the successful sequence as a skill. If the window ALSO showed
            # a navigation loop, attach the runnable loop-breaking PF here so the
            # codified skill carries its guardrail.
            seq = "->".join(st.call.name for st in successes)
            pf = self._loop_pf(window) if has_loop else None
            delta.delta_K.append(CrudOp(OpKind.CREATE, target=f"skill_{seq}",
                                        payload=f"codified from: {seq}", pf=pf))
        elif has_loop:
            # A navigation loop is a runtime failure signature on its own — emit
            # the runnable loop-breaking PF even when there is no successful
            # sequence to codify (CH: edits enter unconditionally; the PF is the
            # K-component runtime edit guarding against the loop).
            tool = window.steps[-1].call.name if window.steps else "tool"
            delta.delta_K.append(CrudOp(OpKind.CREATE, target=f"loop_guard_{tool}",
                                        payload="loop-breaking guardrail",
                                        pf=self._loop_pf(window)))
        for st in window.steps:
            if st.outcome == "exception":
                delta.delta_K.append(CrudOp(OpKind.UPDATE, target=f"repair_{st.call.name}",
                                            payload="repaired code that raised"))

    # PASS M (iv): fill gaps, update stale, demote moved-past areas
    def _pass_memory(self, delta, window, H, sigs) -> None:
        if any(s.kind == SignatureKind.MISSED_EXPLORATION for s in sigs):
            delta.delta_M.append(CrudOp(OpKind.CREATE, target="exploration_gap",
                                        payload="record unexplored tool/area"))
        for s in sigs:
            if s.kind == SignatureKind.STALLED_OBJECTIVE:
                delta.delta_M.append(CrudOp(OpKind.UPDATE, target="objective_status",
                                            payload="objective stalled — update plan"))
        # DEMOTE memory for areas the agent has moved past (present in H, not in window)
        window_tools = {st.call.name for st in window.steps}
        for area in list(H.memory):
            if area not in window_tools and not area.startswith("[demoted]"):
                delta.delta_M.append(CrudOp(OpKind.DEMOTE, target=area))

    def _loop_pf(self, window: TrajectoryWindow) -> EvolvedPF:
        tool = window.steps[-1].call.name if window.steps else "tool"
        return EvolvedPF(layer="H4", target_tool=tool, kind="loop",
                         description="break navigation loop", threshold=window.loop_threshold)

    def apply(
        self,
        H: HarnessState,
        delta: Delta,
        scorer: Optional[Callable[[list], float]] = None,
    ) -> HarnessState:
        """Apply Delta to H according to mode.

        GATE_FREE: unconditional in-place accumulation (CH), scorer ignored.
        HASP_GATED: route runtime PFs through try_admit (regression gate).
        """
        if self.mode == ApplyMode.GATE_FREE:
            return apply_delta(H, delta)
        # HASP_GATED: import here so the gate-free path never imports the gate.
        from harness_core.evolution_loop import SkillLibrary, try_admit
        if scorer is None:
            raise ValueError("HASP_GATED mode requires a scorer")
        # apply non-runtime edits in-place (still CH accumulation for p/G/K/M
        # metadata), but gate the runtime PFs.
        non_runtime = Delta(
            delta_p=delta.delta_p,
            delta_G=[o for o in delta.delta_G if o.pf is None],
            delta_K=[o for o in delta.delta_K if o.pf is None],
            delta_M=delta.delta_M,
        )
        apply_delta(H, non_runtime)
        lib = SkillLibrary()
        lib.active = list(H.active_pfs)
        for pf in delta.runtime_pfs():
            try_admit(lib, pf, scorer)
        H.active_pfs = list(lib.active)
        return H


# --- Phase-2 co-learning SEAM (reward-windowing ONLY; no GRPO/GPU) -----------
#
# SEAM CONTRACT: the SAGE/co-learning online trainer (Appendix D.1: K=256
# steps/iteration, pairwise reward R in [0,1], teacher relabel, soft-SFT) is a
# Phase-2 GPU swap. Phase-1 implements ONLY the reward-WINDOWING boundary logic
# (which steps fall in which co-learning iteration window) as a pure function.
# NO GRPO, NO GPU, NO training is pulled forward.

def reward_window_index(step: int, K: int) -> int:
    """Map a step index to its co-learning iteration window of size K (config).

    Phase-1 boundary logic only. Window i covers steps [i*K, (i+1)*K).
    """
    if K < 1:
        raise ValueError("K must be >= 1")
    return step // K


def reward_window_bounds(window_index: int, K: int) -> tuple[int, int]:
    """Return the [start, end) step bounds of co-learning window `window_index`."""
    if K < 1:
        raise ValueError("K must be >= 1")
    start = window_index * K
    return (start, start + K)
