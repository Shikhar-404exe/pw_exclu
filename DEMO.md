# STRAIN — Demo Guide

> **AI for Legal Assistance & Access** — A GenAI-powered diagnostic tool for rental contract clauses.

## Live Demo

The app is deployed on **Google Cloud Run**:

```
https://strain-[your-cloud-run-url].run.app
```

> If the above URL is unavailable, run the app locally (see README.md for setup).

---

## What STRAIN Does (Problem Statement Alignment)

STRAIN directly addresses all problem statement use cases:

| Use Case | STRAIN Feature |
|---|---|
| **Simplify complex legal documents** | Plain-language topic labels + 0–100 risk scores with plain-English evidence |
| **Compare contracts, agreements** | Strain Atlas: same clause across document generations, side-by-side |
| **Highlight important clauses, risks** | Colour-coded risk cards, high-risk badges, top-3 handoff risks |
| **Answer questions based on documents** | Per-clause evidence panels + AI-matched clause families |
| **Understanding options and next steps** | Reference wording with word diff — see what a fairer clause looks like |
| **Generating summaries, checklists** | Handoff Panel: risks + lawyer questions + documents to bring + key dates |
| **Prepare for a legal professional** | Copy-ready report scoped to riskiest clauses, with topic-routed lawyer questions |
| **Information, not advice** | Guardrail-tested — no "you should" / "we recommend" / "legal advice" in any UI copy |

---

## 3-Minute Walkthrough

### Step 1: Upload or paste a rental agreement
- Navigate to **Diagnose** tab
- Upload a PDF/DOCX/TXT or use a built-in sample

### Step 2: Read the Diagnosis Report
- Each clause gets a **topic label** (rent, deposit, termination, etc.)
- A **0–100 risk score** with evidence: asymmetry + harshness vs. corpus root + outcome factor
- For high-risk clauses: side-by-side **reference wording** with word diff

### Step 3: Explore the Strain Atlas
- See how clause language has **mutated across documents**
- Your clauses glow in the phylogeny tree
- Click any node to see a **parent–child word diff**

### Step 4: Take to a Lawyer
- Scroll to **"Take This to a Lawyer"** handoff panel
- Top-3 risks with **topic-specific questions to ask your lawyer**
- **Documents to bring** checklist
- **Key dates** extracted from your document

---

## AI / GenAI Components

| Component | Technology | Where |
|---|---|---|
| Clause embedding | `all-MiniLM-L6-v2` (local sentence-transformer) | `pipeline/embed.py` |
| Strain matching | Cosine similarity against corpus embeddings | `pipeline/diagnose.py` |
| Topic classification | Rule-based + embedding-assisted (16-topic taxonomy) | `pipeline/segment.py` |
| Mutation labelling | Rule-based classifier (LLM-phrase-only, no hallucination) | `pipeline/analyse.py` |
| Virulence scoring | Multi-component formula (asymmetry + harshness + outcomes) | `pipeline/analyse.py` |
| Handoff generation | Deterministic + clause-data-driven | `pipeline/diagnose.py` |

---

## Sample Documents

Three built-in sample agreements are available on the Diagnose tab:

1. **Sample Landlord Aggressive** — high-risk clauses, expanded reference wording
2. **Sample Balanced** — moderate scores, mixed results
3. **Sample Tenant Friendly** — low scores, illustrates the scale

---

## Disclaimer

STRAIN provides **information and analysis**, not legal advice. All corpus relationships are
textual kinship, not proven copying. Litigation scenarios are illustrative, not verified judgments.
Consult a qualified lawyer for your situation.
