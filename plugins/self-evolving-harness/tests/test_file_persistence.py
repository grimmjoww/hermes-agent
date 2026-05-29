"""FileRuleStore — real on-disk cross-session persistence.

Proves the novel-spine claim concretely: rules written by one process are
reloaded by a *different* process (a new session), and namespaces stay
isolated on disk (study rules never leak into a real-life namespace).
The OV-backed store implements the same RuleStore interface in production.
"""
from harness_core.persistence import FileRuleStore
from harness_core.evolver import ProposedRule


def test_rules_persist_to_disk_across_instances(tmp_path):
    f = tmp_path / "rules.json"
    FileRuleStore(f, namespace="harness-study").save(
        ProposedRule("H4", "search_flights", "loop", "d")
    )
    # a brand-new instance over the same file == a new session/process
    reloaded = FileRuleStore(f, namespace="harness-study").load()
    assert len(reloaded) == 1
    assert reloaded[0].target_tool == "search_flights"


def test_namespaces_isolated_on_disk(tmp_path):
    f = tmp_path / "rules.json"
    FileRuleStore(f, namespace="harness-study").save(ProposedRule("H4", "a", "loop", "d"))
    assert FileRuleStore(f, namespace="real-life").load() == []


def test_load_missing_file_returns_empty(tmp_path):
    assert FileRuleStore(tmp_path / "nope.json", namespace="harness-study").load() == []


def test_multiple_rules_accumulate(tmp_path):
    f = tmp_path / "rules.json"
    store = FileRuleStore(f, namespace="harness-study")
    store.save(ProposedRule("H4", "a", "loop", "d"))
    store.save(ProposedRule("H2", "b", "missing_arg", "e"))
    assert len(FileRuleStore(f, namespace="harness-study").load()) == 2
