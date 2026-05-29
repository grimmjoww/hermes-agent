"""PF efficacy tracking — within-run help-rate disable.

NON-PAPER EXTENSION. This module has NO basis in Continual-Harness
(arXiv 2605.09998) or HASP (arXiv 2605.17734) — it is an invented harness
heuristic, not a paper mechanism. It tracks a per-PF help-rate from
caller-supplied boolean outcomes and flags a PF whose help-rate falls below a
threshold (given enough samples) for disabling within a run. It does NOT read
any structured HASP execution record; the only input is the `helped: bool`
passed to `record`. Treat it as an operator-tunable extension, separate from
the paper-faithful gate (HASP try_admit) and proposer (Continual-Harness).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Stats:
    helped: int = 0
    total: int = 0


class PFEfficacyTracker:
    def __init__(self, min_samples: int = 3, help_rate_threshold: float = 0.5) -> None:
        self.min_samples = min_samples
        self.help_rate_threshold = help_rate_threshold
        self._stats: dict[str, _Stats] = {}

    def record(self, pf_name: str, helped: bool) -> None:
        s = self._stats.setdefault(pf_name, _Stats())
        s.total += 1
        if helped:
            s.helped += 1

    def help_rate(self, pf_name: str) -> float | None:
        s = self._stats.get(pf_name)
        if not s or s.total == 0:
            return None
        return s.helped / s.total

    def should_disable(self, pf_name: str) -> bool:
        """Disable a PF once there's enough evidence its help-rate is too low.

        Heuristic (non-paper extension): requires >= min_samples observations
        and a help-rate below the threshold.
        """
        s = self._stats.get(pf_name)
        if not s or s.total < self.min_samples:
            return False
        return (s.helped / s.total) < self.help_rate_threshold

    def filter_active(self, pf_names: list) -> list:
        """Drop PFs flagged for disabling — the active set the harness should use."""
        return [n for n in pf_names if not self.should_disable(n)]
