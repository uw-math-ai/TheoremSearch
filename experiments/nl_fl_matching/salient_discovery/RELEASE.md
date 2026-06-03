# Mathlib ↔ arXiv matching — honest release spec

Goal: an **honest** cross-graph matching that does not overstate. We separate what we
*claim* (airtight, 2-model-confirmed) from what we *surface* (raw embedding candidates),
and we state both the precision and the recall limits plainly. Two artifacts:

## 1. RAW candidate pool — surfaced, NOT claimed
Every rank-1 informal match with cosine ≥ 0.85 from the saliency sweep (formal Mathlib/
project node → arXiv statement). **No precision claim is made on the raw set** — it is the
embedding's output, released so others can mine it and audit our recall.

| class | 0.85–0.90 | 0.90–0.95 | 0.95–1.0 | total ≥0.85 |
|---|---|---|---|---|
| mathlib | 25,114 | 6,514 | 703 | **32,331** |
| project | 1,769 | 452 | 69 | **2,290** |
| **all** | 26,883 | 6,966 | 772 | **34,621** |

File: `data/salient_matches_full.csv` (sim, band, cls, formal/informal slogans + bodies,
arxiv_id, paper_title, ids). Sweep config: pgvector binary-quant HNSW, cosine rerank,
`ann_k=50`, `max_scan_tuples=500k`, `exclusion=statement`, `embedding_model=qwen3-8b`.

## 2. CONFIRMED edge set — airtight (2-rater Opus consensus)
A candidate is **claimed** only if it survives independent confirmation. `grade_consensus.py`:
two independent blind Opus grades (neutral rubric) → if they agree, CONFIRMED; if not, a
third Opus tie-break decides by majority of three; a genuine 3-way split → **ABSTAIN** (not
claimed). This controls false positives (a fluke must fool two independent strong graders)
*and* false negatives (rejections are double-graded too), and refuses to force the
irreducibly-ambiguous.

Status taxonomy: `confirmed` (2 agree) / `tiebroken` (2-of-3) / `edge_ambiguous` (agree it's
an edge, unsure exact vs inexact) / `notedge_ambiguous` / `ambiguous` (3-way split → abstain).
Fine label ∈ {exact, inexact, wrong}; **claimed edge** = final ∈ {exact, inexact} with status
∈ {confirmed, tiebroken, edge_ambiguous}.

**Status (2026-05-30):** ≥0.90 tier (7,217) grading first — sbatch 35752091, out
`consensus_ge90.jsonl`. The 0.85–0.90 band (25,114) decision is staged pending burn-rate;
until/unless confirmed it remains RAW with the audit-precision estimate below.

## Precision — what we actually know
- **≥0.90 tier:** per-edge 2-Opus-confirmed (in progress). Tier is overwhelmingly real
  (validation head sim=1.0 → all confirmed edges; probe 9/10 exact).
- **0.85–0.90 band:** Opus-consensus *audit* (n=251 stratified, two-blind-Opus truth, tie-broken)
  → **edge keep-precision 76.6% [69.7, 83.5]**, exact precision 70%. **Optimistic end** — the
  audit substrate is the high-sim head (sim ≥ 0.8785); the unlabeled tail (median 0.8621) is lower.
- **Do NOT trust the cheap haiku pre-sort as a claim** — it is lenient (κ=0.57 vs Opus; its
  "inexact" bucket is 32% actually-different-theorems). It is a non-binding sort only.

## Recall / completeness — what this is NOT
This is **discovery from what the embedding surfaced**, not a complete matching. Stated limits:
- **Retrieval horizon:** `ann_k=50`. False-empty probe (n=40 empties re-run at `ann_k=500`)
  found empties are **not** hiding strong matches → the ~47% "empty" formal nodes are genuinely
  non-matchable plumbing, not scan-horizon misses. So retrieval recall on matchable nodes is good,
  but not exhaustive.
- **Recall ceiling (gold):** of 1,577 blueprint-gold formal statements, the sweep recovers the
  gold informal partner @rank-1 **42.2%** / @top-10 **69.4%** (reproduces validated §6 retrieval).
  ⇒ even among known-matchable theorems, ~30% are not surfaced in the top-10 — a real recall gap.
- **Coverage:** informal side = arXiv only; formal side = saliency-swept Mathlib + projects.
  Matches to non-arXiv math (textbooks, other papers) are out of scope by construction.

## Files
`README.md` design · `RUNS.md` run log (RUN 4 = consensus) · `grade_consensus.py` grader ·
`score_grader.py` + `data/grader_*.json` haiku-vs-Opus validation · `data/salient_matches_full.csv`
raw pool · `consensus_ge90.jsonl` (gscratch) confirmed set.
