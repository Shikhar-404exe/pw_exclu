# STRAIN

> A diagnostic tool that treats unfair rental contract clauses as a communicable disease.

STRAIN identifies which known "strain" each clause in your document resembles, how that wording mutated from milder ancestors, how harsh it scores 0–100, and what fairer reference wording exists in the same family. Built for **Indian residential rental agreements**. Every diagnosis ends with a handoff panel — top risks, lawyer questions, key dates — because the tool informs; a qualified lawyer advises.

**The corpus is synthetic.** Relationships shown are textual kinship, not proven copying. Litigation records are illustrative scenarios, never verified judgments.

---

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install frontend dependencies
cd strain/frontend && npm install && cd ../..

# 3. Generate synthetic corpus + build database (downloads ~90 MB model on first run)
python scripts/seed_corpus.py

# 4. Start the app (both backend + frontend)
make demo

# 5. Open browser
# Backend:  http://localhost:8000  (API under /api/*)
# Frontend: http://localhost:5173
```

> **First run**: `seed_corpus.py` downloads `all-MiniLM-L6-v2` from HuggingFace (~90 MB) and caches it locally. All subsequent runs are fully offline — no API key, no paid service, no external calls.

| Command | What it does |
|---------|--------------|
| `make backend` | FastAPI on :8000 (serves API + production SPA build) |
| `make frontend` | Vite dev server on :5173 |
| `make demo` | Seed corpus (if needed) + start both servers |
| `make test` | pytest suite (88 tests) |
| `make evaluate` | `scripts/evaluate.py` → regenerates `EVALUATION.md` (gitignored build output) |
| `make seed` | Re-generate synthetic corpus (clears existing DB) |

---

## Features

- **Diagnose** — Upload/paste a PDF, DOCX, or TXT agreement (or try a sample). Each operative clause gets a topic label (16-topic taxonomy: term, rent, deposit, termination, eviction, penalties, repairs, utilities, access, subletting, use, ownership, disputes, schedule…), a strain-family match with confidence, and an evidence-backed 0–100 score (asymmetry + harshness-vs-root + outcome, weights 0.4/0.4/0.2, all exposed). Preambles, signatures, witnesses, and schedules are identified and **not scored**.
- **Reference wording, honestly gated** — Clauses scoring 60+ auto-expand a side-by-side: current text vs a lower-risk variant from the same family with a word diff. A candidate is shown only if it shares the topic, is textually similar, beats the source score, and preserves material terms (duration, amounts, notice/cure, penalties, parties); otherwise the panel says plainly that none was found.
- **Key dates** — Execution/commencement typed as what they are (never as deadlines); tenancy expiry calculated from term length against the execution anchor (e.g. 11 months from 10 April 2026 → ~10 March 2027, marked approximate); notice/cure periods without an anchor stay honestly unresolved.
- **Strain Atlas** — D3 phylogeny per clause family: how wording mutated across generations, your clauses highlighted, click any node for a parent word-diff.
- **Outbreak Dashboard** — Corpus-level prevalence, harshness trends, illustrative outcome distribution, strain growth.
- **Handoff panel** — Top-3 risks with topic-routed lawyer questions, documents to bring, key dates, referral note.

---

## How it works

```
raw doc → segment → embed → nearest strain → virulence → report
              │        │           │               │
           topics   SHA-256     cosine dist    evidence +
           +kinds   cache       (0.6 gate)     confidence
