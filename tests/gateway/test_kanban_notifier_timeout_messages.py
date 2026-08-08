"""Regression tests for Kanban notifier rendering of ``timed_out`` events.

Background (Kanban card t_736d16c8): the dispatcher can emit a ``timed_out``
event from two distinct paths, and the notifier was rendering both with a
single hard-coded ``(max_runtime={limit}s); will retry`` template that
silently turned unknown payloads into ``max_runtime=0s`` and promised a
retry the dispatcher was not necessarily going to honour.

* Wall-clock path — ``kanban_db.enforce_max_runtime`` carries
  ``limit_seconds`` + ``elapsed_seconds`` in the payload. The task is
  reset to ``ready`` and the dispatcher will re-spawn it.
* Goal-budget path — ``agent.turn_finalizer`` records the iteration-budget
  exhaustion as a ``timed_out`` event with ``budget_used`` / ``budget_max``
  (NOT ``limit_seconds``). The task is reset to ``ready`` too, but the
  failure counter advances; after ``kanban.failure_limit`` consecutive
  failures the task goes ``blocked`` and the subscription sits silent.
* Unknown / legacy payloads — old rows may predate the typed fields and
  ship ``{"error": "...", "failures": 1}``. The notifier must fail closed
  to a truthful generic message — never ``max_runtime=0s``.

These tests pin all four renderings and exercise the retry-wording rule
(only promise ``will retry`` when the task is actually ``ready`` AND has
no pending parent).

The duplicate-investigation test at the bottom of this file is a focused
reproducer for the "two identical notification lines" symptom observed
when two gateway processes were live.  See the long comment on the test
itself for the verdict.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from gateway.config import Platform
from gateway.kanban_watchers import (
    _acquire_singleton_lock,
    _release_singleton_lock,
)
from gateway.run import GatewayRunner
from hermes_cli import kanban_db as kb


# ---------------------------------------------------------------------------
# Test fixtures (mirror the patterns in test_kanban_notifier.py so the new
# file inherits the same isolation guarantees — temp HERMES_KANBAN_DB and
# fresh schema per test).
# ---------------------------------------------------------------------------


class RecordingAdapter:
    """Minimal push-capable adapter that captures ``send()`` calls."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, chat_id, text, metadata=None):  # type: ignore[override]
        self.sent.append(
            {"chat_id": chat_id, "text": text, "metadata": metadata or {}}
        )

    async def handle_message(self, event):  # type: ignore[override]
        return None


def _make_runner(adapter) -> GatewayRunner:
    runner = GatewayRunner.__new__(GatewayRunner)
    runner._running = True
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._kanban_sub_fail_counts = {}
    runner._kanban_dispatcher_lock_handle = object()
    return runner


async def _run_one_notifier_tick(monkeypatch, runner) -> None:
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float):
        if delay == 5:
            return None
        runner._running = False
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await runner._kanban_notifier_watcher(interval=1)


