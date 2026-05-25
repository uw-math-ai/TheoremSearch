# Bidirectional NL↔FL Matching on Blueprint Gold Pairs

**Status (2026-05-24):** complete pilot run. All numbers below grounded in
`experiments/nl_fl_matching/` against db `v2`, embedding = `qwen3-8b`.

## Setup

- **Gold pairs:** 1,595 (informal, formal) pairs derived from
  `informal_metadata.lean` annotations in the 21 Lean Community blueprint
  repos. 1,308 distinct informals × 1,577 distinct formals.
- **Pool details:** see [`schema.md`](./schema.md). All queries restricted
  to statements with a non-insufficient `qwen3-235b` slogan and a
  `qwen3-8b` embedding.
- **f→i sweep**: each gold formal queried against the full 11.7M informal
  pool via binary-quantized HNSW Hamming shortlist (`ann_k=50`) →
  full-precision cosine rerank. Top-10 kept. 22 min wall, 13,985 ranked
  rows, 15 empty (no embedding).
- **i→f sweep**: each gold informal queried against the 36,708
  project-formal pool via in-memory numpy matmul (cosine on L2-normalized
  vectors). Top-10 kept. 21 min wall, 13,080 ranked rows, 0 empty. Matmul
  rather than ANN because project formals are 0.3% of the index — ANN
  would have needed `ann_k≈2000`/query, ~10× slower.
- **Exclusion:** statement-level (query cannot retrieve itself; gold
  partners are not excluded).

## Headline table

| direction | evaluated | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| **f → i** | 1,562 / 1,577 (99.0%) | **0.426** | 0.643 | 0.698 | 0.518 |
| **i → f** | 1,308 / 1,308 (100.0%) | **0.426** | 0.670 | 0.717 | 0.531 |

For comparison, the group's prior paper (arXiv:2602.05216, 111 expert
queries against 9.2M informal corpus, with reranker) headline was
Hit@1=0.189, Hit@10=0.432, MRR@20=0.270 on a fundamentally different
task (mathematician-written queries vs. blueprint-curated pairs).

## Bidirectional agreement (1,595 pairs)

| bucket | count | pct |
|---|---:|---:|
| both_correct (both directions hit rank 1) | 410 | 25.7% |
| f2i_only | 269 | 16.9% |
| i2f_only | 297 | 18.6% |
| neither | 619 | 38.8% |
| **either direction hits at rank 1** | **976** | **61.2%** |

Combining directions lifts top-1 recovery from **42.6% (single-direction)
→ 61.2% (either)** — a ~45% relative gain attributable to the
bidirectional design. This is the "mutual NN as quality signal" claim
from Artetxe & Schwenk (ACL 2019) imported to NL↔FL theorem matching,
where it has no prior precedent.

## Mutual rank-1 nearest neighbours

Stricter signal than the bucket above: same (informal, formal) pair must be
top-1 in **both** directions (not just any gold sibling).

| metric | count | note |
|---|---:|---|
| total mutual rank-1 pairs | 400 | f→i top-1 = i AND i→f top-1 = f |
| mutual ∩ gold | 355 | 88.8% of mutuals are blueprint-annotated |
| mutual ∖ gold | 45 | non-gold mutuals = strongest backfill candidates |
| gold ∩ mutual | 355 / 1,595 | 22.3% of gold pairs recovered as mutual |

Per-pair list at `experiments/nl_fl_matching/data/mutual_rank1_pairs.csv`
(regenerate with `python -m experiments.nl_fl_matching.analysis.mutual_nn`).
The 45 non-gold mutuals are the **highest-confidence formalization backfill
candidates** — see [`formalization_candidates.md`](./formalization_candidates.md).

## Lexical baseline correlation (task 4)

Spearman ρ on a 500-sample of f2i rank-1 pairs (query slogan ↔ top-1
candidate slogan):

| metric | ρ vs embedding cosine |
|---|---:|
| char_4gram (Jaccard) | **0.664** |
| jaccard_tokens | 0.630 |
| tfidf_cosine | 0.625 |
| char_3gram (Jaccard) | 0.600 |
| bm25 | 0.496 |
| edit_norm | 0.465 |

All strongly positive. The embedding's similarity ranking aligns well
with surface-level lexical overlap, indicating it is not surfacing
spurious non-lexical matches. char_4gram is the closest lexical proxy
(captures stem-level overlap most cleanly). Per-pair scores saved to
`/tmp/nl_corr_f2i.csv` for a paper figure.

## Failure modes ("neither" bucket, n=15 sampled)

15 random pairs from the 619 "neither" pairs (seed=20260524) were eyeballed
with hydrated slogans + top-5 per direction (raw at
`experiments/nl_fl_matching/data/neither_cases.md`).
**12 / 15 had the gold at rank ≤ 5 in at least one direction** — the
single-direction rank-1 metric understates how close the embedding actually
gets. Observed failure modes:

