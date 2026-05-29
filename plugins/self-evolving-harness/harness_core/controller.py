"""HarnessController — the 4-layer runtime harness behind a master switch.

Layer lifecycle (Life-Harness Harness.md):
  H3  episode init     — augment tool contracts        (system-prompt time)
  H5  episode start    — inject procedural skills       (system-prompt time)
  H2  pre-execution    — gate/repair/block a tool call
  H4  post-execution   — detect loops/stagnation, inject correction

A layer fires only when the master `enabled` switch AND its own flag are on,
matching Life-Harness's `--enabled` semantics. Off by default (safe).

`from_rules` builds a controller whose active layers are determined by a set
of evolved, persisted rules — so the harness in a new session is configured by
what previous sessions learned.
"""
from __future__ import annotations

from dataclasses import dataclass

from harness_core.layers.h4_trajectory import Correction, ToolCall, detect_repeat_loop


@dataclass
class HarnessController:
    enabled: bool = False  # master switch
    h2: bool = False
    h3: bool = False
    h4: bool = False
    h5: bool = False
    h4_threshold: int = 3

    @classmethod
    def from_rules(cls, rules, enabled: bool = False, **kwargs) -> "HarnessController":
        """Build a controller with the layers named by `rules` turned on.

        Each rule has a `.layer` attribute ("H2".."H5"); the corresponding
        layer flag is enabled. This is how evolved+persisted rules from past
        sessions configure the harness in the current one.
        """
        layers = {getattr(r, "layer", "").upper() for r in rules}
        return cls(
            enabled=enabled,
            h2="H2" in layers,
            h3="H3" in layers,
            h4="H4" in layers,
            h5="H5" in layers,
            **kwargs,
        )

    def _active(self, layer_flag: bool) -> bool:
        """A layer is active only if the master switch and its flag are both on."""
        return self.enabled and layer_flag

    def monitor_post_execution(self, calls: list[ToolCall]) -> Correction | None:
        """H4 Trajectory Monitor: inspect the trajectory after a tool runs."""
        if not self._active(self.h4):
            return None
        return detect_repeat_loop(calls, threshold=self.h4_threshold)

    # H2 pre_execution gate, H3 tool-contract augmentation, and H5 skill
    # injection attach here as those layers are wired into the controller.
