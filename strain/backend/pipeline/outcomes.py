"""Outcome data provider interface and seed implementation."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path


class OutcomeProvider(ABC):
    @abstractmethod
    def get_outcomes(self, strain_id: str) -> list[dict]:
        """Return outcome records for a strain family."""


class SeedOutcomeProvider(OutcomeProvider):
    """Reads from data/outcomes.seed.json. All records carry illustrative=true."""

    def __init__(self, seed_path: Path | None = None) -> None:
        if seed_path is None:
            seed_path = Path(__file__).resolve().parents[3] / "data" / "outcomes.seed.json"
        self._seed_path = seed_path
        self._data: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._seed_path.exists():
            with open(self._seed_path, encoding="utf-8") as f:
                self._data = json.load(f)

    def get_outcomes(self, strain_id: str) -> list[dict]:
        """
        Match outcomes by clause_family.
        strain_id can be an exact match or a family name substring match.
        All returned records are illustrative.
        """
        results = []
        for record in self._data:
            family = record.get("clause_family", "")
            if strain_id in family or family in strain_id:
                r = dict(record)
                r["illustrative"] = True
                results.append(r)
        return results

    def get_all(self) -> list[dict]:
        return [dict(r, illustrative=True) for r in self._data]
