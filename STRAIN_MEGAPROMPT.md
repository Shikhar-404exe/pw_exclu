# STRAIN — Agent Work Order

You are the sole engineer on the STRAIN project located at:
`c:\Users\Shikhar\OneDrive\Desktop\pw_exclu`

Read `AGENTS.md` at the repo root before writing any code. Every rule in that file is non-negotiable. Read `README.md` to understand the architecture. Run `python -m pytest tests/ -v` first to confirm the baseline is green (45/45) before touching anything.

This work order has three parts. Complete them in order. Do not skip verification steps.

---

## PART 1 — Consolidate the Real Corpus (do this first)

### 1a. Find the archive documents
Look inside `c:\Users\Shikhar\OneDrive\Desktop\pw_exclu\archive\` (or any folder at the repo root named `archive`, `docs`, `real_docs`, `corpus`, or similar). There are approximately 43 real Indian residential rental agreement documents in there (PDF, DOCX, or TXT). List them before doing anything else. If you cannot find them, report the exact paths you checked and stop Part 1 — do not fabricate documents.

### 1b. Check document quality
Before ingesting, read the text content of 3 to 5 of the documents using pdfplumber (for PDFs) or python-docx (for DOCX). Check:
- Is the extracted text coherent English (not garbled OCR)?
- Are there at least 5 recognisable clauses (rent, deposit, notice, etc.)?
- Flag any document where extracted text is shorter than 500 characters — those are likely scanned images and should be skipped.

### 1c. Ingest clean documents
For each document that passes the quality check:
1. Call the existing `ingest_and_store()` function from `strain/backend/pipeline/diagnose.py` — do NOT write a new ingestion path.
2. Mark the document `synthetic=False` in the Document table.
3. After all documents are ingested, re-run only the cheap pipeline steps (cluster, phylogeny, mutate_label, virulence). Embeddings will be cached by SHA-256 of normalised_text so re-embedding is fast.
4. Keep 5 documents out of ingestion as a held-out evaluation set (pick the last 5 alphabetically). Record their paths in `EVALUATION.md` under a new section "Real Document Held-Out Set".

### 1d. Run diagnosis on held-out set
Run `/diagnose` on each of the 5 held-out docs using the `diagnose()` function directly (not via HTTP). For each, record: clause count, classified count, average virulence score. Append results to `EVALUATION.md` under "Real-World Diagnosis Accuracy". This is the most important number in the whole evaluation.

---

## PART 2 — Reduce and Consolidate the Codebase

Perform every merge/delete below. After each merge, run `pytest tests/ -v` to confirm nothing broke before moving to the next. Do not batch all changes and test once at the end.

### 2a. Merge `store/db.py` + `store/models.py` into `store/store.py`
- Combine both files into a single `store/store.py`
- Update all imports in `main.py`, `routes.py`, `diagnose.py`, `phylogeny.py`, `cluster.py`, `embed.py`
- Delete `db.py` and `models.py`
- Keep both original files' docstrings in the merged file

### 2b. Merge `providers/embeddings.py` into `pipeline/embed.py`
- Move the `EmbeddingProvider` abstract class, `SentenceTransformerProvider`, `OfflineEmbeddingProvider`, and the cache logic directly into `embed.py`
- Remove `providers/embeddings.py`
- Update all imports (`diagnose.py` imports `get_embedding_provider`)

### 2c. Inline `providers/llm.py` into `pipeline/mutate_label.py`
- The LLM provider is only ever called by `mutate_label.py`. Move `LLMProvider` and `OfflineLabelComposer` into `mutate_label.py` as local classes
- Remove `providers/llm.py`
- Update any remaining imports

### 2d. Merge three pipeline modules into `pipeline/analyse.py`
Merge `pipeline/phylogeny.py` + `pipeline/mutate_label.py` + `pipeline/virulence.py` into a single `pipeline/analyse.py` with three public functions:
- `build_phylogeny(session)`
- `label_all_edges(session)`
- `score_all_clauses(session)`

Keep all existing logic, docstrings, and helper functions — do not simplify the algorithms. Delete the three original files. Update imports in `seed_corpus.py`, `diagnose.py`, and `routes.py`.

### 2e. Move `providers/outcomes.py` to `pipeline/outcomes.py`
Since `providers/` will now be empty, move `outcomes.py` into `pipeline/`. Delete the `providers/` directory entirely. Update imports in `diagnose.py`, `analyse.py` (virulence section), and `routes.py`.

### 2f. Delete dead files
Delete the following — they are either superseded or build artefacts:
- `scripts/ingest_real.py` (superseded by Part 1c)
- `strain/frontend/src/App.css` (overridden entirely by index.css)
- `strain/frontend/src/assets/` directory (only contains the default Vite SVG, not used)
- `backend.log` and `backend.err.log` at repo root (artefacts)
- `PLAN.md` at repo root (covered by README.md and AGENTS.md)

### 2g. Final structure verification
After all merges, the Python source tree under `strain/backend/` must look exactly like this:

```
strain/backend/
  __init__.py
  main.py
  store/
    __init__.py
    store.py
  pipeline/
    __init__.py
    segment.py
    embed.py
    cluster.py
    analyse.py
    diagnose.py
    outcomes.py
  api/
    __init__.py
    routes.py
