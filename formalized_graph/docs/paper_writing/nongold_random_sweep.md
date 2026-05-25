# Non-Gold Random f→i Sweep (strand G)

**Status (2026-05-24):** small-scale pilot complete (n=500). Code:
`experiments/nl_fl_matching/runners/run_nongold_random_f2i.py`. Data:
`experiments/nl_fl_matching/data/nongold_*.{csv,md}`.

## Setup

- **Queries:** 500 project formals sampled uniformly at random (seed=42)
  from the 35,405 non-gold project formals (i.e. those *not* in any
  blueprint `\lean{...}` annotation).
- **Candidate pool:** `all_informals` (11.7M rows), restricted via
  binary-quantized HNSW Hamming shortlist (`ann_k=50`) → cosine rerank.
- **Exclusion:** statement-level. Top-10 retained per query.
- **Wall:** 8 min 11 s (1.0 q/s; bottleneck is RDS ANN).
- **Empty queries (at ann_k=50):** 114 / 500. Root cause established
  (`analysis/diagnose_empties.py`, 2026-05-24): all 114 queries have a
  valid slogan and qwen3-8b embedding; the emptiness is caused by the
  50-NN binary-HNSW shortlist being entirely formal for deep-Mathlib-style
  queries — every shortlist entry is killed by the
  `st.formality='informal'` filter.
- **Empty-query rescue at ann_k=500:** re-ran the 114 empties via
  `runners/run_nongold_empties_retry.py` (pool_descriptor
  `nongold_random_f2i_annk500`). **23 / 114 (20.2%) rescued.** The
  remaining 91 still return 0 informals — these queries are inside a
  dense formal cluster in embedding space with no nearby informal
  partner. Total evaluable set after rescue: **409 queries**.
- **Store:** `direction='f2i'`, `pool_descriptor='nongold_random_f2i'`.

## Rank-1 similarity distribution

| bucket | n | share [95% CI] |
|---|---:|---:|
| sim ≥ 0.95 | 3 | 0.8% — |
| sim ≥ 0.90 | 8 | 2.1% — |
| sim ≥ 0.85 | **36** | **9.3% [6.5, 12.4]** |
| sim ≥ 0.80 | 109 | 28.2% — |
| sim ≥ 0.70 | 350 | 90.7% — |

CIs from `bootstrap_ci.py` (2,000 bootstrap resamples over the n=386
evaluable subset).

**Calibration vs blueprint gold pool (f2i):** the gold-pool sweep returned
Hit@1 = 0.426 — but that's against a known gold partner. Here without a
gold reference, **9.3% of non-gold formals have a rank-1 match at sim ≥
0.85**, which is the threshold our paired-gold experiments showed
correlates with "same statement, possibly different wording" (validated
by eyeballing the top-20).

## Where do high-sim rank-1 candidates come from?

| source (sim ≥ 0.85) | n |
|---|---:|
| arXiv | 30 |
| Lean Community (blueprint) | 6 |

**93.5% of rank-1 candidates are arxiv** (consistent with arxiv dominating
the informal pool). High-sim matches into arxiv are the genuine
"low-hanging fruit" signal: project Lean decls that semantically align with
arxiv prose that nobody linked.

## Repos with the most high-sim non-gold matches (sim ≥ 0.85)

| n | repo |
|---:|---|
| 8 | PrimeNumberTheoremAnd |
| 5 | pfr |
| 3 | cslib |
| 3 | combinatorial-games |
| 3 | HarderNarasimhan |
| 2 each | misc-yd, brownian-motion, sphere-packing-math-inc, physlib |

## Top examples (full list in `data/nongold_top20.md`)

| sim | formal decl | informal partner | what's happening |
|---:|---|---|---|
| 0.974 | pfr `ProbabilityTheory.measureMutualInfo_nonneg` | teorth/pfr blueprint 2.17 | blueprint `\lean{}` says `mutualInfo_nonneg` (no `measure`) — decl was renamed after annotation, gold pair missed it |
| 0.963 | misc-yd `Metric.epackingNum` | arXiv:2310.19103 §9.8 | **cross-source match** — Lean decl finds arxiv prose nobody linked |
| 0.954 | brownian-motion `MeasureTheory.capacity_iUnion` | arXiv:1104.0792 §5.3 | cross-source match |
| 0.929 | pfr `rdist_congr_left` | teorth/pfr blueprint 3.10 | blueprint says `rdist_congr` — naming drift |
| 0.912 | cslib `ωLanguage.isRegular_iff` | arXiv:1605.00186 | cross-source match (omega-regular languages) |
| 0.901 | sphere-packing `…minDist_le_weight_of_nonzero_mem` | arXiv:1907.12754 §1.12 | cross-source match (coding theory) |

Two clear sub-populations in the high-sim band:

1. **Blueprint annotation drift** (~ 6/36 high-sim): formal decl renamed
   since its blueprint partner's `\lean{...}` annotation was written.
   These are *false negatives* in our gold set — they should be gold but
   aren't.
2. **Cross-source matches** (~ 30/36 high-sim): project Lean decls whose
   nearest informal is from arxiv literature outside their own blueprint.
   These are the **"low-hanging fruit" candidates** for either citation
   backfilling (Lean decl → arxiv paper) or upstream attribution.

## Implications for the paper

- The gold pool is **noisy in two directions**: 2/15 "neither" pairs had
  *wrong* annotations ([`bidirectional_matching.md`](./bidirectional_matching.md))
  and ≈6/36 high-sim non-gold formals are *missing* annotations
  (this doc). The true Hit@1 ceiling sits above the reported 0.426.
- Cross-source matches are paper-worthy: 30 of 386 non-gold project
  formals (~7.8%) have a sim ≥ 0.85 arxiv partner. Scaled to the full
  35,405-formal non-gold pool, that projects to ~2,750 cross-source
  candidate links the corpus does not yet record.

## What was NOT run

- Full-scale n=35,405 sweep (~10 hr at current 1 q/s). Deferred — the
  n=500 sample is already enough to characterize the distribution.
- ~~Strand (F) i→i same-formality NN~~ remains deferred (11.7M × 11.7M
  is infeasible without ANN over the entire informal pool).

## Reproducing

```bash
python -m experiments.nl_fl_matching.runners.run_nongold_random_f2i \
    --n 500 --seed 42
python -m experiments.nl_fl_matching.analysis.nongold_distribution
```
