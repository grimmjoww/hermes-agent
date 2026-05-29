"""Visible event-stream contract tests (Charter Req 1 — visible-or-it-doesn't-exist).

These assert the UI SURFACE fired — the testable form of "the user SEES the
self-evolution loop." The stream is platform-free (no WSL dashboard dep), so the
"did a visible event fire?" assertion runs natively on Windows without a UI.

NOT a paper mechanism: the event surface is harness infrastructure for
Requirement 1, separate from the paper-faithful proposer (CH) and gate (HASP).
"""
from harness_core.events import Event, EventKind, EventStream


def test_emit_appends_to_history_and_returns_event():
    s = EventStream()
    ev = s.emit(EventKind.REFINER_PROPOSED, "Refiner proposed 3 edits", n=3)
    assert isinstance(ev, Event)
    assert ev.kind == EventKind.REFINER_PROPOSED
    assert ev.data == {"n": 3}
    assert s.history == [ev]


def test_subscriber_receives_every_event_live():
    s = EventStream()
    sink: list[Event] = []
    s.subscribe(sink.append)
    s.emit(EventKind.PF_ADMITTED, "ADMITTED evolved_h4_nav_loop")
    s.emit(EventKind.PF_REVERTED, "REVERTED regressing PF")
    assert [e.kind for e in sink] == [EventKind.PF_ADMITTED, EventKind.PF_REVERTED]


def test_late_subscriber_can_read_prior_history():
    s = EventStream()
    s.emit(EventKind.RULE_PERSISTED, "saved evolved_h4_nav_loop")
    # a surface attaching after the fact still sees what already fired
    assert len(s.history) == 1
    assert s.events_of(EventKind.RULE_PERSISTED)[0].message.startswith("saved")


def test_events_of_filters_by_kind():
    s = EventStream()
    s.emit(EventKind.REFINER_PROPOSED, "proposed 1")
    s.emit(EventKind.PF_ADMITTED, "admitted")
    s.emit(EventKind.REFINER_PROPOSED, "proposed 2")
    assert len(s.events_of(EventKind.REFINER_PROPOSED)) == 2
    assert len(s.events_of(EventKind.PF_ADMITTED)) == 1


def test_render_is_one_human_line():
    ev = Event(EventKind.PF_REVERTED, "REVERTED — regression failed, rolled back")
    line = ev.render()
    assert line == "[pf_reverted] REVERTED — regression failed, rolled back"


def test_all_loop_event_kinds_present():
    # Req 1 named events: refine, admit, revert, skill-register, persist.
    kinds = {k.value for k in EventKind}
    assert {
        "refiner_proposed",
        "pf_admitted",
        "pf_reverted",
        "skill_registered",
        "rule_persisted",
    } <= kinds


def test_visible_surface_fires_on_a_refine_admit_revert_sequence():
    """End-to-end shape of the visible loop: a surface (the sink) observes the
    full refine -> admit -> revert sequence — the proof-of-life assertion."""
    s = EventStream()
    seen: list[str] = []
    s.subscribe(lambda e: seen.append(e.kind.value))
    s.emit(EventKind.REFINER_PROPOSED, "Refiner proposed 2 edits", n=2)
    s.emit(EventKind.PF_ADMITTED, "ADMITTED evolved_h4_nav_loop")
    s.emit(EventKind.PF_REVERTED, "REVERTED evolved_h2_api_missing_arg")
    assert seen == ["refiner_proposed", "pf_admitted", "pf_reverted"]
