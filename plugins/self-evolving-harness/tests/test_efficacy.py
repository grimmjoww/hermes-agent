"""PF efficacy tracking — unit test for the non-paper within-run-disable extension.

This is a HARNESS EXTENSION with no basis in Continual-Harness or HASP; it tracks
a per-PF help-rate from caller-supplied booleans and disables low-help-rate PFs.
"""
import harness_core.efficacy as efficacy_mod
from harness_core.efficacy import PFEfficacyTracker


def test_pf_with_mostly_harmful_outcomes_is_flagged_for_disable():
    t = PFEfficacyTracker(min_samples=3, help_rate_threshold=0.5)
    for helped in (False, False, False):
        t.record("pf_bad", helped)
    assert t.should_disable("pf_bad") is True


def test_pf_with_helpful_outcomes_is_kept():
    t = PFEfficacyTracker(min_samples=3, help_rate_threshold=0.5)
    for helped in (True, True, False):
        t.record("pf_good", helped)
    assert t.should_disable("pf_good") is False


def test_insufficient_samples_not_disabled():
    t = PFEfficacyTracker(min_samples=3, help_rate_threshold=0.5)
    t.record("pf_x", False)
    assert t.should_disable("pf_x") is False  # not enough evidence yet


def test_filter_active_drops_disabled_pfs():
    t = PFEfficacyTracker(min_samples=2, help_rate_threshold=0.5)
    for h in (False, False):
        t.record("bad", h)
    for h in (True, True):
        t.record("good", h)
    assert t.filter_active(["bad", "good"]) == ["good"]


def test_efficacy_docstring_marked_extension():
    """Anti-fabricated-fidelity guard: efficacy is labeled a non-paper extension
    and no longer claims it consumes HASP PFExecution records."""
    doc = efficacy_mod.__doc__ or ""
    assert "NON-PAPER EXTENSION" in doc
    assert "no basis in" in doc.lower()
    assert "PFExecution records" not in doc
