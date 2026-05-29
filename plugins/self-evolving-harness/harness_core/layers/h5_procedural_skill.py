"""H5 Procedural Skill layer.

Retrieves task-relevant procedural skills and formats them for injection at
episode start. Life-Harness used BM25 over a hand-written corpus; in
production this is backed by OpenViking semantic recall. The selection and
formatting logic is a pure, testable function — the OV backend supplies the
corpus.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Skill:
    """A procedural skill: a short name and its guidance content."""

    name: str
    content: str


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def retrieve_skills(skills: list[Skill], query: str, top_k: int = 3) -> list[Skill]:
    """Return up to top_k skills ranked by term overlap with the query.

    Skills with zero overlap are excluded (no spurious injection). Ties keep
    corpus order (stable sort).
    """
    q = _terms(query)
    scored = [(len(q & _terms(f"{s.name} {s.content}")), s) for s in skills]
    relevant = [(score, i, s) for i, (score, s) in enumerate(scored) if score > 0]
    relevant.sort(key=lambda x: (-x[0], x[1]))
    return [s for _, _, s in relevant[:top_k]]


def format_skills_block(skills: list[Skill]) -> str:
    """Format selected skills into a block to inject into the system prompt."""
    if not skills:
        return ""
    lines = ["Relevant procedural skills for this task:"]
    lines += [f"- {s.name}: {s.content}" for s in skills]
    return "\n".join(lines)
