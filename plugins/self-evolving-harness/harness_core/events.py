"""Visible event stream — the surface the user SEES the self-evolution loop on.

Charter Req 1 (Agent C): every refine + admission must emit a streamed event on a
Windows-native surface (gateway / CLI / Control UI) so the loop is observable, not
a silent background mutation. This module is the in-process publish/subscribe spine
those surfaces attach to; it carries ZERO platform deps (no WSL-only dashboard
pane), so it runs natively on Windows and is unit-testable.

Subscribers are plain callables: a CLI printer, a gateway pusher, a test sink. The
emitter never reaches into a renderer — it just publishes typed events. That keeps
the "did the loop fire a visible event?" assertion testable without a UI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class EventKind(str, Enum):
    REFINER_PROPOSED = "refiner_proposed"   # Refiner emitted N edits
    PF_ADMITTED = "pf_admitted"             # gate admitted a PF
    PF_REVERTED = "pf_reverted"             # gate rolled a regressing PF back
    SKILL_REGISTERED = "skill_registered"   # a real skill became a managed PF
    RULE_PERSISTED = "rule_persisted"       # an evolved rule was saved to the store
    PF_FIRED = "pf_fired"                   # a PF activated at runtime (e.g. H4 correction)
    SESSION_START = "session_start"         # harness session-start hook fired
    SESSION_END = "session_end"             # harness session-end hook fired


@dataclass
class Event:
    kind: EventKind
    message: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def render(self) -> str:
        """One human-readable line, the form a CLI/gateway surface would show."""
        return f"[{self.kind.value}] {self.message}"


class EventStream:
    """Publish/subscribe event spine. Keeps a history AND fans out to subscribers.

    `subscribe` a callable to receive each event live (CLI print, gateway push).
    `history` lets a late-attaching surface (or a test) read what already fired.
    """

    def __init__(self) -> None:
        self.history: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subscribers.append(fn)

    def emit(self, kind: EventKind, message: str, **data) -> Event:
        ev = Event(kind=kind, message=message, data=data)
        self.history.append(ev)
        for fn in self._subscribers:
            fn(ev)
        return ev

    def events_of(self, kind: EventKind) -> list[Event]:
        return [e for e in self.history if e.kind == kind]
