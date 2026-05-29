"""H5 Procedural Skill — retrieve + inject relevant skills at episode start.

Life-Harness used BM25 over a hand-written skill corpus. Our production layer
backs this with OpenViking semantic recall, but the retrieval/selection logic
is a pure function tested here: given a corpus and a query, return the most
relevant skills and format them for injection.
"""
from harness_core.layers.h5_procedural_skill import Skill, retrieve_skills, format_skills_block

CORPUS = [
    Skill("refund_policy", "To process a refund, verify the booking then call issue_refund."),
    Skill("baggage", "Baggage fees depend on cabin class and route."),
    Skill("seat_change", "Seat changes require checking availability before confirming."),
]


def test_retrieves_most_relevant_skill_for_query():
    out = retrieve_skills(CORPUS, "how do I process a refund", top_k=1)
    assert len(out) == 1
    assert out[0].name == "refund_policy"


def test_top_k_limits_number_returned():
    out = retrieve_skills(CORPUS, "refund baggage seat", top_k=2)
    assert len(out) == 2


def test_irrelevant_query_returns_empty():
    out = retrieve_skills(CORPUS, "zzz nonexistent xyzzy", top_k=3)
    assert out == []


def test_format_block_includes_skill_content():
    block = format_skills_block([CORPUS[0]])
    assert "issue_refund" in block
