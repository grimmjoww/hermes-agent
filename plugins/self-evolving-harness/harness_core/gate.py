"""HASP admission gate — agentic-signal scorer + conjunctive two-gate.

Faithful to HASP (arXiv 2605.17734):
  * Sec 3.2 — the four-signal vector z_t = (t_t, m_t, q_t, o_t) and aggregation
    A_t = lambda_t*t + lambda_m*m + lambda_q*q + lambda_o*o with the PAPER
    weights (lambda_t, lambda_m, lambda_q, lambda_o) = (0.15, 0.10, 0.25, 0.50).
    Components: t_t = intervention TIMING, m_t = intervention MODE (NOT memory),
    q_t = correctness/quality, o_t = outcome.
  * Sec 3.3 — admission is CONJUNCTIVE: a candidate c is accepted iff
    Q_exec(c) >= eta_exec AND Q_teach(c) >= eta_teach. Q_exec checks syntax,
    interface validity, mock execution, legal return types. Q_teach (teacher
    review) evaluates: captures a reusable failure pattern, fires under
    appropriate conditions, proposes a useful repair.
  * Sec 3.1 — the intervention operator Gamma: (a~_t, c_t, kappa_t) =
    Gamma(s_t, a_t^orig, R(s_t)) composes the activated PF set into one
    (corrected action, corrective context, metadata) tuple.

PROVENANCE / HONESTY:
  The DEFAULT_LAMBDAS weights ARE the paper's published values (Sec 3.2).
  The numeric THRESHOLDS in GateConfig (0.30 / 0.60 / 0.42 / 0.75 / 0.60) are
  this HARNESS's operating points — the paper specifies the gate STRUCTURE
  (eta_exec / eta_teach exist) but gives NO numeric values. They live in
  GateConfig with provenance docstrings and must never be cited as
  HASP-published constants. The REVISE band is a harness EXTENSION (not in the
  paper): a near-miss PF is routed back to the Refiner for one repair pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from harness_core.program_function import (
    ActionOverride,
    AgentState,
    ContextInjection,
    Intervention,
)
from harness_core.layers.h4_trajectory import ToolCall


# --- A_t agentic signal (PAPER values, Sec 3.2) -------------------------------

@dataclass(frozen=True)
class Lambdas:
    """The four aggregation weights. PAPER values (HASP Sec 3.2)."""

    t: float = 0.15  # intervention TIMING
    m: float = 0.10  # intervention MODE  (paper's m_t is MODE, not memory)
    q: float = 0.25  # correctness / quality
    o: float = 0.50  # outcome

    def __post_init__(self) -> None:
        total = self.t + self.m + self.q + self.o
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Lambdas must sum to 1.0, got {total}")

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.t, self.m, self.q, self.o)


DEFAULT_LAMBDAS = Lambdas()


@dataclass(frozen=True)
class AgenticSignal:
    """z_t = (t, m, q, o), each in [0, 1] (HASP Sec 3.2).

    t = intervention TIMING, m = intervention MODE, q = correctness/quality,
    o = outcome. NOTE: m is MODE, NOT memory (common mislabel).
    """

    t: float
    m: float
    q: float
    o: float


def agentic_signal(z: AgenticSignal, weights: Lambdas = DEFAULT_LAMBDAS) -> float:
    """A_t = 0.15*t + 0.10*m + 0.25*q + 0.50*o (HASP Sec 3.2 paper weights)."""
    return weights.t * z.t + weights.m * z.m + weights.q * z.q + weights.o * z.o


# --- GateConfig: thresholds (HARNESS operating points, NOT paper constants) ---

@dataclass(frozen=True)
class GateConfig:
    """Admission/grouping thresholds.

    Every numeric field below is a harness operating point, NOT a HASP-published
    constant (the paper specifies gate STRUCTURE only — eta_exec/eta_teach exist
    but are not numerically specified). q_skill_accept (0.60) intentionally
    equals revise_high (0.60) so the bands are contiguous and non-overlapping:
    revise = [0.42, 0.60), accept = [0.60, 1.0].
    """

    q_exec_reject: float = 0.30   # harness operating point, not a HASP-published value
    q_skill_accept: float = 0.60  # harness operating point, not a HASP-published value
    revise_low: float = 0.42      # harness operating point, not a HASP-published value
    revise_high: float = 0.60     # harness operating point, not a HASP-published value
    group_new: float = 0.75       # harness operating point, not a HASP-published value
    group_same: float = 0.60      # harness operating point, not a HASP-published value


DEFAULT_GATE_CONFIG = GateConfig()


# --- Q_exec / Q_teach scorers (paper criteria) --------------------------------

def Q_exec(candidate_pf) -> float:
    """Validity score in [0, 1] from HASP's four Q_exec checks (Sec 3.3):
    (1) interface validity — exposes should_activate + intervene;
    (2) mock execution — should_activate on a probe state does not raise;
    (3) mock execution — intervene on a probe state does not raise;
    (4) legal return type — intervene returns ActionOverride|ContextInjection.

    The legal-return-type check (4) is DECISIVE: a PF that returns an illegal
    type is not executable and is capped below the hard-reject floor, regardless
    of how many other checks pass. A non-runnable description string scores 0.0.
    Weights: interface 0.20, activate-runs 0.20, intervene-runs 0.20, and the
    legal-return check gates the result up to 1.0 (it is the conjunctive
    executability requirement, not just another additive quarter).
    """
    has_activate = callable(getattr(candidate_pf, "should_activate", None))
    has_intervene = callable(getattr(candidate_pf, "intervene", None))
    if not (has_activate and has_intervene):
        return 0.0
    score = 0.20  # interface validity
    probe_state = AgentState(history=[], memory={})
    probe_action = ToolCall("__probe__", {})
    try:
        candidate_pf.should_activate(probe_state, probe_action)
        score += 0.20  # mock execution: should_activate does not raise
    except Exception:
        return score
    try:
        result = candidate_pf.intervene(probe_state, probe_action)
        score += 0.20  # mock execution: intervene does not raise
    except Exception:
        return score
    if isinstance(result, (ActionOverride, ContextInjection)):
        return 1.0  # legal return type: fully executable
    # Illegal return type — not executable. Cap below the hard-reject floor
    # so the gate's q_exec_reject (0.30) rejects it on the executability check.
    return 0.25


def Q_teach(candidate_pf, teacher: Callable[[object], float]) -> float:
    """Teacher-rubric score in [0, 1] over HASP's three Q_teach criteria (Sec 3.3):
    captures a reusable failure pattern, fires under appropriate conditions,
    proposes a useful repair. Pluggable: `teacher(candidate_pf) -> float`.
    """
    return teacher(candidate_pf)


# --- Two-gate admission (CONJUNCTIVE, HASP Sec 3.3) ---------------------------

class GateDecision(Enum):
    REJECT = "reject"
    REVISE = "revise"   # harness extension: route near-miss back to Refiner
    ACCEPT = "accept"


def admit(
    q_exec: float,
    q_skill: float,
    cfg: GateConfig = DEFAULT_GATE_CONFIG,
) -> GateDecision:
    """Conjunctive two-gate admission (HASP Sec 3.3).

    1. HARD REJECT if q_exec < cfg.q_exec_reject (Q_exec is the first conjunct;
       a failure short-circuits regardless of q_skill — paper: accepted iff BOTH
       gates pass).
    2. Of candidates clearing Q_exec, ACCEPT if q_skill >= cfg.q_skill_accept.
    3. REVISE (harness extension) if cfg.revise_low <= q_skill < cfg.revise_high.
    4. REJECT if q_skill < cfg.revise_low.
    """
    if q_exec < cfg.q_exec_reject:
        return GateDecision.REJECT
    if q_skill >= cfg.q_skill_accept:
        return GateDecision.ACCEPT
    if q_skill >= cfg.revise_low:
        return GateDecision.REVISE
    return GateDecision.REJECT


# --- Library grouping + teacher-select ----------------------------------------

class GroupKind(Enum):
    NEW_GROUP = "new_group"
    SAME_GROUP = "same_group"
    AMBIGUOUS = "ambiguous"  # band [group_same, group_new): defer to teacher-select


@dataclass
class GroupDecision:
    kind: GroupKind
    best_group: object | None = None
    similarity: float = 0.0


def assign_group(
    max_similarity: float,
    best_group: object | None = None,
    cfg: GateConfig = DEFAULT_GATE_CONFIG,
) -> GroupDecision:
    """Assign a candidate to an existing group or a new one (harness thresholds).

    sim < group_new (0.75) AND sim < group_same (0.60) -> NEW_GROUP.
    sim >= group_new (0.75) -> SAME_GROUP (clearly belongs).
    group_same (0.60) <= sim < group_new (0.75) -> AMBIGUOUS -> teacher-select.
    """
    if max_similarity < cfg.group_same:
        return GroupDecision(GroupKind.NEW_GROUP, None, max_similarity)
    if max_similarity >= cfg.group_new:
        return GroupDecision(GroupKind.SAME_GROUP, best_group, max_similarity)
    return GroupDecision(GroupKind.AMBIGUOUS, best_group, max_similarity)


def teacher_select(candidates: list, signal_of, q_teach_of=None) -> object | None:
    """Pick the representative/teacher PF of a group: highest A_t (agentic
    signal); ties broken by higher Q_teach, then lexically by name. Deterministic.

    `signal_of(pf) -> float` returns A_t; `q_teach_of(pf) -> float` optional.
    """
    if not candidates:
        return None
    if q_teach_of is None:
        q_teach_of = lambda _pf: 0.0
    return max(
        candidates,
        key=lambda pf: (signal_of(pf), q_teach_of(pf), _neg_name(pf)),
    )


def _neg_name(pf) -> str:
    # max() wants the lexically-SMALLEST name to win ties; invert ordering by
    # selecting on the name and relying on the two prior keys, then break with
    # a stable lexical tiebreak (smaller name preferred).
    name = getattr(pf, "name", "")
    # Return a value such that a smaller name yields a LARGER sort key.
    return _LexInvert(name)


@dataclass(frozen=True)
class _LexInvert:
    name: str

    def __lt__(self, other: "_LexInvert") -> bool:
        # invert: smaller name should be "greater" for max()
        return self.name > other.name

    def __eq__(self, other) -> bool:  # type: ignore[override]
        return isinstance(other, _LexInvert) and self.name == other.name


# --- Gamma multi-PF composition (HASP Sec 3.1) --------------------------------

@dataclass
class Composition:
    """Gamma output: (a~_t, c_t, kappa_t) = (action_out, context_out, meta)."""

    action_out: ToolCall | None
    context_out: str
    meta: list  # kappa_t: list of contributing pf_name+layer


def compose(
    activated_pfs: list,
    state: AgentState,
    action: ToolCall,
    signal_of=None,
) -> Composition:
    """Compose the activated PF set into one intervention tuple (HASP Gamma).

    Rule: ActionOverride dominates ContextInjection for a~_t (an action
    correction wins). If multiple ActionOverrides activate, the teacher PF
    (highest A_t) wins a~_t. All ContextInjections concatenate (dedup, stable
    order) into c_t. kappa_t lists contributing pf name+layer.

    Single-PF degenerate case matches PFRegistry.apply first-wins behavior.
    """
    if signal_of is None:
        signal_of = lambda _pf: 0.0

    action_out: ToolCall | None = None
    override_owner = None
    context_parts: list[str] = []
    meta: list = []

    for pf in activated_pfs:
        intervention = pf.intervene(state, action)
        meta.append({"pf_name": getattr(pf, "name", ""), "layer": getattr(pf, "layer", "")})
        if isinstance(intervention, ActionOverride):
            if override_owner is None or signal_of(pf) > signal_of(override_owner):
                action_out = intervention.action
                override_owner = pf
        elif isinstance(intervention, ContextInjection):
            if intervention.text not in context_parts:
                context_parts.append(intervention.text)

    return Composition(
        action_out=action_out,
        context_out="\n".join(context_parts),
        meta=meta,
    )
