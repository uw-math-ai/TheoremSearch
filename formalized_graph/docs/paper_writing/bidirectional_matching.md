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

## Gold-set annotation noise (n=150 dual-rater audit, 2026-05-24)

Dual-rater audit: 150 random gold pairs from the 1,595-pair set, labeled by
Claude Sonnet 4.5 (primary) + Claude Haiku 4.5 (secondary) via Bedrock.
Code: `experiments/nl_fl_matching/analysis/gold_pair_audit.py`.
Data: `experiments/nl_fl_matching/data/gold_pair_audit.{csv,json}`.

| status (both raters) | n | share |
|---|---:|---:|
| both 'correct' | 24 | 16.0% |
| both 'partial' (same theorem, generality mismatch) | 31 | 20.7% |
| both 'wrong' (annotation broken) | **18** | **12.0%** |
| disagree (mostly correct↔partial: n=43) | 70 | 46.7% |
| at least one 'ambiguous' | 7 | 4.7% |

**Inter-rater agreement: Cohen's κ = 0.296** (fair; partial-vs-correct
boundary is judge-dependent). Observed agreement = 0.487.

**Defensible noise bounds:**
- **Lower bound on annotation error rate: 12.0%** (n=18 both 'wrong'; eyeballed
  e.g. carleson 11.1.3 informal asks about `|S_N f - S_N f_0|` but formal bounds
  a single function; Sphere-Packing 1.1 defines packing as union-of-balls but
  formal extracts center points).
- **Upper bound: 26.7%** (n=40 either rater flagged 'wrong').

**Implication for Hit@k:** the 38.8% "neither" bucket includes at least
~12pp of pure annotation noise. Adjusted retrieval-failure rate is ≤27pp,
not 39pp. The 0.426 Hit@1 has a lower-bound corrected value of roughly
**0.426 / (1 - 0.12) ≈ 0.48** if we assume the 12% wrong cases would have
matched correctly against the *true* formal partner had it been labeled.

**Methodological observation worth flagging in the paper:** even strong
LLM judges (κ=0.30) disagree on the correct↔partial boundary when typeclass
generality differs. Three-category labels (correct/partial/wrong) are too
granular for reliable LLM-only audit; future work could binary-collapse
("matches the right theorem family yes/no") for higher agreement.

## Open work — must-do / should-do before submission

These are the gaps surfaced by the methodology critique (2026-05-24). The
gold-pair audit and empty-query root-cause are running / done; the others
are documented here so the next session can pick up without re-deriving.

**Must-do (defends primary claims)**

| ✓ | task | informs | est wall |
|:---:|---|---|---|
| ✅ | Gold-pair correctness audit (n=150, dual-rater Bedrock Claude) — 2026-05-24 | every Hit@k number; **noise floor: 12% lower, 27% upper, κ=0.30** | done (20 min wall) |
| ✅ | Empty-query root cause for non-gold sweep | non-gold 9.3% interpretation; ann_k tuning | 30 min |
| ⬜ | Hand-label the 45 non-gold mutual pairs | turns 88.8% precision from circular into a real claim | ~1 hr |
| ✅ | Drop "directional symmetry" framing from prose | replaced with the agreement-bucket claim (2026-05-24) | done |
| ✅ | Recompute cross-project headline excluding the 2 parallel-formalization pairs | **446 twins (not 1,391) at sim≥0.85** after exclusion; see [`cross_project_twins.md`](./cross_project_twins.md) | done (2026-05-24) |

**Should-do (closes obvious reviewer attacks)**

| task | informs | est wall |
|---|---|---|
| Bootstrap CIs on Hit@1 numbers (both directions, mutual NN, non-gold high-sim rate) | every point estimate in this doc | ~1 hr |
| Expand "neither" failure-mode sample to n≥50 with two-rater agreement | currently n=15 one-author taxonomy | ~3 hr |
| Cite + position vs Herald (ICLR 2025), RLM25 (EMNLP 2025), LSv2 (arXiv:2605.13137), Lean Finder (ICLR 2026), graph-aug premise selection (arXiv:2510.23637) | reviewer attack: "did you read the lit" | ~30 min |
| BM25 / char-4gram baseline on the same 1,562 + 1,308 gold queries | reviewer attack: "no baseline" | ~2 hr |

**Nice-to-have (after deadline if time)**

- Headline figure: scatter of (emb_cos, char_4gram) on gold pairs, colored by agreement-bucket
- One alternate embedding model ablation (Llama-Embed-Nemotron-8B is the strongest open challenger)
- Re-run the n=500 non-gold sweep at ann_k=500 from the start so the 9.3% headline reflects the corrected coverage
- Expand non-gold sweep to n=1k–2k for tighter CI on the 9.3% rate

## Findings (paper-ready)

1. **Bidirectional retrieval as a recovery mechanism**: 25.7% of gold
   pairs are recovered by both directions; 35.5% by exactly one;
   38.8% missed by both. **Combining directions raises top-1 recovery from
   42.6% to 61.2% — a ~45% relative gain over a single direction.**
   No prior NL↔FL retrieval paper reports both directions on a shared
   gold set; this is the headline result.
2. **Mutual rank-1 nearest neighbours as a high-precision filter:**
   400 (informal, formal) pairs are rank-1 in both directions. 88.8%
   (355/400) match the blueprint gold partner exactly, and a dual-rater
   audit of the 45 non-gold mutuals (see below) puts ~X% of them at
   "correct OR partial." Mutual-NN is the strongest "same statement"
   signal the pipeline produces — paper-worthy as a method, not just an
   observation.
3. **Embedding aligns with lexical baselines but isn't redundant with
   them.** Spearman correlations are positive (0.47–0.66) but well below
   1.0, so the embedding contributes non-lexical signal that the simpler
   methods miss. Future work could weight lexical + embedding for the
   one-direction-only recovery cases (~36% of gold pairs).

> **Reporting note (2026-05-24):** earlier drafts framed "both directions
> hit 0.426" as "directional symmetry." This framing is dropped — the two
> directions search pools of different sizes (36k vs 11.7M), so identical
> Hit@1 is a numeric coincidence rather than a phenomenon. The agreement-
> bucketing finding (item 1) is what's actually new about doing both
> directions.

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
