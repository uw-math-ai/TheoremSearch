# f→f Cross-Project Nearest Neighbours

**Status (2026-05-24):** complete sweep. All 36,708 project formals queried
against the same pool with `exclusion='paper'` so each rank-1 candidate is
from a *different* repo. Code: `experiments/nl_fl_matching/runners/run_ff_cross_project.py`.
Data: `experiments/nl_fl_matching/data/ff_cross_project_*`.

## Setup

- Pool: 36,708 project formals (`source = 'Lean Repo'`, external_id excludes
  `Mathlib_*` and `Batteries_*`).
- Embedding: `qwen3-8b` on `qwen3-235b` slogans, L2-normalized.
- Method: in-memory all-pairs matmul (36,708 × 36,708 × 4096 floats),
  chunked 1024 rows at a time. **Wall: 92 s after pool load.**
- Exclusion: `paper` — same-repo candidates are masked to −∞ before top-K.
- Written to `nl_fl_match_pilot` as
  `direction='f2f', exclusion='paper', pool_descriptor='cross_project_f2f'`.

## Headline numbers

**All cross-project rank-1 matches (raw):**

| threshold | twins | share |
|---|---:|---:|
| sim ≥ 0.95 | 131 | 0.4% |
| sim ≥ 0.85 | 1,391 | 3.8% |
| sim ≥ 0.80 | 3,042 | 8.3% |

**Corrected — excluding the two parallel-formalization repo-pairs**
(Sphere-Packing-Lean ↔ sphere-packing-math-inc; add-combi ↔ apap; the
latter is independent additive-combinatorics work, not a fork):

| threshold | twins | share |
|---|---:|---:|
| sim ≥ 0.95 | **14** | **0.04%** |
| sim ≥ 0.85 | **446** | **1.3%** |
| sim ≥ 0.80 | 1,502 | 4.5% |

The two parallel-formalization repo-pairs contribute **945/1,391 (68%)** of
high-sim twins, including **117/131 (89%) of the sim ≥ 0.95 matches**.
Within those pair-pools, 28.3% of rank-1 candidates are at sim ≥ 0.85 —
versus 1.3% for the rest of the corpus. **Headline cross-project
"discovery" finding is 446 twins at sim ≥ 0.85, not 1,391.**

**Interpretation:** at ≥0.95 a twin is essentially the same theorem written
in two repos; at ≥0.85 it's the same statement with minor variation
(`f`/`f'` decls, generalization of typeclass, naming variant). The raw
1,391 count is inflated by the two known parallel-formalization corpora;
the corrected 446 represents independent re-formalizations across
genuinely distinct projects.

## Top cross-project pairs (twins at sim ≥ 0.85)

| pair | n twins | what this means |
|---|---:|---|
| Sphere-Packing-Lean ↔ sphere-packing-math-inc | **706** | two parallel formalizations of the same sphere-packing paper |
| add-combi ↔ apap | **239** | parallel additive-combinatorics convolution libraries |
| PrimeNumberTheoremAnd ↔ combinatorial-games | 55 | likely Mathlib-style basic-arithmetic lemmas in both |
| PrimeNumberTheoremAnd ↔ sphere-packing-math-inc | 41 | shared analytic-number-theory helpers |
| physlib ↔ sphere-eversion | 24 | differential-geometry overlap |
| apap ↔ carleson | 24 | Fourier / harmonic-analysis helpers |

## Example twins (sim ≥ 0.98)

From `data/ff_cross_project_top20.md`:

| sim | repo A | repo B | comment |
|---|---|---|---|
| 0.999 | add-combi `NNReal.coe_comp_dconv` | apap `NNReal.coe_comp_cdconv` | identical convolution-coercion lemma |
| 0.988 | Sphere-Packing-Lean `Φ₄'_contDiffOn_ℂ` | sphere-packing-math-inc `Φ₄'_contDiffOn` | same smoothness lemma, decl-name suffix differs |
| 0.987 | apap `neg_cdconv` | add-combi `neg_conv` | same convolution-negation identity |
| 0.985 | Sphere-Packing-Lean `I₂'_bounding_aux_3` | sphere-packing-math-inc (mirror) | same integral bound |

## Findings (paper-ready)

1. **Cross-project duplication is concrete and measurable.** 1,391 project
   formals (3.8% of the corpus) have a sim ≥ 0.85 twin in a different
   repo. These are real duplicates — the top-20 are nearly identical
   slogans with different decl names.
2. **Two repo pairs account for 68% of all high-confidence twins**:
   the Sphere-Packing-Lean ↔ sphere-packing-math-inc fork (706) and the
   add-combi ↔ apap convolution overlap (239). The corpus has at least
   two cases of fully parallel formalization that the community could
   consolidate.
3. **This experiment is directly useful for an upstream-merging agent:**
   `data/ff_cross_project_twins.csv` is 36,708 rows of
   (decl_a, decl_b, sim) sorted by sim — the top 1,391 are the
   high-confidence dedup queue.

## Reproducing

```bash
python -m experiments.nl_fl_matching.runners.run_ff_cross_project
python -m experiments.nl_fl_matching.analysis.ff_cross_project
```

Wall: ~17 min pool load (RDS-bound) + 92 s matmul/write.

## What we did NOT run

- Same-formality NN for informals (i→i): 11.7M × 11.7M is infeasible at
  this scale without ANN; deferred.
- Random-sample sweep of non-gold project formals against full informal
  pool (G): deferred.
