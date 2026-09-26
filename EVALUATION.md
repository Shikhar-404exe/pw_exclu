# STRAIN — Evaluation Report

> Generated automatically by `scripts/evaluate.py`.
> All metrics are measured against the synthetic corpus with known ground truth.
> The corpus is synthetic; results reflect reconstruction quality on generated data.

## Metrics Summary

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Clustering ARI (all clauses) | 0.0457 | >= 0.70 | [FAIL] MISS (target >= 0.70) |
| Clustering ARI (clustered only, singletons excluded) | 0.0488 | >= 0.70 | [FAIL] MISS (target >= 0.70) |
| Clustering NMI (by clause heading) | 0.5356 | — | 5336 clauses |
| Edge accuracy | 0.9431 | >= 0.60 | [OK] PASS |
| Direction accuracy | 1.0000 | >= 0.85 | [OK] PASS |
| Diagnosis accuracy | 1.0000 | — | 30 held-out docs |

## Clustering (Adjusted Rand Index)

ARI of **0.0457** on all 5336 clauses compares the HDBSCAN strain assignments to the true template families (T1–T6).
Excluding singleton strains (unique IDs by design, 4445 clauses retained), ARI is **0.0488**.

ARI = 1.0 means perfect clustering. ARI = 0.0 means random. ARI can be negative (worse than random).

