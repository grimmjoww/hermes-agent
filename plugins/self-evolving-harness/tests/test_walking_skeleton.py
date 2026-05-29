"""Walking skeleton — the full self-evolution loop closes across a session.

Demonstrates the whole system end-to-end with the in-memory backend:
  session 1: a run fails (a loop) -> evolver proposes an H4 rule -> persist
  session 2: load the evolved rule -> build the harness FROM the rules ->
             the harness now catches the failure that went uncaught before.

This is the compounding-improvement mechanic that neither Life-Harness nor
Continual Harness has (freeze / per-episode reset).
"""
from harness_core.evolver import FailureEvent, propose_rule
from harness_core.persistence import InMemoryRuleStore
from harness_core.controller import HarnessController
from harness_core.layers.h4_trajectory import ToolCall


def _loop():
    return [ToolCall("search_flights", {"q": "JFK-SFO"})] * 3


def test_before_evolution_the_loop_is_not_caught():
    # a naive harness built from NO evolved rules does not catch the loop
    controller = HarnessController.from_rules([], enabled=True)
    assert controller.monitor_post_execution(_loop()) is None


def test_loop_closes_observe_evolve_persist_reload_catch():
    backend: dict = {}

    # session 1 — observe a recurring loop failure, evolve a rule, persist it
    rule = propose_rule([FailureEvent("search_flights", "loop")] * 3)
    assert rule is not None and rule.layer == "H4"
    InMemoryRuleStore(backend, "harness-study").save(rule)

    # session 2 (fresh) — reload evolved rules and build the harness from them
    reloaded = InMemoryRuleStore(backend, "harness-study").load()
    controller = HarnessController.from_rules(reloaded, enabled=True)

    # the harness now catches the exact failure that was uncaught in session 1
    corr = controller.monitor_post_execution(_loop())
    assert corr is not None
    assert corr.tool_name == "search_flights"
