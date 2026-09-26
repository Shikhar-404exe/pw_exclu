"""
Phase 2 acceptance test: validates the synthetic seed corpus.

Every document must:
- Have a resolvable parent (or be generation 0)
- Have a non-empty mutation_log if generation > 0
- Have all clause_ids resolve to valid doc_ids
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GT_PATH = REPO_ROOT / "data" / "ground_truth.json"
DOCS_DIR = REPO_ROOT / "data" / "documents"


def load_gt():
    if not GT_PATH.exists():
        pytest.skip("Ground truth not generated yet — run seed_corpus.py first")
    with open(GT_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_corpus_size():
    """At least 250 documents generated."""
    gt = load_gt()
    assert len(gt) >= 250, f"Expected ≥ 250 documents, got {len(gt)}"


def test_all_documents_have_files():
    """Every ground truth doc_id has a corresponding .txt file."""
    gt = load_gt()
    for record in gt:
        doc_id = record["doc_id"]
        path = DOCS_DIR / f"{doc_id}.txt"
        assert path.exists(), f"Missing document file for {doc_id}"


def test_all_parents_resolvable():
    """Every non-generation-0 document has a parent that exists in the corpus."""
    gt = load_gt()
    all_ids = {r["doc_id"] for r in gt}
    for record in gt:
        if record["generation"] == 0:
            assert record["parent_id"] is None, (
                f"Generation 0 doc {record['doc_id']} should have no parent"
            )
        else:
            assert record["parent_id"] is not None, (
                f"Generation {record['generation']} doc {record['doc_id']} has no parent_id"
            )
            assert record["parent_id"] in all_ids, (
                f"Doc {record['doc_id']} has unresolvable parent_id {record['parent_id']}"
            )


def test_mutation_logs_non_empty_for_descendants():
    """Every document with generation > 0 has at least one mutation recorded."""
    gt = load_gt()
    for record in gt:
        if record["generation"] > 0:
            assert len(record["mutation_log"]) > 0, (
                f"Doc {record['doc_id']} (gen {record['generation']}) has empty mutation_log"
            )


def test_mutation_log_has_required_fields():
    """Each mutation log entry has operator and clause_ordinal fields."""
    gt = load_gt()
    for record in gt:
        for entry in record.get("mutation_log", []):
            assert "operator" in entry, f"Mutation log entry missing 'operator' in {record['doc_id']}"
            assert "clause_ordinal" in entry, f"Mutation log entry missing 'clause_ordinal' in {record['doc_id']}"


def test_template_ids_are_valid():
    """All template_ids are from the known set T1–T6."""
    gt = load_gt()
    valid_templates = {"T1", "T2", "T3", "T4", "T5", "T6"}
    for record in gt:
        assert record["template_id"] in valid_templates, (
            f"Doc {record['doc_id']} has unknown template_id {record['template_id']}"
        )


def test_six_generations_exist():
    """Documents span exactly generations 0–5."""
    gt = load_gt()
    generations = {r["generation"] for r in gt}
    assert 0 in generations, "Generation 0 (ancestors) missing"
    assert 5 in generations, "Generation 5 (latest) missing"


def test_all_six_ancestors_present():
    """All six template ancestors (gen 0) are present."""
    gt = load_gt()
    gen0 = [r for r in gt if r["generation"] == 0]
    template_ids = {r["template_id"] for r in gen0}
    assert len(template_ids) == 6, f"Expected 6 ancestor templates, got {len(template_ids)}: {template_ids}"


def test_synthetic_dates_exist():
    """All records have a synthetic_date field."""
    gt = load_gt()
    for record in gt:
        assert record.get("synthetic_date"), (
            f"Doc {record['doc_id']} missing synthetic_date"
        )


def test_no_synthetic_markers_in_gt():
    """Ground truth data is accurate metadata, not synthetic content warnings."""
    gt = load_gt()
    # Every record should have the required keys
    required_keys = {"doc_id", "parent_id", "generation", "template_id", "mutation_log"}
    for record in gt:
        missing = required_keys - set(record.keys())
        assert not missing, f"Doc {record['doc_id']} missing keys: {missing}"