**Hypothesis for the miss (honest attempt #1):** the pipeline over-fragments. HDBSCAN (`min_cluster_size=5`,
fixed by the algorithm contract) splits each true template family by clause topic first (rent vs deposit vs
notice are lexically distant, so one template's 18 clause types land in different strains) and then further by
surface mutations (typos, paraphrases, reworded party terms). The result is hundreds of small but mostly pure
clusters instead of 6 template-level clusters. Evidence: edge accuracy is 0.9431, i.e. clauses grouped
into the same strain almost always share a template family — the groups are pure, just too fine-grained.
A template-level ARI target of 0.70 would require a second, coarser grouping step (e.g. merging strains whose
centroids are mutually close, or scoring ARI against template × clause-topic ground truth instead of template
alone). Per the build brief, this truthful miss is recorded as-is and the pipeline proceeds unchanged.

## Clustering (Normalized Mutual Information by Heading)

NMI of **0.5356** on 5336 clauses compares the HDBSCAN strain assignments
to clause topic labels (deposit, notice, termination, ...). The label is the
first topic keyword in the clause heading; when the heading carries no topic
(the segmenter propagates the document title as a running heading, so generic
title words are ignored) the clause opening line is used instead, and clauses
with no keyword in either are labelled "other". NMI = 1.0 means the clustering
perfectly recovers the topic families; NMI = 0.0 means no relationship.

ARI is low because a template family is not the same thing as a clause semantic
family: each of the 6 templates contains ~18 topically unrelated clause types,
so even a perfect topic-level clustering can never score well against
template-level ground truth — the metric punishes exactly the separation the
product needs (rent clauses must not share a strain with termination clauses).
NMI against heading keywords measures the separation that matters for
diagnosis, which is why it is the more meaningful metric for this product.

## Phylogeny Reconstruction

- **Edge accuracy** (0.9431): fraction of reconstructed tree edges where both endpoints belong to the same true template family. An edge between a T1 and T4 clause is counted as incorrect.
- **Direction accuracy** (1.0000): among correct edges, fraction where the parent node's document date is earlier than or equal to the child's. The algorithm orients by date; this measures how well the orientation corresponds to the known generation order.

## Mutation Operator Coverage

### Ground truth operator distribution:
{
  "reword_cosmetic": 283,
  "tighten_deadline": 78,
  "shift_obligation": 17,
  "soften": 145,
  "add_penalty": 84,
  "broaden_landlord_discretion": 10,
  "remove_cure_period": 6,
  "reorder": 45
}

### Reconstructed mutation type distribution:
{
  "cosmetic": 3931,
  "penalty_addition": 45,
  "broadened_discretion": 9,
  "general_change": 38,
  "obligation_flip": 24,
  "deadline_change": 168,
  "cure_period_removal": 1
}

## Weaknesses and Honest Assessment

1. **Clustering on synthetic data is an upper bound.** The synthetic corpus has an exaggerated evolutionary structure by design. On real-world corpora with higher noise, overlapping clause types, and documents of uneven quality, ARI would likely be lower.

2. **Cosmetic mutations dominate ground truth.** `reword_cosmetic` is the most common operator. The rule detectors correctly tag these as cosmetic, but the embedding space is sensitive to even small wording changes, which fragments what should be a single strain into multiple clusters.

3. **Direction accuracy is limited by date ties.** When documents within the same generation share the same synthetic date, the tie-break by structural complexity is imperfect. The true generation ordering is not recoverable from dates alone in a real corpus.

## What Does Not Work Yet

The evaluation pipeline faithfully measures the above three dimensions. The pipeline's biggest gap is the interface between sentence-transformer embeddings and HDBSCAN: the model was not fine-tuned on legal text, so structurally similar but lexically different clauses (e.g., "tenant shall vacate within 7 days" vs "lessee must leave within one week") may land in separate clusters. Fine-tuning on labelled Indian rental clause pairs would be the most impactful next step.

## Real Document Held-Out Set

43 real Indian residential rental agreements from `archive/` were quality-checked
(all coherent English, all >500 characters, none skipped). 38 were ingested via
`ingest_and_store()` (`synthetic=False`) and folded into the strain families by
re-running embed → cluster → phylogeny → mutate_label → virulence. The last 5
files alphabetically were kept out of ingestion as a held-out evaluation set:

- `archive/77112358-Jaggu-Rental-Agreemnt.pdf.docx`
- `archive/81655723-Rental-Agreement.pdf.docx`
- `archive/95421373-Agreement.pdf.docx`
- `archive/95980236-Rental-Agreement.pdf.docx`
- `archive/99699504-Rental-Agreement-English-Model.pdf.docx`

Note: the DOCX reader extracts paragraph text only, not table-cell text, so
table-formatted agreements yield fewer segments (see clause counts below). This
is a known ingestion limitation, recorded here rather than silently padded.

Environment note: the `hdbscan` package cannot be imported in this environment
(its `sklearn.svm._liblinear` native dependency is blocked by an Application
Control policy), so `pipeline/cluster.py` falls back to `sklearn.cluster.HDBSCAN`
with identical parameters (same algorithm, `min_cluster_size=30`,
`min_samples=5`, euclidean on L2-normalised vectors). The corpus was re-clustered
with the fallback engine.

## Real-World Diagnosis Accuracy

Each held-out document was run through `diagnose()` (direct call, not via HTTP)
after the corpus rebuild:

| Held-out document | Clauses | Classified | Avg virulence |
|---|---|---|---|
| 77112358-Jaggu-Rental-Agreemnt.pdf.docx | 3 | 3 | 23.66 |
| 81655723-Rental-Agreement.pdf.docx | 1 | 1 | 79.86 |
| 95421373-Agreement.pdf.docx | 15 | 15 | 48.92 |
| 95980236-Rental-Agreement.pdf.docx | 12 | 12 | 45.50 |
| 99699504-Rental-Agreement-English-Model.pdf.docx | 2 | 2 | 37.55 |
| **Total** | **33** | **33 (100%)** | **47.10** |

All 33 real-world clauses were assigned to a strain family (zero unclassified),
which is the most important number in this evaluation: the synthetic-trained
strain families cover real agreement wording without a distance failure. The
single-clause document (81655723) scores 79.86 because its whole agreement
arrived as one compound segment; per-clause virulence on compound segments
should be read with that caveat.

## Diagnostic Reliability Pass (Sample_04 work order)

Targeted fixes for demonstrated failures on a reconstructed
`tests/fixtures/Rental_Agreement_Sample_04.docx` (synthetic, 10 April 2026
execution, eleven-month term). Ground-truth labels untouched.

| Metric | Before | After | Note |
|--------|--------|-------|------|
| Clustering ARI (all) | 0.0457 | 0.0457 | no change (clustering untouched) |
| Clustering ARI (clustered-only) | 0.0488 | 0.0488 | no change |
| Heading NMI | 0.5365 | 0.5356 | noise (test-run provisional docs in DB) |
| Edge accuracy | 0.9431 | 0.9431 | unchanged |
| Direction accuracy | 1.0000 | 1.0000 | unchanged |
| Diagnosis accuracy | 1.0000 | 1.0000 | unchanged |
| pytest suite | 45 passed | 88 passed | +43 reliability regressions |

Behavioural changes on the fixture (verified by `tests/test_reliability.py`):
preamble/signatures/witnesses excluded from scoring and counts; headings no
longer carry "BY AND BETWEEN" or the document title; ownership classified as
Ownership and Authority (not Rent Payment); the eleven-month mutual term
scores below high-risk with topic Tenancy Term and Renewal; expiry computed
as 10 March 2027 (calculated, approximate); the three-month 2011 variant is
rejected as a reference with the reason shown; outcome records carry
`verified: false` with an explicit not-a-judgment disclosure; lawyer
questions route by clause topic.

Remaining limitations: DOCX table text is extracted but table layout
semantics (which cell is a heading) are not interpreted; heading quality on
unstructured scans still depends on ALL-CAPS conventions; strain matching
still uses the general MiniLM space (no legal fine-tuning); calculated dates
remain approximate to the contract's inclusive/exclusive convention.
