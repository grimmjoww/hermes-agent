"""HASP Program Functions — skills as executable state-action interventions.

Faithful to HASP (arXiv 2605.17734): a Program Function exposes
``should_activate(state, action)`` and ``intervene(state, action)`` returning
EITHER an ``ActionOverride`` (modify the candidate action) OR a
``ContextInjection`` (inject corrective text). A ``PFRegistry`` retrieves PFs,
evaluates their activation predicates, executes the first valid intervention,
and returns a structured ``PFExecution`` record.

This is the unified abstraction the 4 layers express themselves through, and it
adds the MODIFY_ACTION capability the earlier block-only design lacked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Union

from harness_core.layers.h4_trajectory import ToolCall


@dataclass
class ActionOverride:
    """MODIFY_ACTION: replace the candidate action with a corrected one."""

    action: ToolCall


@dataclass
class ContextInjection:
    """INJECT_CONTEXT: surface corrective guidance to the agent."""

    text: str


Intervention = Union[ActionOverride, ContextInjection]


@dataclass
class AgentState:
    """Runtime state a PF may inspect: trajectory so far + scratch memory."""

    history: list = field(default_factory=list)
    memory: dict = field(default_factory=dict)


class ProgramFunction(Protocol):
    name: str
    layer: str

    def should_activate(self, state: AgentState, action: ToolCall) -> bool: ...

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention: ...


@dataclass
class PFExecution:
    """Structured record of a PF firing (HASP: original action + intervention + skill + layer)."""

    pf_name: str
    layer: str
    original_action: ToolCall
    intervention: Intervention


class PFRegistry:
    """Holds PFs; applies the first whose activation predicate fires."""

    def __init__(self, pfs: list) -> None:
        self.pfs = list(pfs)

    def apply(self, state: AgentState, action: ToolCall) -> PFExecution | None:
        for pf in self.pfs:
            if pf.should_activate(state, action):
                intervention = pf.intervene(state, action)
                return PFExecution(
                    pf_name=pf.name,
                    layer=pf.layer,
                    original_action=action,
                    intervention=intervention,
                )
        return None
