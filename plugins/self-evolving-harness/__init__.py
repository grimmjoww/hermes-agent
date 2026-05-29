"""self-evolving-harness — Hermes plugin (canonical v0.15.1 plugin API).

Wires the 4-layer Life-Harness program-function runtime (H2/H3/H4/H5) onto the
Hermes agent turn via ``register(ctx)`` + ``ctx.register_hook(...)``, and exposes
a ``/harness`` slash command for status.

Hook map (real v0.15.1 dispatch signatures, discovered from the plugin host in
``hermes_cli/plugins.py`` + the call sites in ``agent/conversation_loop.py`` and
``model_tools.py``):

  on_session_start(session_id, model, platform)
      -> H5 procedural-skill / H3 tool-contract anchor; resets the per-session
         trajectory buffer; emits a visible SESSION_START event.

  pre_tool_call(tool_name, args, task_id, session_id, tool_call_id)
      -> H2 action gate. BLOCK-only (paper-faithful). Returns
         ``{"action": "block", "message": ...}`` to block, or None to allow.
         H2 is OFF by default (master switch + h2 flag), so this is an
         observer/allow path until evolved H2 rules turn it on.

  post_tool_call(tool_name, args, result, task_id, session_id, tool_call_id, duration_ms)
      -> H4 trajectory monitor. The host hook only passes the CURRENT call, so
         this handler keeps its OWN per-session trajectory buffer (keyed by
         session_id), appends the current ToolCall, runs detect_repeat_loop over
         the buffer, and on a loop emits a visible PF_FIRED event + a correction
         line. GATE-FREE: it never calls try_admit / snapshot / restore.

  on_session_end(session_id, completed, interrupted, model, platform)
      -> flush/persist anchor; emits a visible SESSION_END event; drops the
         session's trajectory buffer.

PAPER-FAITHFULNESS:
  * Continual-Harness is gate-free — the H4 post_tool_call path injects its
    correction UNCONDITIONALLY and never rolls back.
  * The HASP try_admit regression gate runs in a SEPARATE post-turn evolve pass
    (harness_core.evolution_loop), NOT inside any per-tool-call hook here.

The post_tool_call return value is not injected by the host (model_tools.py
fires the hook for observers and discards returns), so the H4 correction is made
VISIBLE via the event stream + the harness log rather than by mutating the tool
result. The handler still RETURNS the Correction so it is unit-testable.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import harness_core relatively when loaded by the Hermes host (which loads
# this dir as a package whose __path__ is the plugin dir), and fall back to a
# top-level import for tooling that imports the file standalone (pytest
# collecting __init__.py, ad-hoc REPL). Same objects either way — the plugin
# dir is on sys.path in the test harness.
try:  # pragma: no cover - exercised by both load paths
    from .harness_core.controller import HarnessController
    from .harness_core.events import Event, EventKind, EventStream
    from .harness_core.layers.h4_trajectory import Correction, ToolCall
except ImportError:  # standalone import (no parent package)
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from harness_core.controller import HarnessController
    from harness_core.events import Event, EventKind, EventStream
    from harness_core.layers.h4_trajectory import Correction, ToolCall

logger = logging.getLogger(__name__)

# The four Hermes lifecycle hooks this plugin binds (must match plugin.yaml).
VALID_HOOK_EVENTS = (
    "on_session_start",
    "pre_tool_call",
    "post_tool_call",
    "on_session_end",
)


def _log_path() -> Path:
    """``$HERMES_HOME/self-evolving-harness/harness.log`` (created on demand)."""
    home = os.getenv("HERMES_HOME") or str(Path.home() / ".hermes")
    d = Path(home) / "self-evolving-harness"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d / "harness.log"


class HarnessPlugin:
    """Runtime state + the four hook handlers.

    Holds a HarnessController (the 4-layer master switch), an EventStream so every
    layer firing is visible (Charter Req 1), and a per-session trajectory buffer
    for H4 loop detection (the host hook only hands us the current call).
    """

    def __init__(
        self,
        controller: HarnessController | None = None,
        event_stream: EventStream | None = None,
    ) -> None:
        # H4 on by default so the loop monitor is live; other layers stay off
        # (paper-faithful safe default) until evolved rules turn them on.
        self.controller = controller or HarnessController(enabled=True, h4=True)
        self.events = event_stream or EventStream()
        # session_id -> list[ToolCall]; guarded because post_tool_call can fire
        # concurrently across parallel tool calls.
        self._trajectories: Dict[str, List[ToolCall]] = {}
        self._lock = threading.Lock()
        # Cap per-session buffer so a long session can't grow unbounded; the
        # H4 detector only ever inspects the trailing `threshold` calls.
        self._max_buffer = 256

    # -- visible-surface wiring ------------------------------------------------

    def attach_default_surface(self) -> None:
        """Subscribe a logger that makes every event visible (agent.log + file)."""
        self.events.subscribe(self._emit_to_log)

    def _emit_to_log(self, ev: Event) -> None:
        line = ev.render()
        logger.info("[self-evolving-harness] %s", line)
        try:
            with open(_log_path(), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    # -- H5 + H3 at session start ---------------------------------------------

    def on_session_start(
        self,
        session_id: str = "",
        model: str = "",
        platform: str = "",
        **_: Any,
    ) -> None:
        with self._lock:
            self._trajectories[session_id] = []
        self.events.emit(
            EventKind.SESSION_START,
            f"harness session start (model={model or '?'} platform={platform or '?'})",
            session_id=session_id,
        )

    # -- H2 pre-execution gate (BLOCK-only) -----------------------------------

    def pre_tool_call(
        self,
        tool_name: str = "",
        args: Optional[Dict[str, Any]] = None,
        task_id: str = "",
        session_id: str = "",
        tool_call_id: str = "",
        **_: Any,
    ) -> Optional[Dict[str, str]]:
        # H2 is OFF by default (controller.enabled & h2). When an evolved H2 rule
        # turns the layer on, a contract check would run here and return a block
        # directive. Paper-faithful: BLOCK-only, no silent action rewrite.
        if not self.controller._active(self.controller.h2):
            return None
        # Layer active but no contract corpus wired in this slice -> allow.
        return None

    # -- H4 post-execution trajectory monitor (gate-free) ---------------------

    def post_tool_call(
        self,
        tool_name: str = "",
        args: Optional[Dict[str, Any]] = None,
        result: Any = None,
        task_id: str = "",
        session_id: str = "",
        tool_call_id: str = "",
        duration_ms: Optional[float] = None,
        **_: Any,
    ) -> Optional[Correction]:
        """Append the current call to the session buffer and run H4.

        The host passes only the current (tool_name, args, result); we accumulate
        the trajectory ourselves so detect_repeat_loop can see the trailing run.
        """
        logger.debug(
            "[self-evolving-harness] H4 post_tool_call fired: tool=%s session=%s",
            tool_name, session_id,
        )
        call = ToolCall(name=tool_name, args=args if isinstance(args, dict) else {})
        with self._lock:
            buf = self._trajectories.setdefault(session_id, [])
            buf.append(call)
            if len(buf) > self._max_buffer:
                del buf[: len(buf) - self._max_buffer]
            snapshot = list(buf)

        correction = self.controller.monitor_post_execution(snapshot)
        if correction is not None:
            # gate-free: surfaced unconditionally, never rolled back.
            self.events.emit(
                EventKind.PF_FIRED,
                f"H4 loop detected on `{correction.tool_name}` — {correction.guidance}",
                tool_name=correction.tool_name,
                session_id=session_id,
            )
        return correction

    # -- on_session_end: flush/persist anchor ---------------------------------

    def on_session_end(
        self,
        session_id: str = "",
        completed: bool = True,
        interrupted: bool = False,
        model: str = "",
        platform: str = "",
        **_: Any,
    ) -> None:
        with self._lock:
            self._trajectories.pop(session_id, None)
        self.events.emit(
            EventKind.SESSION_END,
            f"harness session end (completed={completed} interrupted={interrupted})",
            session_id=session_id,
        )

    # -- /harness slash command -----------------------------------------------

    def handle_command(self, raw_args: str) -> str:
        argv = (raw_args or "").strip().split()
        sub = argv[0] if argv else "status"
        if sub in {"help", "-h", "--help"}:
            return (
                "/harness — self-evolving harness\n"
                "  status   Show master switch, active layers, recent events\n"
                "  events   Dump the recent event history\n"
            )
        if sub == "events":
            hist = self.events.history[-20:]
            if not hist:
                return "[self-evolving-harness] no events yet this process."
            return "\n".join(e.render() for e in hist)
        # default: status
        c = self.controller
        active = [name for name, on in
                  (("H2", c.h2), ("H3", c.h3), ("H4", c.h4), ("H5", c.h5)) if on]
        with self._lock:
            n_sessions = len(self._trajectories)
            n_calls = sum(len(v) for v in self._trajectories.values())
        return (
            "[self-evolving-harness] status\n"
            f"  master switch : {'ON' if c.enabled else 'OFF'}\n"
            f"  active layers : {', '.join(active) or '(none)'}\n"
            f"  H4 threshold  : {c.h4_threshold} identical consecutive calls\n"
            f"  tracked       : {n_sessions} session(s), {n_calls} buffered call(s)\n"
            f"  events fired  : {len(self.events.history)} this process"
        )


# Module-level singleton: one harness per Hermes process. The hook callbacks the
# host stores are bound methods of THIS instance, so the per-session trajectory
# buffer survives across the many post_tool_call invocations of a turn.
_PLUGIN: Optional[HarnessPlugin] = None


def _get_plugin() -> HarnessPlugin:
    global _PLUGIN
    if _PLUGIN is None:
        _PLUGIN = HarnessPlugin()
        _PLUGIN.attach_default_surface()
    return _PLUGIN


def register(ctx) -> None:
    """Hermes plugin entry point (canonical API). Binds 4 hooks + /harness."""
    plugin = _get_plugin()
    ctx.register_hook("on_session_start", plugin.on_session_start)
    ctx.register_hook("pre_tool_call", plugin.pre_tool_call)
    ctx.register_hook("post_tool_call", plugin.post_tool_call)
    ctx.register_hook("on_session_end", plugin.on_session_end)
    ctx.register_command(
        "harness",
        handler=plugin.handle_command,
        description="Self-evolving harness status + recent self-evolution events.",
        args_hint="status | events",
    )
    logger.info(
        "[self-evolving-harness] registered: 4 hooks (%s) + /harness command",
        ", ".join(VALID_HOOK_EVENTS),
    )
