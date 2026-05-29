"""H3 Environment Contract layer.

Augments tool descriptions with environment-specific constraints once at
episode initialization, so the agent reads the correct contract when it
decides how to call a tool. Idempotent: re-applying the same contract does
not duplicate it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolDoc:
    """A tool's name and the description text the agent sees."""

    name: str
    description: str


def augment_tool_descriptions(
    tools: list[ToolDoc], contracts: dict[str, str]
) -> list[ToolDoc]:
    """Return tool docs with environment constraints appended per matching tool."""
    out: list[ToolDoc] = []
    for tool in tools:
        contract = contracts.get(tool.name)
        if contract and contract not in tool.description:
            description = tool.description.rstrip() + " " + contract.strip()
        else:
            description = tool.description
        out.append(ToolDoc(tool.name, description))
    return out
