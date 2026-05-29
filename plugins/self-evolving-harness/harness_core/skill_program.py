"""Promote a real, existing SKILL into a managed HASP Program Function.

Charter VISIBLE acceptance test: "feed ONE real existing skill (a feature, not a
memory) -> it becomes a managed HASP program-function, no new infra."

A `Skill` (harness_core.layers.h5_procedural_skill.Skill) is a feature: a named
piece of procedural guidance. HASP's Program Function is "a skill expressed as an
executable state-action intervention" (arXiv 2605.17734). This module is the thin
PROMOTION adapter between the two — it does NOT build new infrastructure: the
result is an `EvolvedPF` (existing) that an existing `PFRegistry` manages exactly
like an evolved one.

Activation is keyword-triggered against the candidate action's tool name (the
feature fires when its trigger tool is about to run); the intervention injects the
skill's guidance as corrective context. This makes a hand-authored feature a
first-class participant in the same gate/admit/runtime path as evolved PFs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from harness_core.layers.h4_trajectory import ToolCall
from harness_core.layers.h5_procedural_skill import Skill
from harness_core.program_function import AgentState, ContextInjection, Intervention


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


@dataclass
class SkillProgramFunction:
    """A real Skill, managed as a HASP PF (satisfies the ProgramFunction Protocol).

    `trigger_tool` (optional) makes it fire only when a specific tool is about to
    run. With no trigger_tool it fires when the action's tool name overlaps the
    skill's vocabulary — the feature volunteers its guidance where relevant.
    """

    skill: Skill
    trigger_tool: str | None = None
    layer: str = "H5"  # procedural-skill layer
    name: str = field(default="")

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"skillpf_{self.skill.name}"

    def should_activate(self, state: AgentState, action: ToolCall) -> bool:
        if self.trigger_tool is not None:
            return action.name == self.trigger_tool
        return bool(_terms(action.name) & _terms(f"{self.skill.name} {self.skill.content}"))

    def intervene(self, state: AgentState, action: ToolCall) -> Intervention:
        return ContextInjection(f"[skill: {self.skill.name}] {self.skill.content}")


def promote_skill(skill: Skill, trigger_tool: str | None = None) -> SkillProgramFunction:
    """Promote a real existing skill to a managed HASP Program Function.

    No new infra: the returned object satisfies the same ProgramFunction Protocol
    as evolved PFs and is held/applied by the existing PFRegistry.
    """
    return SkillProgramFunction(skill=skill, trigger_tool=trigger_tool)