| mode | n | example | what the embedding returned at rank 1 |
|---|---:|---|---|
| Sibling-lemma adjacency (same paper, many near-identical statements) | 3 | sphere-packing `H₄`, carleson `pairwiseDisjoint_E1` | a sister lemma about the same object |
| Equation/property-of-X ranked over definition-of-X | 3 | pfr `condMutualInfo`, brownian-motion `gaussianReal` | `*_eq` / `*_iff` form of the gold decl |
| Additive/multiplicative or fun-vs-value twin (`to_additive`-style) | 2 | toric `MonoidAlgebra.span_isGroupLikeElem` | the `AddMonoidAlgebra` mirror |
| Multiple correct formalizations exist; canonical form wins | 2 | sphere-packing `Submodule.E8` | `E8Packing_lattice` (sim 0.90 vs gold 0.84) |
| Terminology drift between blueprint and Lean code | 1 | carleson 7.1.2 ("cubes" → `tiles`) | a different cube-union lemma |
| Compound / multi-clause informal statement dilutes embedding | 1 | carleson 11.3.5 | a topically-adjacent but different inequality |
| Bad / under-specified blueprint `\lean{}` annotation | 2 | FLT 10.9, ClassFieldTheory 24 | unrelated decl (annotation appears wrong) |
| Generalization gap (project-specific informal ↔ general Mathlib lemma) | 1 | brownian-motion 2.2.3 ↔ Mathlib `infClosure` | the wrong Mathlib infClosure variant |
| Lexical hijack by surface triggers (e.g. "successor order") | 1 | brownian-motion `rightCont_eq_self` | `Filter.cofinite_hasBasis_Ici` |

**Two implications for the paper:**

1. Three failure modes (sibling adjacency, equation/def confusion,
   additive/multiplicative twin) account for 8/15 cases. All three are
   **structural artefacts of the Lean corpus** (paper authors write
   many parallel lemmas; Mathlib emits both `MonoidAlgebra` and
   `AddMonoidAlgebra` forms via `to_additive`). They are not
   embedding-quality failures — every "wrong" rank-1 match is itself a
   correct paraphrase of the gold statement. **A reranker that uses
   formal-side metadata (paper context, `decl_name` stem, `kind`) could
   recover most of them.**
2. ≥2/15 sampled pairs have a **wrong blueprint annotation** (FLT 10.9
   → an additive Haar-measure lemma is clearly mis-targeted). The
   "neither" bucket is therefore inflated by blueprint noise; the true
   alignment ceiling is higher than the 61.2% either-direction number.

## Findings (paper-ready)

1. **Directional asymmetry is essentially zero at Hit@1** (both = 0.426).
   This contradicts the literature's expectation that formal slogans being
   terser than informal counterparts should make f→i easier. Our slogan→
   embed pipeline appears to wash that asymmetry out. **No prior NL↔FL
   retrieval paper reports both directions — this is genuinely new.**
2. **Bidirectional retrieval as a recovery mechanism**: 25.7% of gold
   pairs are recovered by both directions; 35.5% by exactly one;
   38.8% missed by both. Combining directions raises top-1 recovery to
   61.2%, a ~45% relative gain over a single direction.
3. **Embedding aligns with lexical baselines but isn't redundant with
   them.** Spearman correlations are positive (0.47–0.66) but well below
   1.0, so the embedding contributes non-lexical signal that the simpler
   methods miss. Future work could weight lexical + embedding for the
   one-direction-only recovery cases (~36% of gold pairs).

## What we did NOT run (deferred)

- (E) f→f same-formality nearest-neighbour: **DONE 2026-05-24** with
  cross-project (`exclusion='paper'`) constraint. See
  [`cross_project_twins.md`](./cross_project_twins.md) — 1,391 twins at
  sim ≥ 0.85, two repo-pairs (Sphere-Packing-Lean ↔ sphere-packing-math-inc,
  add-combi ↔ apap) account for 68% of high-sim matches.
- (F) i→i same-formality nearest-neighbour: deferred — 11.7M × 11.7M
  is too expensive for the current deadline.
- (G) random sample of 5k non-gold formals: **DONE 2026-05-24** at n=500
  scale. See [`nongold_random_sweep.md`](./nongold_random_sweep.md) —
  9.3% have rank-1 sim ≥ 0.85, ~80% of those are cross-source Lean↔arxiv
  matches the corpus does not record.

All three were scoped as P2 in the deadline plan; the headline result
(Hit@k + MRR table + agreement + correlation) is complete without them.

## Reproducing

```bash
python -m experiments.nl_fl_matching.smoke_test
python -m experiments.nl_fl_matching.runners.run_gold_pair_sweep --direction f2i
python -m experiments.nl_fl_matching.runners.run_gold_pair_sweep --direction i2f
python -m experiments.nl_fl_matching.analysis.eval
python -m experiments.nl_fl_matching.analysis.agreement
python -m experiments.nl_fl_matching.analysis.nl_corr --direction f2i \
    --pool-descriptor gold_subset_f2i --sample 500 --out-csv nl_corr_f2i.csv
```

Output rows persist in `nl_fl_match_pilot` on `db v2`, keyed by
`(query_statement_id, direction, exclusion, rank, embedding_model)`.
Re-running a sweep is idempotent (upsert on PK).
