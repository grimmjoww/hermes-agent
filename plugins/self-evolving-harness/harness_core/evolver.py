"""Evolver — proposes a RUNNABLE Program Function from observed failures.

The decision step of the self-evolution loop: cluster recurring deterministic
failures, take the dominant (tool, kind), and map it to the EARLIEST lifecycle
layer that can catch it.

PAPER-FAITHFULNESS (charter critical path): HASP defines PFs as "executable
guardrails that activate on failure-prone states and modify the next action or
inject corrective context" (arXiv 2605.17734) — contrasted WITH passive advice.
The previous output was a `ProposedRule` DESCRIPTION STRING (passive advice), so
the HASP Q_exec gate had nothing valid to admit. `propose_rule` now returns an
`EvolvedPF`: a single object that is BOTH the metadata record (.layer,
.target_tool, .kind, .name — so persistence + controller.from_rules keep
working) AND a runnable ProgramFunction (should_activate + intervene).

GATE BOUNDARY: propose_rule is the CONTINUAL-HARNESS PROPOSER and is GATE-FREE.
It emits a candidate runnable PF; it does NOT validate Q_exec or roll back. The
Q_exec admission + rollback is HASP's job (`evolution_loop.try_admit`). Do NOT
add a gate here, and do NOT claim CH rolls back.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from harness_core.layers.h4_trajectory import ToolCall, detect_repeat_loop
from harness_core.program_function import (
    ActionOverride,
    AgentState,
    ContextInjection,
    Intervention,
)


@dataclass
class FailureEvent:
    """A single observed failure extracted from a trajectory."""

    tool_name: str
    kind: str  # "loop" | "missing_arg" | "unknown_tool" | "wrong_convention" | ...
    detail: str = ""


# kind -> the earliest lifecycle layer that can deterministically catch it
_KIND_TO_LAYER = {
    "loop": "H4",            # post-execution trajectory monitor
    "missing_arg": "H2",     # pre-execution action gate
    "unknown_tool": "H2",    # pre-execution action gate
    "wrong_convention": "H3",  # episode-init tool-contract calibration
}


@dataclass
class EvolvedPF:
    """A runnable Program Function proposed from observed failures.

    It is BOTH the metadata record (layer / target_tool / kind / name — read by
    persistence and HarnessController.from_rules) AND a runnable PF satisfying
    the program_function.ProgramFunction Protocol (should_activate + intervene).

    Per-kind activation/intervention delegates to existing layer logic; it does
    NOT reimplement detection.
    """

    layer: str
    target_tool: str
    kind: str
    description: str = ""
    name: str = ""
    threshold: int = 3            # loop: trailing-repeat run length
    required_arg: str | None = None  # missing_arg: the arg that must be present

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"evolved_{self.layer.lower()}_{self.target_tool}_{self.kind}"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if self.kind == "loop":
            # H4: fire when this action targets target_tool AND the trailing run
            # of identical calls reaches threshold (reuse detect_repeat_loop).
            if action.name != self.target_tool:
                return False
            calls = list(state.history) + [action]
            return detect_repeat_loop(calls, threshold=self.threshold) is not None
        if self.kind == "missing_arg":
            # H2: fire when target_tool is called without the required arg.
            return action.name == self.target_tool and (
                self.required_arg is not None and self.required_arg not in action.args
            )
        if self.kind == "unknown_tool":
            # H2: fire on the unknown tool name.
            return action.name == self.target_tool
        if self.kind == "wrong_convention":
            # H3 approximation: inject the convention once on first sight of the
            # tool (H3 augments docs at episode init; modeled here per-action as
            # a documented approximation, not overstated fidelity).
            return action.name == self.target_tool
        return False

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        if self.kind == "loop":
            return ContextInjection(
                f"You have repeated `{self.target_tool}` with identical arguments "
                f"{self.threshold} times — this is a loop and is not making progress. "
                f"Stop repeating it; try a different action or re-read the task."
            )
        if self.kind == "missing_arg":
            repair = state.memory.get(self.required_arg) if self.required_arg else None
            if repair is not None:
                fixed = ToolCall(action.name, {**action.args, self.required_arg: repair})
                return ActionOverride(fixed)
            return ContextInjection(
                f"The call to `{self.target_tool}` is missing required argument "
                f"`{self.required_arg}`. Re-issue the call including it."
            )
        if self.kind == "unknown_tool":
            return ContextInjection(
                f"`{self.target_tool}` is not an available tool. Choose a valid "
                f"tool from the available set."
            )
        if self.kind == "wrong_convention":
            return ContextInjection(
                f"Calling convention for `{self.target_tool}`: {self.description}"
            )
        return ContextInjection(self.description)


# Backwards-compatible alias: the proposed object is now a runnable PF, but the
# name `ProposedRule` is still used by persistence (serialize/deserialize) and
# downstream code as the metadata record. EvolvedPF IS the metadata record.
ProposedRule = EvolvedPF


def propose_rule(failures: list[FailureEvent]) -> EvolvedPF | None:
    """Return a runnable EvolvedPF for the most common (tool, kind), or None.

    CONTINUAL-HARNESS proposer: GATE-FREE. Emits a candidate runnable PF; the
    HASP gate (try_admit) performs Q_exec admission separately.
    """
    if not failures:
        return None
    counts = Counter((f.tool_name, f.kind) for f in failures)
    (tool, kind), n = counts.most_common(1)[0]
    layer = _KIND_TO_LAYER.get(kind, "H4")
    detail = next(
        (f.detail for f in failures if f.tool_name == tool and f.kind == kind and f.detail),
        "",
    )
    suffix = f" (e.g. {detail})" if detail else ""
    description = (
        f"Recurring '{kind}' failure on tool '{tool}' ({n} occurrence(s)){suffix}. "
        f"Add a {layer} rule to catch it at the earliest lifecycle point."
    )
    required_arg = detail if kind == "missing_arg" and detail else None
    name = f"evolved_{layer.lower()}_{tool}_{kind}"
    return EvolvedPF(
        layer=layer,
        target_tool=tool,
        kind=kind,
        name=name,
        description=description,
        required_arg=required_arg,
    )
