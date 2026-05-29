"""Mimir MemoryProvider — Phase-1 contract + reference stub.

This module defines the SEAM (three Protocols) plus ONE in-memory reference
implementation that satisfies the contract. The real OV-backed Mimir and the
SAGE GRPO-writer / GFM-reader land LATER behind the IDENTICAL Protocols.

Faithful to SAGE (arXiv 2605.12061) at the INTERFACE level only:
  * Writer = a policy that turns an interaction window into structured records.
    SAGE's writer emits entity-relation triples (u, r, v) with source anchors,
    trained with clipped GRPO. Phase-1 stub does deterministic text extraction,
    NO training. The MemoryRecord models a triple so the graph writer can
    populate it later with no schema change.
  * Reader = SAGE's Graph Foundation Model returning TopK doc distribution
    D_hat_k, a query-activated subgraph G_hat_q and optional relational paths
    Pi_q. Phase-1 stub does substring ranking; the RecallResult exposes the
    graph fields (empty for the stub) so the GFM populates them with no
    interface change.

OUT OF SCOPE PHASE-1: GRPO, the GFM, graph training, GPU. The seam is the fact
that writer and reader are INDEPENDENTLY swappable behind the provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# --- The substrate-neutral unit both writer and reader move -------------------

@dataclass
class MemoryRecord:
    """One memory unit.

    `content` is the plain text (always present). `triple` optionally holds a
    SAGE-style (subject, relation, object) graph edge with `source` anchors —
    representable now so the GRPO writer can populate it later with no schema
    change. `metadata['level']` preserves the OV L0/L1/L2 hierarchy slot and is
    never flattened/stripped on recall (dont_undo_migration_premise).
    """

    id: str
    content: str
    kind: str = "episodic"
    triple: tuple[str, str, str] | None = None
    source: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    proof_count: int = 0


@dataclass
class RecallHit:
    record_id: str
    content: str
    score: float


@dataclass
class RecallResult:
    """SAGE reader output shape.

    `hits` = ranked docs (D_hat_k = TopK). `subgraph` (G_hat_q) and
    `relational_paths` (Pi_q) are PRESENT in the type but empty for the
    non-graph stub — the GFM reader populates them later with no interface
    change.
    """

    hits: list[RecallHit] = field(default_factory=list)
    subgraph: object | None = None       # SAGE G_hat_q (None for the stub)
    relational_paths: list = field(default_factory=list)  # SAGE Pi_q (empty for the stub)


# --- The two independently-swappable sub-component Protocols -------------------

@runtime_checkable
class MemoryWriter(Protocol):
    """The GRPO-writer seam. Phase-2 SAGE writer is a sequential policy trained
    with clipped GRPO; Phase-1 stub does deterministic extraction (no training).
    `extract` is the learned-decision boundary; `write` is durable substrate I/O
    — kept separate so the GPU-trained part is isolated to extract()."""

    def extract(self, interaction_history: list[str]) -> list[MemoryRecord]: ...

    def write(self, records: list[MemoryRecord]) -> list[str]: ...


@runtime_checkable
class MemoryReader(Protocol):
    """The GFM-reader seam. Phase-2 SAGE reader is a Graph Foundation Model;
    Phase-1 stub does substring-embedding-free ranking over the same records."""

    def recall(self, query: str, k: int) -> RecallResult: ...


# --- Phase-1 reference stubs (deterministic, zero ML deps) --------------------

class StubWriter:
    """Deterministic writer: one record per history item. NO training, NO GPU."""

    def __init__(self, store: dict[str, MemoryRecord], level: str = "L1") -> None:
        self._store = store
        self._level = level
        self._counter = 0

    def extract(self, interaction_history: list[str]) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for item in interaction_history:
            self._counter += 1
            records.append(
                MemoryRecord(
                    id=f"rec-{self._counter}",
                    content=item,
                    metadata={"level": self._level},  # preserve OV hierarchy slot
                )
            )
        return records

    def write(self, records: list[MemoryRecord]) -> list[str]:
        ids: list[str] = []
        for rec in records:
            self._store[rec.id] = rec
            ids.append(rec.id)
        return ids


class StubReader:
    """Substring-ranking reader: score by query-term overlap. NO GFM, NO GPU."""

    def __init__(self, store: dict[str, MemoryRecord]) -> None:
        self._store = store

    def recall(self, query: str, k: int) -> RecallResult:
        q_terms = set(query.lower().split())
        scored: list[RecallHit] = []
        for rec in self._store.values():
            content_terms = set(rec.content.lower().split())
            overlap = len(q_terms & content_terms)
            if overlap > 0:
                score = overlap / max(len(q_terms), 1)
                scored.append(RecallHit(rec.id, rec.content, score))
        scored.sort(key=lambda h: (-h.score, h.record_id))
        return RecallResult(hits=scored[:k])  # D_hat_k = TopK; subgraph/paths empty


# --- The MemoryProvider: composes writer + reader -----------------------------

class MemoryProvider:
    """Mimir M-provider. Holds a writer and a reader as SEPARATE swappable
    attributes (`self.writer`, `self.reader`) so SAGE drops each in
    independently behind the same provider.

    Agent-facing API:
      * ingest(history)        — writer.extract + writer.write
      * recall(query, k)       — reader.recall
      * register_proof(id)     — Hindsight-style consolidation feedback:
                                 increments that record's proof_count.
    """

    def __init__(self, writer: MemoryWriter, reader: MemoryReader,
                 store: dict[str, MemoryRecord]) -> None:
        self.writer = writer
        self.reader = reader
        self._store = store

    def ingest(self, interaction_history: list[str]) -> list[str]:
        records = self.writer.extract(interaction_history)
        return self.writer.write(records)

    def recall(self, query: str, k: int = 5) -> RecallResult:
        return self.reader.recall(query, k)

    def register_proof(self, record_id: str) -> int:
        """Hindsight-style proof_count feedback: a record that proved useful gets
        its proof_count incremented. Returns the new count."""
        rec = self._store.get(record_id)
        if rec is None:
            raise KeyError(record_id)
        rec.proof_count += 1
        return rec.proof_count

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._store.get(record_id)


class InMemoryMemoryProvider(MemoryProvider):
    """The Phase-1 contract reference impl: dict-backed, wired with StubWriter +
    StubReader over a shared store (mirrors InMemoryRuleStore's test substrate).
    The real OV-backed MimirProvider + SAGE writer/reader are LATER, behind the
    identical Protocols.
    """

    def __init__(self, level: str = "L1") -> None:
        store: dict[str, MemoryRecord] = {}
        super().__init__(
            writer=StubWriter(store, level=level),
            reader=StubReader(store),
            store=store,
        )
