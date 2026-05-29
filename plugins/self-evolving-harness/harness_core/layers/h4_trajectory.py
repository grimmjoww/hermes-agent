"""H4 Trajectory Monitor layer.

Post-execution, count-based loop/stagnation detection. Per Life-Harness
Harness.md: self-reinforcing trajectory failures are detectable from the
*statistical properties* of the action sequence (e.g. an identical call
repeated N times), independent of the call's semantics — which makes the
rule broadly generalizable across environments.

This is the layer Rei's runtime currently lacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation in the trajectory."""

    name: str
    args: dict = field(default_factory=dict)


@dataclass
class Correction:
    """A corrective annotation to inject into what the agent sees next."""

    tool_name: str
    guidance: str


def detect_repeat_loop(calls: list[ToolCall], threshold: int = 3) -> Correction | None:
    """Return a Correction if the trailing `threshold` calls are identical.

    Identical = same tool name AND same arguments. Only the *trailing* run is
    considered, so a repeat that was already broken by a different action does
    not trigger.
    """
    if threshold < 1 or len(calls) < threshold:
        return None
    tail = calls[-threshold:]
    first = tail[0]
    if all(c.name == first.name and c.args == first.args for c in tail):
        return Correction(
            tool_name=first.name,
            guidance=(
                f"You have called `{first.name}` with identical arguments "
                f"{threshold} times in a row. This is a loop and it is not making "
                f"progress. Stop repeating it — try a different action, different "
                f"arguments, or re-read the task to find what is actually blocking you."
            ),
        )
    return None