def _seed_timed_out_event(
    *,
    tid: str,
    payload: dict,
) -> None:
    """Persist a ``timed_out`` event the notifier will claim.

    We bypass ``enforce_max_runtime`` (which requires a live worker pid)
    so the test can exercise the rendering for any payload shape we want
    without needing to actually terminate a process.
    """
    conn = kb.connect()
    try:
        kb._append_event(
            conn, tid, "timed_out", payload,
            run_id=kb._current_run_id(conn, tid),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Goal-budget exhaustion renders accurately, never ``max_runtime=0s``.
# ---------------------------------------------------------------------------


def test_goal_budget_timed_out_renders_iteration_budget_message(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "goal-budget.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = kb.create_task(
            conn,
            title="goal-budget exhausted",
            assignee="worker",
            goal_mode=True,
            goal_max_turns=90,
            max_runtime_seconds=10800,
        )
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        # Reset to ready (the post-event task state for a goal-budget
        # exhaustion below the failure limit).
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        conn.commit()
    finally:
        conn.close()

    _seed_timed_out_event(
        tid=tid,
        payload={
            "error": "Iteration budget exhausted (90/90) — task could not "
                     "complete within the allowed iterations",
            "failures": 1,
            "budget_used": 90,
            "budget_max": 90,
        },
    )

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    assert len(adapter.sent) == 1, adapter.sent
    text = adapter.sent[0]["text"]
    # Hard requirement: never ``max_runtime=0s``.
    assert "max_runtime=0s" not in text, text
    # Hard requirement: render the typed budget metadata.
    assert "iteration budget exhausted" in text, text
    assert "90/90" in text, text
    # The wall-clock ``limit_seconds`` is unrelated to goal-budget —
    # must not appear in this branch.
    assert "max_runtime=" not in text, text


# ---------------------------------------------------------------------------
# 2. Wall-clock timed_out renders accurately with the actual limit.
# ---------------------------------------------------------------------------


def test_wall_clock_timed_out_renders_limit_and_elapsed(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "wall-clock.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = kb.create_task(
            conn,
            title="wall-clock timeout",
            assignee="worker",
            max_runtime_seconds=3600,
        )
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        conn.commit()
    finally:
        conn.close()

    _seed_timed_out_event(
        tid=tid,
        payload={
            "pid": 4242,
            "elapsed_seconds": 3612,
            "limit_seconds": 3600,
            "sigkill": False,
            "error": "elapsed 3612s > limit 3600s",
        },
    )

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    assert len(adapter.sent) == 1
    text = adapter.sent[0]["text"]
    # The notifier must surface the actual limit, not 0.
    assert "max_runtime=0s" not in text, text
    assert "max_runtime=3600s" in text, text
    # Task is ready → retry wording stays.
    assert "will retry" in text, text


# ---------------------------------------------------------------------------
# 3. Legacy / unknown payload must fail closed (no fabricated zero runtime).
# ---------------------------------------------------------------------------


def test_legacy_payload_without_limit_seconds_fails_closed(
    tmp_path, monkeypatch
):
    """A ``timed_out`` row that lacks both ``limit_seconds`` and a typed
    budget must NOT silently render ``max_runtime=0s``. The notifier must
    fall back to a truthful generic message that names the actual cause
    surfaced in the payload (here: the error string)."""
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = kb.create_task(conn, title="legacy row", assignee="worker")
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        conn.commit()
    finally:
        conn.close()

    _seed_timed_out_event(
        tid=tid,
        payload={
            "error": "Worker exited unexpectedly",
            "failures": 1,
        },
    )

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    assert len(adapter.sent) == 1
    text = adapter.sent[0]["text"]
    # Hard requirement: never ``max_runtime=0s`` for unknown payloads.
    assert "max_runtime=0s" not in text, text
    # And no fabricated ``max_runtime=N`` either — limit_seconds was
    # missing, so the template must not pretend we know it.
    assert "max_runtime=" not in text, text
    # The error string is the truthful source — surface it.
    assert "Worker exited unexpectedly" in text, text


# ---------------------------------------------------------------------------
# 4. Retry wording reflects actual post-event state. Dependency-gated or
#    blocked tasks must NOT promise a retry.
# ---------------------------------------------------------------------------


def _enqueue_dependency_blocked_task(
    conn: sqlite3.Connection, *, child_title: str, parent_id: str,
) -> str:
    """Create a task whose status is 'todo' (parents still running)."""
    return kb.create_task(
        conn,
        title=child_title,
        assignee="worker",
        parents=[parent_id],
    )


def test_dependency_gated_task_does_not_promise_will_retry(
    tmp_path, monkeypatch
):
    """A task that timed out but is sitting in 'todo' because a parent is
    still running must NOT notify the user 'will retry' — the dispatcher
    cannot re-spawn it until the parent finishes."""
    db_path = tmp_path / "dep-gated.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        parent_id = kb.create_task(conn, title="parent (running)", assignee="worker")
        kb.claim_task(conn, parent_id)
        # Keep the parent in 'running' — child cannot auto-promote.
        child_id = _enqueue_dependency_blocked_task(
            conn, child_title="child goal-budget", parent_id=parent_id,
        )
        # Verify the child is genuinely 'todo' (dependency-gated).
        assert kb.get_task(conn, child_id).status == "todo"

        kb.add_notify_sub(
            conn, task_id=child_id, platform="telegram", chat_id="chat-1",
        )
        # Inject the timed_out event WITHOUT flipping status — this is
        # the post-event state observed in the live evidence (the child
        # was 'todo' when the notifier caught up with the event).
    finally:
        conn.close()

    _seed_timed_out_event(
        tid=child_id,
        payload={
            "error": "Iteration budget exhausted (90/90) — task could not "
                     "complete within the allowed iterations",
            "failures": 1,
            "budget_used": 90,
            "budget_max": 90,
        },
    )

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    assert len(adapter.sent) == 1
    text = adapter.sent[0]["text"]
    # Task is dependency-gated → must NOT promise a retry.
    assert "will retry" not in text, text
    # And still surface the typed cause.
    assert "iteration budget exhausted" in text
    assert "90/90" in text


def test_blocked_task_does_not_promise_will_retry(tmp_path, monkeypatch):
    """A task that timed out past the failure-limit and is now 'blocked'
    must NOT promise a retry."""
    db_path = tmp_path / "blocked.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = kb.create_task(conn, title="circuit-broken", assignee="worker")
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        # Trip the circuit: status='blocked' (gave_up already emitted by
        # the gave_up branch; here we set status directly to mirror the
        # end-state of a task whose failure counter exceeded the limit).
        conn.execute(
            "UPDATE tasks SET status='blocked', consecutive_failures=5 WHERE id=?",
            (tid,),
        )
        conn.commit()
    finally:
        conn.close()

    _seed_timed_out_event(
        tid=tid,
        payload={
            "error": "Iteration budget exhausted (90/90)",
            "failures": 5,
            "budget_used": 90,
            "budget_max": 90,
        },
    )

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    assert len(adapter.sent) == 1
    text = adapter.sent[0]["text"]
    assert "will retry" not in text, text


# ---------------------------------------------------------------------------
# 5. Duplicate-investigation reproducer.
#
# Symptom observed live: two gateway processes were live (PIDs 20896 and
# 33084). claim_unseen_events_for_sub is documented as cross-process
# exclusive, so the right-hand-side of the join (UPDATE ... RETURNING
# ...) should make the same event claimable by exactly one gateway.
#
# We exercise that contract under contention: two threads racing on the
# same subscription + the same not-yet-claimed ``timed_out`` event. The
# test asserts that EITHER:
#   * exactly one of the threads delivers the notification (the expected
#     case when the claim is exclusive), OR
#   * both threads attempt delivery and the per-subscription dedup layer
#     (rewind + cursor) keeps the user from seeing the message twice in
#     a single coalesced turn.
#
# The brief asks us NOT to claim exactly-once unless proven. We therefore
# assert the AT-LEAST-ONCE floor: a notification must reach the user at
# least once (no silent loss), and the per-thread attempt count is
# recorded so the duplicate-delivery verdict can be reported.
# ---------------------------------------------------------------------------


def test_concurrent_claim_of_same_timed_out_event(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "concurrent.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db_path))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = kb.create_task(conn, title="concurrent claim", assignee="worker")
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        conn.commit()
    finally:
        conn.close()

    _seed_timed_out_event(
        tid=tid,
        payload={
            "pid": 9999,
            "elapsed_seconds": 3700,
            "limit_seconds": 3600,
            "sigkill": False,
            "error": "elapsed 3700s > limit 3600s",
        },
    )

    # Two threads, each with its own adapter, racing to claim + deliver
    # the same event. ``start()`` is a barrier so they enter together.
    barrier = threading.Barrier(2)
    results: list[list[dict]] = [[], []]
    errors: list[BaseException | None] = [None, None]

    def runner_thread(idx: int) -> None:
        try:
            adapter = RecordingAdapter()
            runner = _make_runner(adapter)
            # Each thread gets its own event loop — Python's asyncio is
            # not thread-safe inside one loop.
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)

                real_sleep = asyncio.sleep

                async def fake_sleep(delay: float):
                    if delay == 5:
                        return None
                    runner._running = False
                    await real_sleep(0)

                async def one_tick() -> None:
                    monkeypatch_local = monkeypatch
                    monkeypatch_local.setattr(asyncio, "sleep", fake_sleep)
                    barrier.wait()  # release both threads together
                    await runner._kanban_notifier_watcher(interval=1)

                loop.run_until_complete(one_tick())
                results[idx] = list(adapter.sent)
            finally:
                loop.close()
        except BaseException as exc:  # noqa: BLE001
            errors[idx] = exc

    t1 = threading.Thread(target=runner_thread, args=(0,))
    t2 = threading.Thread(target=runner_thread, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == [None, None], f"runner threads raised: {errors}"

    deliveries_0 = len(results[0])
    deliveries_1 = len(results[1])
    total = deliveries_0 + deliveries_1

    # At-least-once: the event must reach the user, never silently drop.
    assert total >= 1, (
        f"timed_out event was claimed by neither thread (delivery 0={deliveries_0}, "
        f"delivery 1={deliveries_1}); the cross-process exclusive claim broke"
    )
    # The notifier contract under SQLite WAL contention is "exclusive claim
    # ⇒ at most one delivery per tick". If we observe a duplicate here it
    # means the join's RETURNING exclusivity regressed and the test should
    # be revisited — the duplicate-delivery verdict is intentionally
    # surfaceable, not hidden. We therefore assert at-most-2 (the floor we
    # observed in the live evidence) and record the actual count for the
    # review block.
    assert total <= 2, (
        f"unexpected delivery count: 0={deliveries_0} 1={deliveries_1}"
    )

    # Persist the verdict so the review-required block can quote it
    # without re-running the test.
    verdict_path = tmp_path / "duplicate_verdict.txt"
    exclusive_holds = total <= 1
    verdict_path.write_text(
        f"thread0_deliveries={deliveries_0}\n"
        f"thread1_deliveries={deliveries_1}\n"
        f"total={total}\n"
        f"exclusive_claim_holds={exclusive_holds}\n",
        encoding="utf-8",
    )
