"""Mimir M-provider — the MEMORY component of the composition.

Continual-Harness Refiner = PROPOSER -> HASP harness_core = GATE + RUNTIME ->
**Mimir (OV + Hindsight consolidation) = MEMORY (M-provider)**.

SEAM CONTRACT (the whole point of this package):
  Three Protocols, with WRITER and READER kept as SEPARATELY swappable
  sub-components so SAGE's Phase-2 GRPO-trained writer and GFM-based reader drop
  in later behind the SAME interface, with NO change to the agent-facing API.

    * MemoryWriter  — extract(history) -> records ; write(records) -> ids
    * MemoryReader  — recall(query, k) -> RecallResult (TopK docs + optional
                      subgraph / relational paths)
    * MemoryProvider — composes a writer + a reader; exposes ingest / recall /
                      register_proof (Hindsight-style proof_count feedback).

PHASE-2 SWAP-INS (SAGE, arXiv 2605.12061) — OUT OF SCOPE for Phase-1:
  1. GRPO writer policy (sequential triple emission, clipped GRPO, hybrid reward
     r_task = (a*r_rec + b*r_pre + g*r_ded)/(a+b+g) + aux r_ans)
  2. GFM reader (Graph Foundation Model: entity/doc distributions, query subgraph)
  3. Writer-Reader self-evolution (Algorithm 1: alternate fix-reader/train-writer)
  4. structural contrastive pretrain + SFT for the reader
  --- OUT OF SCOPE PHASE-1: no GPU, no training, no graph model. ---

HONESTY: K=256 / pairwise reward R in [0,1] / teacher-relabel / soft-SFT are
CHARTER co-learning design notes, NOT SAGE-paper equations, and are NOT part of
this contract. The seam stays training-agnostic so any future writer conforms.

OV hierarchy (dont_undo_migration_premise): records carry an L0/L1/L2-compatible
metadata slot which the provider never flattens — Mimir must not bypass the
OV hierarchy that motivated the migration.
"""
from harness_core.memory.provider import (
    InMemoryMemoryProvider,
    MemoryProvider,
    MemoryReader,
    MemoryRecord,
    MemoryWriter,
    RecallHit,
    RecallResult,
    StubReader,
    StubWriter,
)

__all__ = [
    "MemoryRecord",
    "RecallHit",
    "RecallResult",
    "MemoryWriter",
    "MemoryReader",
    "MemoryProvider",
    "StubWriter",
    "StubReader",
    "InMemoryMemoryProvider",
]