```

Run `pytest tests/ -v`. All 45 tests must pass.

---

## PART 3 — Product Improvements (do after Parts 1 and 2)

These are ordered by impact. Stop and verify each one before moving on.

### 3a. Fix the ARI evaluation story
Open `scripts/evaluate.py`. Add a second clustering metric: Normalized Mutual Information (NMI) by clause heading. The ground truth for this metric is: clauses with the same heading keyword (deposit, notice, termination, etc.) should be in the same cluster. Use `sklearn.metrics.normalized_mutual_info_score`. Report NMI in `EVALUATION.md` alongside ARI. Add a one-paragraph explanation of why ARI is low (template family is not the same as clause semantic family) and why NMI is the more meaningful metric for this product. This turns the evaluation weakness into a documented and honest strength.

### 3b. Fix diagnosis speed via normalised-text embedding cache
In `pipeline/embed.py`, the current cache key is the SHA-256 of `normalised_text`. Verify this is working: diagnose the same sample document twice and confirm the second run completes in under 3 seconds with no model inference. If it is re-running inference, the cache load path is broken — fix it. The cache must be a dict keyed by SHA-256 hex digest, stored in `data/embedding_cache.json`.

### 3c. Promote the neutralising wording as the centrepiece
In `strain/frontend/src/components/ClauseCard.tsx`: for any clause with `virulence_score >= 60`, show the neutralising wording automatically expanded (not hidden behind a button). Use a side-by-side layout: left = current clause text with a red background tint, right = neutralising alternative with a green background tint. The `WordDiff.tsx` component already exists — use it here. This makes the product's core value proposition unmissable.

### 3d. Surface real dates in the HandoffPanel
In `pipeline/diagnose.py`, the `_build_handoff_panel()` function already extracts dates with a regex. Make it smarter:
- Also extract duration patterns like "2 months notice", "11 months", "3 months lock-in" and convert them to absolute dates by adding to the document's detected signing date (or today if none found)
- In `HandoffPanel.tsx`, if `detected_deadlines` is non-empty, show a highlighted "Key Dates" block at the very top of the panel above the risk clauses. Format each as: "Lock-in expires: ~15 March 2027 (5 months away)"

### 3e. Limit the Strain Atlas selector to top 10 strains
In `strain/frontend/src/views/StrainAtlas.tsx`, show only the top 10 strains by `clause_count` in the selector by default. Add a "Show all families" toggle below the pills that expands to show the rest. This removes the overwhelming 71-pill problem.

### 3f. Add a backend-down error state to the frontend
In `strain/frontend/src/api.ts`, add a 10-second request timeout on all calls. If any call fails with a network error (not a 4xx or 5xx), display a full-page error banner: "Backend not reachable. Run: python -m uvicorn strain.backend.main:app --port 8000" with a Retry button. Currently the app spins forever if the backend is down.

---

## Verification Checklist (run before handing back)

- [ ] `pytest tests/ -v` passes 45/45 (or more if new tests were added)
- [ ] `python scripts/evaluate.py` runs without error and writes EVALUATION.md
- [ ] `python -m uvicorn strain.backend.main:app --port 8000` starts without import errors
- [ ] `GET http://localhost:8000/health` returns status ok
- [ ] `GET http://localhost:8000/strains` returns at least 10 non-singleton strains with named families
- [ ] `GET http://localhost:8000/outbreak` returns outcome_distribution total >= 10
- [ ] `GET http://localhost:8000/samples` returns 3 samples
- [ ] `POST http://localhost:8000/diagnose` with a sample file returns clauses with virulence_scores and handoff_panel
- [ ] `cd strain/frontend && npm run build` exits 0 with no TypeScript errors
- [ ] No forbidden strings (advice, you should, we recommend, copied from, plagiarised) in frontend/src/ — confirmed by test_guardrails.py
- [ ] Real docs from archive ingested — confirmed by checking Document table synthetic=False count
- [ ] EVALUATION.md updated with real-world diagnosis accuracy results

Do not mark anything done until you have run the relevant verification step and seen passing output.
