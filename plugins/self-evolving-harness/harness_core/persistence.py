"""Persistence — store evolved rules so they survive across runs.

The novel spine: neither Life-Harness (freezes evolved layers) nor Continual
Harness (resets per-episode) persists improvements across sessions. Here,
evolved rules are saved to a namespaced store and reloaded on the next run, so
gains compound.

`RuleStore` is the interface. `InMemoryRuleStore` is for tests; `FileRuleStore`
is real on-disk cross-process persistence; the production backend
(`OpenVikingRuleStore`) writes to the isolated `harness-study` OV namespace.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from harness_core.evolver import ProposedRule


def serialize_rule(rule: ProposedRule) -> dict:
    return asdict(rule)


def deserialize_rule(data: dict) -> ProposedRule:
    return ProposedRule(**data)


class RuleStore(Protocol):
    """A namespaced, cross-session store of evolved harness rules."""

    namespace: str

    def save(self, rule: ProposedRule) -> None: ...

    def load(self) -> list[ProposedRule]: ...


class InMemoryRuleStore:
    """Dict-backed store. The backend dict simulates durable cross-session
    storage: a new store instance over the same backend == a new session."""

    def __init__(self, backend: dict, namespace: str) -> None:
        self.backend = backend
        self.namespace = namespace

    def save(self, rule: ProposedRule) -> None:
        self.backend.setdefault(self.namespace, []).append(serialize_rule(rule))

    def load(self) -> list[ProposedRule]:
        return [deserialize_rule(d) for d in self.backend.get(self.namespace, [])]


class FileRuleStore:
    """JSON-file-backed store: real persistence across separate processes.
    Rules are keyed by namespace within the file, so namespaces stay isolated."""

    def __init__(self, path, namespace: str) -> None:
        self.path = Path(path)
        self.namespace = namespace

    def _read_all(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, rule: ProposedRule) -> None:
        data = self._read_all()
        data.setdefault(self.namespace, []).append(serialize_rule(rule))
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> list[ProposedRule]:
        return [deserialize_rule(d) for d in self._read_all().get(self.namespace, [])]
