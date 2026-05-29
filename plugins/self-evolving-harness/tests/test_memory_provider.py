"""Mimir MemoryProvider CONTRACT tests (Phase-1 seam — Task 6 / Agent D).

These assert the MemoryProvider CONTRACT (round-trip write->recall, proof_count
increments, writer/reader independently swappable) — NOT SAGE training. SAGE's
GRPO writer + GFM reader are Phase-2 GPU swap-ins behind the SAME interface.

Paper-faithfulness / honesty:
  * The seam stays training-agnostic. No K=256 / pairwise reward / teacher-relabel
    / soft-SFT is a required behavior of the contract — those are charter notes,
    not SAGE-paper terms.
  * OUT OF SCOPE PHASE-1: GPU, training, graph model. The contract is exercised
    with ZERO ML/torch imports and no model load.
"""
from __future__ import annotations

from harness_core.memory import (
    InMemoryMemoryProvider,
    MemoryReader,
    MemoryRecord,
    RecallResult,
    StubReader,
)


def test_memory_provider_round_trip_write_then_recall():
    """Charter DoD: round-trip write->recall."""
    provider = InMemoryMemoryProvider()
    ids = provider.ingest(["agent searched flights 3x in a loop"])
    assert len(ids) == 1

    result = provider.recall("flights loop", k=5)
    assert isinstance(result, RecallResult)
    assert len(result.hits) >= 1
    hit = result.hits[0]
    assert hit.record_id == ids[0]
    # content round-trips intact
    assert provider.get(hit.record_id).content == "agent searched flights 3x in a loop"


def test_recall_returns_topk_ranked_not_more_than_k():
    """SAGE D_hat_k = TopK_d(s_D(d)) shape, without requiring the GFM."""
    provider = InMemoryMemoryProvider()
    provider.ingest([f"flights record number {i}" for i in range(10)])
    result = provider.recall("flights record", k=3)
    assert len(result.hits) <= 3
    # descending score order
    scores = [h.score for h in result.hits]
    assert scores == sorted(scores, reverse=True)


def test_proof_count_increments_on_register_proof():
    """Charter DoD: proof_count increments (Hindsight-style consolidation feedback)."""
    provider = InMemoryMemoryProvider()
    [rid] = provider.ingest(["a useful memory"])
    assert provider.get(rid).proof_count == 0
    assert provider.register_proof(rid) == 1
    assert provider.get(rid).proof_count == 1
    assert provider.register_proof(rid) == 2
    assert provider.get(rid).proof_count == 2


def test_writer_and_reader_are_independently_swappable():
    """The load-bearing seam test: swap the READER for another instance
    implementing the SAME MemoryReader Protocol; recall still satisfies the
    contract WITHOUT touching the provider or agent code. Proves SAGE's GFM
    reader (and symmetrically a GRPO writer) drops in behind the same interface.
    """
    provider = InMemoryMemoryProvider()
    provider.ingest(["graph memory about retries"])

    # a second, distinct reader over the SAME store, conforming to the Protocol
    new_reader = StubReader(provider._store)
    assert isinstance(new_reader, MemoryReader)
    provider.reader = new_reader  # hot-swap the reader sub-component

    result = provider.recall("retries", k=5)
    assert len(result.hits) >= 1
    assert "retries" in result.hits[0].content


def test_recall_result_exposes_graph_fields_optional():
    """SAGE G_hat_q / Pi_q fields PRESENT in the type but empty for the stub —
    so the GFM reader populates them later with no interface change."""
    provider = InMemoryMemoryProvider()
    provider.ingest(["something"])
    result = provider.recall("something", k=1)
    assert hasattr(result, "subgraph")
    assert hasattr(result, "relational_paths")
    assert result.subgraph is None
    assert result.relational_paths == []


def test_contract_does_not_require_training_or_gpu():
    """Hard rule: Phase-1 is interface+contract only. Constructed and exercised
    with ZERO ML/torch imports and no model load."""
    import sys
    provider = InMemoryMemoryProvider()
    provider.ingest(["fast no-model path"])
    provider.recall("fast", k=1)
    # no heavy ML libs were pulled in by the memory package
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_l0_l1_l2_hierarchy_preserved_in_record_metadata():
    """Guards dont_undo_migration_premise: records carry an OV-hierarchy slot
    and the provider never flattens/strips it on recall."""
    provider = InMemoryMemoryProvider(level="L2")
    [rid] = provider.ingest(["hierarchical memory"])
    rec = provider.get(rid)
    assert rec.metadata.get("level") == "L2"
    # recall does not strip the hierarchy
    result = provider.recall("hierarchical", k=1)
    assert provider.get(result.hits[0].record_id).metadata.get("level") == "L2"


def test_record_models_a_graph_triple_for_sage_writer():
    """MemoryRecord can hold a SAGE (u, r, v) triple + source anchors so the
    GRPO writer populates structured graph memory later with no schema change."""
    rec = MemoryRecord(
        id="t1",
        content="Alice works_at Acme",
        triple=("Alice", "works_at", "Acme"),
        source=["doc-3"],
    )
    assert rec.triple == ("Alice", "works_at", "Acme")
    assert rec.source == ["doc-3"]


def test_no_sage_training_terms_in_contract():
    """HONESTY (assertion-by-absence): the MemoryProvider contract MUST NOT
    reference K=256 / pairwise reward / teacher-relabel / soft-SFT as required
    behavior. The seam stays training-agnostic so any future writer conforms.
    """
    import inspect
    from harness_core.memory import provider as mod

    src = inspect.getsource(mod)
    # No required-behavior training knobs leak into the contract surface
    # (the module docstring may MENTION them as out-of-scope notes, but no API
    #  field/param/method enforces them).
    lowered = src.lower()
    # these must not appear as code identifiers / parameters
    assert "soft_sft" not in lowered
    assert "teacher_relabel" not in lowered
    assert "pairwise_reward" not in lowered
    # K=256 must not be a hardcoded constant
    assert "256" not in src
