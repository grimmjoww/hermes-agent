"""Persistence — evolved rules survive across runs (the novel spine).

This is what neither Life-Harness (freezes) nor Continual Harness (resets
per-episode) does: evolved harness rules persist across sessions so gains
compound. Rules are namespaced; the study namespace is isolated from any
real-life namespace (memory-safety: study artifacts never bleed into Rei's
real memory).

The store is defined by a protocol; tested here with an in-memory backend.
The production backend is OpenViking (tested separately against the live OV).
"""
from harness_core.persistence import serialize_rule, deserialize_rule, InMemoryRuleStore
from harness_core.evolver import ProposedRule


def test_rule_roundtrips_through_serialization():
    r = ProposedRule(layer="H4", target_tool="search_flights", kind="loop", description="d")
    assert deserialize_rule(serialize_rule(r)) == r


def test_rules_persist_and_reload_in_a_new_session():
    backend: dict = {}  # simulates durable cross-session storage
    InMemoryRuleStore(backend, namespace="harness-study").save(
        ProposedRule("H4", "search_flights", "loop", "d")
    )
    # a fresh store instance == a new session reading the same durable backend
    reloaded = InMemoryRuleStore(backend, namespace="harness-study").load()
    assert len(reloaded) == 1
    assert reloaded[0].target_tool == "search_flights"


def test_namespaces_are_isolated():
    backend: dict = {}
    InMemoryRuleStore(backend, namespace="harness-study").save(
        ProposedRule("H4", "a", "loop", "d")
    )
    # a different namespace (e.g. real-life) sees none of the study rules
    assert InMemoryRuleStore(backend, namespace="real-life").load() == []
