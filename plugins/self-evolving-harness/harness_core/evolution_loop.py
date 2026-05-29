"""Evolution loop — regression-gated PF admission with rollback.

The control that stops the self-evolution loop from "saturating early and not
rolling back": a candidate PF is admitted to the active library ONLY if it does
not regress the score (HASP: "admit only after validation"); otherwise it is
rolled back. Snapshot/restore also lets the harness reset state between tests
so conditions stay independent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class AdmitResult:
    admitted: bool
    score_before: float
    score_after: float


class SkillLibrary:
    """The active set of admitted PFs, with snapshot/restore for rollback."""

    def __init__(self) -> None:
        self.active: list = []

    def add(self, pf) -> None:
        self.active.append(pf)

    def snapshot(self) -> list:
        return list(self.active)

    def restore(self, snap: list) -> None:
        self.active = list(snap)


def try_admit(
    library: SkillLibrary,
    candidate,
    scorer: Callable[[list], float],
    require_strict_improvement: bool = False,
) -> AdmitResult:
    """Tentatively add `candidate`, score it, keep it only if it doesn't regress.

    `scorer(active_pfs) -> float` evaluates the library (e.g. eval reward).
    If admitting the candidate regresses the score (or, with
    `require_strict_improvement`, fails to improve it), roll back.
    """
    before = scorer(list(library.active))
    snap = library.snapshot()
    library.add(candidate)
    after = scorer(list(library.active))
    keep = after > before if require_strict_improvement else after >= before
    if keep:
        return AdmitResult(admitted=True, score_before=before, score_after=after)
    library.restore(snap)
    return AdmitResult(admitted=False, score_before=before, score_after=after)
