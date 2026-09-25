# STRAIN — Agent Standing Instructions

Any agent working in this repo must read and follow every rule in this file before writing any code.

---

## 1. Non-Negotiables

1. **Runs fully offline after setup.** No paid API key may be required to run the demo. Embeddings default to a local sentence-transformers model (`all-MiniLM-L6-v2`). All LLM calls route through `backend/providers/llm.py`'s `LLMProvider` interface with an `OfflineLabelComposer` fallback. The app must never hard-fail without a key.
2. **No web scraping at runtime.** Any external corpus work happens in `scripts/seed_corpus.py` (offline). The repo ships with the resulting data committed.
3. **Every claim in the UI is traceable.** No sentence may appear in the output unless it carries the source `doc_id` and `clause_id` it came from. If you cannot cite it, do not render it.
4. **Synthetic data is labelled as synthetic everywhere it appears.** Never in small print only. Use visible badges/banners.
5. **Kinship, not descent.** The product says clauses are textually related — never that one provably came from another. Use: "kinship", "related", "same family". Never: "copied from", "plagiarised".
6. **Information, not legal advice.** Every diagnosis view ends with a HandoffPanel, not a recommendation.
7. **No fabricated case law.** Court outcome data comes only from `data/outcomes.seed.json`. If a strain has no outcome record, the UI must say "no litigation history in this dataset". Never guess.
8. **No authentication, user accounts, payments, or chat interface** — ever.
9. **No LLM for clustering, lineage, virulence or diagnosis decisions.** The model segments, phrases and explains. The graph decides.
10. **Do not broaden past Indian residential rental agreements** in v1.

---

## 2. Algorithm Contract

Implement exactly this pipeline, in this order, each stage independently testable:

| Step | Module | Input → Output |
|------|--------|----------------|
| 1 | `pipeline/segment.py` | Raw doc text → `[{clause_id, doc_id, ordinal, heading, text, normalised_text}]`. Normalisation: replace party names, amounts (₹\d+), dates, addresses with `[PARTY_A]`, `[PARTY_B]`, `[AMOUNT]`, `[DATE]`, `[CITY]` tokens. |
| 2 | `pipeline/embed.py` | `normalised_text` → embedding vector. Cache by SHA-256 of `normalised_text`. |
| 3 | `pipeline/cluster.py` | Embeddings → strain clusters via HDBSCAN (cosine, `min_cluster_size=5`). Noise points → singleton strains. |
| 4 | `pipeline/phylogeny.py` | Per strain: pairwise normalised Levenshtein → MST → orient edges by document date (earlier = parent), tie-break by lower structural complexity. Output: `edges` table. |
| 5 | `pipeline/mutate_label.py` | Per edge: rule-based detectors first (deadline_shortening, obligation_flip, penalty_addition, cure_period_removal, cosmetic). `LLMProvider.phrase_label()` only to phrase, never to decide. Offline fallback = rule output as-is. |
| 6 | `pipeline/virulence.py` | Per clause variant: `asymmetry_score` (obligations per party from rule detectors) + `harshness_delta` vs strain root + `outcome_factor`. Combine → 0–100 `virulence_score`. All weights exposed in API response. No hidden weighting. |
| 7 | `pipeline/diagnose.py` | New doc → steps 1+2 → nearest-strain by centroid cosine. Distance > 0.6 → `"unclassified"` with graceful message. Attach as provisional leaf. Neutralise: find lowest-asymmetry variant in strain family, return with `source_doc_id`. |

---

## 3. Guardrail Copy Rules

These exact constraints apply to all user-facing strings in `frontend/src/`:

### 3a. Required UI elements
- **Diagnosis report header**: One-line statement that the corpus is synthetic and that relationships shown are textual kinship, not proven copying.
- **Any litigation history element**: A visible `ILLUSTRATIVE` badge. Not a tooltip. Not a footnote. A badge.
- **End of every diagnosis**: A `HandoffPanel` listing the 3 highest-risk clauses, specific questions to ask a lawyer, documents to bring, and any deadline visible in the user's document. This is the terminal output — design it as the payoff, not the apology.

### 3b. Forbidden strings (enforced by `tests/test_guardrails.py`)
The following strings must not appear anywhere in `frontend/src/` in user-facing text:
- `advice` (in any case)
- `you should`
- `we recommend`

A pytest test greps for these. It must pass before Phase 11 is complete.

### 3c. Forbidden in all code and copy, everywhere
- Fabricated case citations (judge names, docket numbers, court names)
- The words "copied from" or "plagiarised" in any output
- Any claim that the tool produces legal advice
