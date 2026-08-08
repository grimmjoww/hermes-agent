"""Regression tests for ``_record_task_failure`` event payload persistence.

Background (Kanban card t_736d16c8): the goal-budget exhaustion path in
``agent.turn_finalizer`` calls ``_record_task_failure(outcome="timed_out",
..., event_payload_extra={"budget_used": ..., "budget_max": ...})``.

The gave_up branch (above the failure-limit) correctly folds the extras
into the event payload. The below-threshold branch did NOT — it emitted
the ``timed_out`` event with only ``{"error", "failures"}`` and silently
dropped ``budget_used``/``budget_max``.

That drop is what made the notifier render ``max_runtime=0s`` for every
goal-budget event, because the only typed fields it could read were
``limit_seconds`` (wall-clock only) and ``elapsed_seconds`` (wall-clock
only). Without those, ``limit`` defaulted to 0.

These tests pin both branches: gave_up persists extras (sanity check that
the existing behavior stays intact) and below-threshold release_claim
persists extras (the fix).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


def _make_claimed_task(conn, *, title: str, assignee: str = "worker") -> str:
    """Helper: create a task, claim it, set a live worker pid."""
    tid = kb.create_task(conn, title=title, assignee=assignee)
    kb.claim_task(conn, tid)
    kb._set_worker_pid(conn, tid, 99999)
    return tid


def test_below_threshold_release_claim_persists_event_payload_extra(
    tmp_path, monkeypatch
):
    """Reproduces the live bug: a goal-budget exhaustion with
    ``event_payload_extra={"budget_used": 90, "budget_max": 90}`` must
    reach the persisted ``timed_out`` event row.
    """
    db_path = tmp_path / "payload-extra.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = _make_claimed_task(conn, title="goal-budget below threshold")

        # Stay below the default failure limit (2) so we land on the
        # below-threshold branch.
        kb._record_task_failure(
            conn,
            tid,
            error="Iteration budget exhausted (90/90) — task could not "
                  "complete within the allowed iterations",
            outcome="timed_out",
            release_claim=True,
            end_run=True,
            event_payload_extra={
                "budget_used": 90,
                "budget_max": 90,
            },
        )

        events = kb.list_events(conn, tid)
        timed_out = [e for e in events if e.kind == "timed_out"]
        assert len(timed_out) == 1, events
        payload = timed_out[0].payload
        # Both typed budget fields must survive into the persisted row.
        assert payload.get("budget_used") == 90, payload
        assert payload.get("budget_max") == 90, payload
        # Sanity: the wall-clock fields are NOT in this payload — the
        # notifier must read it as goal-budget, not wall-clock.
        assert "limit_seconds" not in payload, payload
        assert "elapsed_seconds" not in payload, payload
    finally:
        conn.close()


def test_wall_clock_enforce_max_runtime_persists_payload(
    tmp_path, monkeypatch
):
    """Companion test: the wall-clock timeout path (``enforce_max_runtime``)
    emits its OWN ``timed_out`` event with the typed payload (limit_seconds,
    elapsed_seconds, pid, sigkill). This pins that behaviour so a future
    refactor of enforce_max_runtime cannot regress it.

    Note: ``_record_task_failure`` is also called from this path with
    ``end_run=False`` (because the event is already emitted before the
    call), so the extras travel through ``enforce_max_runtime``'s own
    event row, NOT through ``_record_task_failure``.
    """
    import os
    import time

    db_path = tmp_path / "wall-clock-extras.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    # Pass a no-op signal_fn so we never actually raise SIGTERM against
    # the pytest process. Use a fake pid (99999) that does not exist so
    # ProcessLookupError is caught by the path's own except clause.
    killed: list = []

    def _signal_fn(pid, sig):
        killed.append((pid, sig))

    # We bypass _pid_alive by stubbing it so the grace-poll exits fast.
    import hermes_cli.kanban_db as _kb
    original_alive = _kb._pid_alive
    _kb._pid_alive = lambda pid: False

    try:
        conn = kb.connect()
        try:
            tid = kb.create_task(
                conn, title="wall-clock timeout", assignee="worker",
                max_runtime_seconds=1,
            )
            kb.claim_task(conn, tid)
            # Use a high fake pid that does NOT belong to the test runner.
            kb._set_worker_pid(conn, tid, 99999)
            # Backdate started_at on both task + active run so elapsed > limit.
            old_started = int(time.time()) - 30
            with kb.write_txn(conn):
                conn.execute(
                    "UPDATE tasks SET started_at = ? WHERE id = ?",
                    (old_started, tid),
                )
                conn.execute(
                    "UPDATE task_runs SET started_at = ? "
                    "WHERE id = (SELECT current_run_id FROM tasks WHERE id = ?)",
                    (old_started, tid),
                )

            timed_out = kb.enforce_max_runtime(conn, signal_fn=_signal_fn)
            assert tid in timed_out
            assert killed and killed[0][0] == 99999

            events = kb.list_events(conn, tid)
            timed_out_events = [e for e in events if e.kind == "timed_out"]
            assert len(timed_out_events) == 1, events
            payload = timed_out_events[0].payload
            # All four typed fields must survive into the persisted row.
            assert payload.get("limit_seconds") == 1, payload
            assert payload.get("elapsed_seconds", 0) >= 30, payload
            assert payload.get("pid") == 99999, payload
            assert "sigkill" in payload, payload
        finally:
            conn.close()
    finally:
        _kb._pid_alive = original_alive


def test_above_threshold_gave_up_still_persists_event_payload_extra(
    tmp_path, monkeypatch
):
    """Sanity guard: the gave_up branch (above the failure limit) ALREADY
    persists ``event_payload_extra`` today. This test pins that behaviour
    so the fix does not regress it.

    With the default failure_limit=2, the first call lands below the
    threshold (failures=1 < 2 → release_claim, status=ready, no gave_up
    event). The second call lands at the limit (failures=2 >= 2) and
    trips the breaker → gave_up path, which is where the extras must
    survive.
    """
    db_path = tmp_path / "gave-up-extras.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = _make_claimed_task(conn, title="goal-budget above threshold")
        # First call: below threshold, release_claim, no gave_up yet.
        kb._record_task_failure(
            conn, tid, error="first",
            outcome="timed_out", release_claim=True, end_run=True,
        )
        # Second call: trips the breaker → gave_up path with extras.
        kb._record_task_failure(
            conn, tid, error="second (gave_up)",
            outcome="timed_out", release_claim=True, end_run=True,
            event_payload_extra={"budget_used": 90, "budget_max": 90},
        )

        events = kb.list_events(conn, tid)
        gave_up = [e for e in events if e.kind == "gave_up"]
        assert len(gave_up) == 1, events
        payload = gave_up[0].payload
        assert payload.get("budget_used") == 90, payload
        assert payload.get("budget_max") == 90, payload
    finally:
        conn.close()
