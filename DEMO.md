# STRAIN — 3-Minute Demo Script

> **Purpose**: End-to-end walkthrough for a hackathon judge or first-time user.  
> **Prerequisite**: Corpus seeded and both servers running.  
> Start servers: `make demo` (seeds + starts backend on :8000, frontend on :5173)

---

## 0 — Setup (30 seconds, pre-demo)

```
make demo
```

Wait until you see:
- `Uvicorn running on http://0.0.0.0:8000`
- `VITE v6.x ready in ... ms → http://localhost:5173/`

Open **http://localhost:5173** in a browser.

---

## 1 — Home Screen (15 seconds)

Point out the navigation bar:
- **Diagnose** — upload/paste a rental agreement
- **Strain Atlas** — phylogeny explorer
- **Outbreak** — population-level dashboard
- **"Synthetic Corpus" badge** — always visible to remind users the corpus is constructed

> *"STRAIN treats contract clauses like viral strains. It identifies which family a clause belongs to, how it has mutated from an ancestral draft, and how harsh it has become."*

---

## 2 — Diagnose a Document (60 seconds)

**Click "Load samples"** → Three synthetic documents appear.

**Click "Sample Landlord Aggressive"** (the Template T4 descendant — most mutations, highest virulence).

While loading (5–15 seconds), explain:
> *"STRAIN is computing an embedding for each clause in your document, then finding the nearest strain cluster in our corpus of 306 synthetic agreements."*

When results appear:
- **Stats row**: Show clause count, high-risk count, avg risk score
- **Top clause** (expanded by default): Point out the 0–100 risk score and the three-component breakdown: *Asymmetry, Harshness Δ, Outcome Risk*
- **Litigation history row**: Expand one clause with a "Voided" outcome. Point to the **ILLUSTRATIVE** badge and explain: *"We never fabricate case law. Every record here is clearly labelled illustrative — it shows the pattern type, not a specific decided case."*
- **Neutralising wording**: Click "Show alternative" on a high-risk clause — STRAIN shows the lowest-asymmetry variant from the same strain family in the corpus.

---

## 3 — Strain Atlas (45 seconds)

Click the **"Strain Atlas"** tab.

Pick the **Security Deposit** family from the selector row.

The phylogeny tree appears:
- **Colour = risk level** (green → amber → orange → red)
- **Your document's clauses** appear as **indigo nodes with a glow ring**
- **Drag to pan, scroll to zoom**

Click one of your indigo nodes. The side panel opens:
- Clause text of the selected node
- **Word diff** from its parent (red = removed, green = added)

> *"This is the mutation view. STRAIN reconstructs which clauses evolved from which — tracking how tenant-protective language was gradually stripped out across document generations."*

---

## 4 — Outbreak Dashboard (30 seconds)

Click **Outbreak** tab.

Show the four charts:
- **Strain Prevalence**: which clause families appear most in the corpus
- **Harshness Trend**: average risk score by document generation (the T4 family trends upward — landlord-aggressive clauses compound over time)
- **Outcome Distribution**: illustrative litigation results across all strain families
- **Strain Growth**: stacked area chart showing how strain populations expand across generations

> *"This is the view for a legal-aid NGO or regulator — at a glance, which clause patterns are proliferating and which ones courts have voided."*

---

## 5 — Handoff Panel (30 seconds)

Go back to **Diagnosis** (tab appears after first diagnosis).

Scroll to the bottom. Show the **"Take This to a Lawyer"** panel:
- **Top 3 highest-risk clauses** with targeted questions to ask a lawyer
- **Documents to bring** — pre-populated practical checklist
- **Deadlines detected** — any explicit dates extracted from the agreement text
- **Referral note** at the bottom: *"A qualified lawyer can assess how these clauses interact with applicable local rent control legislation."*

> *"STRAIN identifies the problem areas and arms a tenant with the right questions. It explicitly does not tell them what to do — that's a lawyer's job."*

---

## Talking Points for Q&A

| Question | Response |
|---|---|
| "Is this real case law?" | "No. Every outcome record is clearly labelled ILLUSTRATIVE and our AGENTS.md bans fabricated citations." |
| "How does it work offline?" | "Embeddings use sentence-transformers (all-MiniLM-L6-v2) which download once and run locally. No API key needed." |
| "What data does it store?" | "SQLite, on disk. No data leaves the machine." |
| "Why rental agreements only?" | "Depth beats breadth. One document type, deeply analysed. Generalising to other contract types is a roadmap item." |
| "How accurate is clustering?" | "See EVALUATION.md. ARI measures how well HDBSCAN reconstructs the 6 known template families. The honest limitation is also documented there." |
| "Could it be wrong?" | "Yes. STRAIN says clauses are textually related, never that one provably caused the other. A lawyer reviews the specifics." |

---

*STRAIN — Contract Clause Diagnostic Tool*  
*Synthetic corpus · Offline-first · No legal advice*
