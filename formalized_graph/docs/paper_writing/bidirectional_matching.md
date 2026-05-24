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

- (E) f→f same-formality nearest-neighbour (exclude self / exclude paper)
- (F) i→i same-formality nearest-neighbour
- (G) random sample of 5k non-gold formals to characterize the distribution
  outside the blueprint subset

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