```

- `pipeline/segment.py` — extraction (incl. DOCX tables), preamble/signature splitting, normalisation (`[PARTY_A]`, `[AMOUNT]`, `[DATE]`, `[CITY]`), topic + component-kind classification.
- `pipeline/embed.py` — local MiniLM embeddings, disk-cached by text hash.
- `pipeline/cluster.py` — HDBSCAN strain families (sklearn fallback with identical params).
- `pipeline/analyse.py` — MST phylogeny oriented by date, rule-based mutation labels (LLM phrases only, never decides), evidence-based virulence.
- `pipeline/diagnose.py` — full diagnosis + handoff; new clauses attach as provisional leaves without rewriting history.
- `store/store.py` — SQLite/SQLModel tables; `api/routes.py` — `/api/health`, `/diagnose`, `/ingest`, `/strains`, `/strain/{id}`, `/outbreak`, `/samples`.

---

## Evaluation (latest, from `make evaluate`)

| Metric | Value | Target |
|--------|-------|--------|
| Clustering ARI (all / clustered-only) | 0.0457 / 0.0488 | ≥ 0.70 (known miss, documented) |
| Topic NMI | 0.5356 | — (the meaningful clustering metric) |
| Edge accuracy / direction accuracy | 0.9431 / 1.0000 | ≥ 0.60 / ≥ 0.85 |
| Held-out diagnosis accuracy | 1.0000 | — |
| Real held-out docs (5 archive files) | 33/33 clauses classified | — |
| pytest | 88 passed | — |

ARI is low because each synthetic template holds ~18 unrelated clause topics — template-level ARI punishes exactly the topic separation diagnosis needs. See `tests/test_reliability.py` (43 regression tests incl. an end-to-end Sample_04 fixture) for behavioural guarantees.

---

## 3-minute demo

1. `make demo`, open :5173. Note the nav (Diagnose / Strain Atlas / Outbreak) and the always-visible Synthetic Corpus badge.
2. **Diagnose** → Load samples → *Sample Landlord Aggressive*: stats row, top clause's three-component breakdown, an ILLUSTRATIVE litigation record, and the auto-expanded reference wording with word diff.
3. **Strain Atlas** → pick Security Deposit: tree coloured by risk, your clauses glowing, click a node for the parent diff.
4. **Outbreak** → prevalence, harshness trend (T4 climbs), outcomes, growth.
5. Back to **Diagnosis** → scroll to *Take This to a Lawyer*: top-3 risks, questions, documents, key dates.

---

## Problem-statement alignment (AI for Legal Assistance & Access)

| Problem-statement need | Where STRAIN meets it |
|---|---|
| Simplifying complex legal documents | Plain-topic labels, 0–100 scores with shown evidence, word-level diffs |
| Comparing contracts and agreements | Strain Atlas: same clause across generations side by side |
| Highlighting clauses, obligations, risks | Risk-ranked clause cards; top-3 handoff; Key Dates |
| Answering questions based on documents | Per-clause evidence panels + topic-routed lawyer questions |
| Understanding options and next steps | Reference wording comparison; documents-to-bring checklist |
| Generating summaries, checklists, actionable outputs | Handoff panel (risks, questions, dates, checklist) |
| Preparing for a legal professional | Copy/paste-ready report scoped to the riskiest clauses |
| Information, not advice | No recommendations; referral note + guardrail-tested copy |

GenAI in this submission: local MiniLM embeddings match clauses to families; an optional LLM only phrases mutation labels (never decides them), defaulting to a fully offline composer. Built with Antigravity, an AI coding assistant, across pipeline, UI, tests, and deployment.

---

## Operating rules (non-negotiable)

- Offline-first after setup; no key may ever be required.
- Every UI claim traces to a `doc_id` + `clause_id`; synthetic data is labelled everywhere.
- Kinship language only ("related", "same family") — never "copied" / "plagiarised".
- Information, not legal advice: no `advice` / `you should` / `we recommend` in UI copy (enforced by `test_guardrails.py`).
- Outcomes come only from `data/outcomes.seed.json`, always disclosed as illustrative with no verified source claimed.
- Indian residential rentals only (v1); out-of-scope geography is flagged, not blocked.

---

## Project layout

```
strain/backend/   main.py  api/routes.py  pipeline/{segment,embed,cluster,analyse,diagnose,outcomes}.py  store/store.py
strain/frontend/  Vite + React + TS (api.ts, views/, components/) — dist/ built at deploy time
scripts/          seed_corpus.py  evaluate.py
data/             ground_truth.json  outcomes.seed.json  documents/  samples/
archive/          43 real rental agreements (quality-checked source corpus)
tests/            test_segment.py  test_seed.py  test_improvements.py  test_guardrails.py  test_reliability.py
                  fixtures/Rental_Agreement_Sample_04.docx (synthetic regression fixture + builder)
Dockerfile  cloudbuild.yaml  Makefile  requirements.txt
```

`data/strain.db` and `data/embedding_cache.json` are local regenerable artefacts (gitignored — rebuild via `scripts/seed_corpus.py`). Production is a single container (Cloud Run): FastAPI serves the built SPA at `/` and the API at `/api/*`; see `Dockerfile` + `cloudbuild.yaml` (project `pw-exclusive-509711`).

---

## Legal

Informational tool about textual patterns. Not legal advice. All litigation records are illustrative scenarios, not verified judgments — consult a qualified lawyer for your situation.
