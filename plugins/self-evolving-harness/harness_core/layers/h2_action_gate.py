"""H2 Action Gate layer.

Pre-execution validity check against the tool contract. Per Life-Harness:
action-interface errors can be judged BEFORE execution using prior information
(the declared tool spec) — without inferring the agent's intent. Invalid calls
are blocked with corrective guidance so the agent can self-correct.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from harness_core.layers.h4_trajectory import ToolCall


@dataclass(frozen=True)
class ToolSpec:
    """The declared contract for a tool: its name and required argument keys."""

    name: str
    required: list[str] = field(default_factory=list)


@dataclass
class GateDecision:
    """Outcome of the pre-execution gate."""

    action: str  # "allow" | "block"
    reason: str = ""
    guidance: str = ""


def check_tool_call(call: ToolCall, specs: dict[str, ToolSpec]) -> GateDecision:
    """Validate a proposed tool call against the known tool specs."""
    spec = specs.get(call.name)
    if spec is None:
        known = ", ".join(sorted(specs)) or "(none)"
        return GateDecision(
            action="block",
            reason=f"Unknown tool '{call.name}'.",
            guidance=f"'{call.name}' is not an available tool. Available tools: {known}.",
        )
    missing = [k for k in spec.required if k not in call.args]
    if missing:
        names = ", ".join(missing)
        return GateDecision(
            action="block",
            reason=f"Missing required argument(s) for '{call.name}': {names}.",
            guidance=(
                f"The call to '{call.name}' is missing required argument(s): {names}. "
                f"Re-issue the call with all required arguments: {', '.join(spec.required)}."
            ),
        )
    return GateDecision(action="allow")
