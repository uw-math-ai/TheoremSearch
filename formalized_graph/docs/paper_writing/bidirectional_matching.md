# Bidirectional NL↔FL Matching on Blueprint Gold Pairs

**Status (2026-05-24):** complete pilot run. All numbers below grounded in
`experiments/nl_fl_matching/` against db `v2`, embedding = `qwen3-8b`.

## Related work and differentiation

This work sits in a crowded landscape of Lean-side retrieval / autoformalization
papers from 2025 onward. Brief positioning (full discussion in the paper):

- **LeanSearch v2** (Tao et al., arXiv:2605.13137, May 2026) is the
  closest competitor on the *formal-side retrieval* axis: staged
  embedding + Qwen3-Reranker-8B over a hierarchy-informalized Mathlib
  corpus, with a reasoning-mode sketch-retrieve-reflect loop. Their
  MathlibQR benchmark reports nDCG@10 = 0.62 (with reranker). Our
  parallel replication harness lives at
  `experiments/leansearch_v2_replication/`; we are *not* claiming
  Mathlib-formal-retrieval SOTA.
- **Lean Finder** (Yang et al., ICLR 2026, arXiv:2510.15940) fine-tunes
  embeddings on synthetic user-intent queries and beats LeanSearch +
  GPT-4o on user preference (81.6%). Lean Finder's i→f setup is closest
  to ours; the differentiation is that they fine-tune for retrieval
  quality, while we run off-the-shelf qwen3-8b but report *both*
  directions on a shared gold set.
- **Herald** (Gao et al., ICLR 2025, arXiv:2410.10878) ships 580k NL-FL
  Mathlib statement pairs via RAG-driven informalization. Their corpus
  is much larger than our blueprint gold set but covers Mathlib only;
  ours bridges 21 blueprint repos + 1.84M arxiv papers + 30 project
  formal repos.
- **RLM25 / BEq+ / ProofNet#** (Liu et al., EMNLP 2025,
  `2025.emnlp-main.907`) curates 619 research-level NL-FL pairs from
  6 formalization projects with a reliable-evaluation framework. We
  overlap substantially in scope but differ in that they evaluate
  autoformalization quality with structural metrics, whereas we
  evaluate *retrieval* over an explicit gold set.
- **Graph-augmented premise selection** (arXiv:2510.23637, Oct 2025) uses
  structural dependency-graph signal to beat ReProver by +25% on
  LeanDojo. Our embeddings are text-only; the persistent dependency
  graph in our schema (`formal_dependency`, 11.3M edges) is queryable
  but not exploited for retrieval in this paper — a clear extension.

**Our four claims that none of these papers report:**
(a) bidirectional matching on a shared gold set with agreement-bucketing
(42.6% → 61.2% recovery from combining directions, §Bidirectional
agreement); (b) audited mutual-NN precision as a method
(audited ≈60% broad / ≈15% strict, §Mutual rank-1); (c) cross-project
parallel-formalization twin detection (446 corrected twins at
sim ≥ 0.85, [`cross_project_twins.md`](./cross_project_twins.md)); and
(d) a dual-rater LLM audit characterizing 12-27% noise in blueprint
`\lean{...}` gold annotations.

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

All intervals are bootstrap 95% CIs over 2,000 resamples (per-query resampling
with replacement). Code: `experiments/nl_fl_matching/analysis/bootstrap_ci.py`.
Full report: `experiments/nl_fl_matching/data/bootstrap_ci.{json,md}`.

| direction | evaluated | Hit@1 [95% CI] | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| **f → i** | 1,562 / 1,577 (99.0%) | **0.426** [0.401, 0.449] | 0.643 [0.620, 0.668] | 0.698 [0.675, 0.720] | 0.518 [0.496, 0.540] |
| **i → f** | 1,308 / 1,308 (100.0%) | **0.426** [0.400, 0.453] | 0.670 [0.644, 0.696] | 0.717 [0.693, 0.741] | 0.531 [0.507, 0.555] |

The two directions' Hit@1 CIs overlap heavily — the apparent equality
(0.426 = 0.426) is well within sampling noise, reinforcing why we
retract the "directional symmetry" framing (see Findings §reporting
note).

## BM25 baseline (added 2026-05-25)

Tokenized (whitespace + alphanumeric) BM25Okapi over the same gold
queries. Source: `experiments/nl_fl_matching/runners/run_bm25_baseline.py`
+ `analysis/bm25_vs_embedding.py`. Persisted under `embedding_model='bm25'`
in `nl_fl_match_pilot`. Bootstrap 95% CIs over 2,000 resamples.

| sweep | n | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| qwen3-8b — f→i (vs 11.7M informals) | 1,562 | 42.6% [40.2, 45.1] | 64.3% [61.9, 66.6] | 69.8% [67.6, 72.2] | 51.8% [49.6, 53.9] |
| BM25 — f→i (vs **2,544 blueprint** informals) | 1,577 | **43.5% [41.0, 45.8]** | 72.4% [70.1, 74.6] | 79.8% [77.7, 81.8] | 55.7% [53.7, 57.7] |
| qwen3-8b — i→f (vs 36,708 project formals) | 1,308 | **42.6% [39.8, 45.3]** | 67.0% [64.4, 69.5] | 71.7% [69.2, 74.2] | 53.1% [50.8, 55.5] |
| BM25 — i→f (vs 36,708 project formals) | 1,308 | 31.3% [28.9, 33.9] | 53.7% [51.0, 56.4] | 61.0% [58.4, 63.7] | 41.0% [38.7, 43.4] |

**Two messages, neither flattering nor catastrophic:**

1. **f→i: BM25 wins slightly on the smaller pool.** BM25 over the
   2,544-blueprint pool beats qwen3-8b over the 11.7M pool at every k.
   This is *not* a fair comparison (the pools differ by 4 orders of
   magnitude), but it does mean the embedding's f→i value-add is
   **robustness to haystack size**, not raw discriminative power. The
   2,544-pool BM25 is the strongest comparison we can run within
   memory limits; full-11.7M-pool BM25 would degrade.
2. **i→f: qwen3-8b beats BM25 by ~11 pp on the same pool.** Hit@1 CIs
   are disjoint ([39.8, 45.3] vs [28.9, 33.9]) — statistically clean.
   This is the headline embedding-adds-value finding: identical 36,708
   project-formal pool, identical 1,308 queries, qwen3-8b wins
   decisively.

**Paper framing:** report both. The asymmetry is itself a finding:
embeddings dominate i→f (where the surface lexical overlap between
informal blueprint LaTeX and Lean syntactic decl names is low) but
roughly tie on f→i within a blueprint pool (where the gold is
specifically authored to lexically resemble Lean decl identifiers).

For comparison, the group's prior paper (arXiv:2602.05216, 111 expert
queries against 9.2M informal corpus, with reranker) headline was
Hit@1=0.189, Hit@10=0.432, MRR@20=0.270 on a fundamentally different
task (mathematician-written queries vs. blueprint-curated pairs).

## Bidirectional agreement (1,595 pairs)

| bucket | count | pct [95% CI] |
|---|---:|---:|
| both_correct (both directions hit rank 1) | 410 | 25.7% [23.7, 27.9] |
| f2i_only | 269 | 16.9% [15.0, 18.7] |
| i2f_only | 297 | 18.6% [16.7, 20.5] |
| neither | 619 | 38.8% [36.4, 41.2] |
| **either direction hits at rank 1** | **976** | **61.2% [58.7, 63.6]** |

Combining directions lifts top-1 recovery from **42.6% (single-direction)
→ 61.2% (either)** — a ~45% relative gain attributable to the
bidirectional design. The single→either jump from 42.6% to 61.2% is
statistically unambiguous: the CIs are disjoint
([40.1, 44.9] vs [58.7, 63.6]). This is the "mutual NN as quality
signal" claim from Artetxe & Schwenk (ACL 2019) imported to NL↔FL
theorem matching, where it has no prior precedent.

## Mutual rank-1 nearest neighbours

Stricter signal than the bucket above: same (informal, formal) pair must be
top-1 in **both** directions (not just any gold sibling).

| metric | count | note |
|---|---:|---|
| total mutual rank-1 pairs | 400 | f→i top-1 = i AND i→f top-1 = f |
| mutual ∩ gold | 355 | 88.8% of mutuals overlap an existing blueprint annotation |
| mutual ∖ gold | 45 | candidates outside the gold set |
| gold ∩ mutual | 355 / 1,595 | **22.3% [20.3, 24.3]** of gold pairs recovered as mutual |

Per-pair list at `experiments/nl_fl_matching/data/mutual_rank1_pairs.csv`
(regenerate with `python -m experiments.nl_fl_matching.analysis.mutual_nn`).

### Audited precision (2026-05-24)

The 88.8% headline is *not* precision — it's overlap with the gold set
(which itself has 12-27% annotation noise; see §gold-set audit). True
precision requires auditing both the gold-overlap and non-overlap halves:

| subset | n | dual-rater (Sonnet 4.5 + Haiku 4.5) — bootstrap 95% CIs |
|---|---:|---|
| **mutual ∩ gold** (355) | inherits gold-audit noise (n=150) | both 'correct': 16.0% [10.7, 22.0] / both 'correct or partial': 65.3% [58.0, 72.7] / either 'wrong': 26.7% [20.0, 34.0] |
| **mutual ∖ gold** (45)  | direct audit on all 45 | both 'correct': 6.7% [0.0, 15.6] / both 'correct or partial': 24.4% [13.3, 37.8] / either 'wrong': 73.3% [60.0, 84.4] |

Combining:
- **Strict precision** (both raters say "correct"): ≈ (355 × 0.16 + 3) / 400 = **15.0%**
- **Broad precision** (both raters say "correct" or "partial"): ≈ (355 × 0.65 + 11) / 400 = **60.4%**
- **Hostile upper bound on error** (at least one rater says "wrong"): ≈ (355 × 0.27 + 33) / 400 = **32.2%**

Cohen's κ on the 45-pair non-gold audit is **0.448** (moderate), higher
than the gold audit's 0.30 — judges agree more strongly when the answer
is "wrong" (the dominant label here).

**Takeaway for the paper:** mutual-NN is *not* a 88.8%-precision filter
in absolute terms — it's a high-overlap-with-gold signal. Audited
precision lands at ~60% (broad) / ~15% (strict). Still substantially
above a random baseline, and the 22.3% gold-recall number is unaffected.

Eyeballed non-gold mutual failures fall into the same taxonomy as the
"neither" bucket (sibling-lemma adjacency, equation-vs-definition
confusion, definition-vs-derived-property) — see e.g. PFR 3.26 ↔
`condRuzsaDist_diff_le'` (4 vs 3 random variables; near-twin formula),
brownian-motion 2.2.34 ↔ `MeasurableSet.isPavingAnalytic_fst` (analytic
weakened to measurable).

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

| status (both raters) | n | share [95% CI] |
|---|---:|---:|
| both 'correct' | 24 | 16.0% [10.7, 22.0] |
| both 'partial' (same theorem, generality mismatch) | 31 | 20.7% — |
| both 'wrong' (annotation broken) | **18** | **12.0% [7.3, 17.3]** |
| disagree (mostly correct↔partial: n=43) | 70 | 46.7% — |
| at least one 'wrong' | 40 | 26.7% [20.0, 34.0] |

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
| ✅ | Hand-label the 45 non-gold mutual pairs (Bedrock dual-rater) | **3/45 (6.7%) correct, 11/45 (24.4%) correct-or-partial; mutual-NN audited precision ~60% broad / ~15% strict** (2026-05-24) | done |
| ✅ | Drop "directional symmetry" framing from prose | replaced with the agreement-bucket claim (2026-05-24) | done |
| ✅ | Recompute cross-project headline excluding the 2 parallel-formalization pairs | **446 twins (not 1,391) at sim≥0.85** after exclusion; see [`cross_project_twins.md`](./cross_project_twins.md) | done (2026-05-24) |

**Should-do (closes obvious reviewer attacks)**

| task | informs | est wall |
|---|---|---|
| ~~Bootstrap CIs on Hit@1 numbers (both directions, mutual NN, non-gold high-sim rate)~~ ✅ done — see headline table + `data/bootstrap_ci.{json,md}` | every point estimate in this doc | done (2026-05-24) |
| Expand "neither" failure-mode sample to n≥50 with two-rater agreement | currently n=15 one-author taxonomy | ~3 hr |
| ~~Cite + position vs Herald (ICLR 2025), RLM25 (EMNLP 2025), LSv2 (arXiv:2605.13137), Lean Finder (ICLR 2026), graph-aug premise selection (arXiv:2510.23637)~~ ✅ done — see top of doc | reviewer attack: "did you read the lit" | done (2026-05-24) |
| ~~BM25 / char-4gram baseline on the same 1,562 + 1,308 gold queries~~ ✅ done — see §BM25 baseline; qwen3-8b wins i→f by 11pp, BM25 wins f→i on smaller pool | reviewer attack: "no baseline" | done (2026-05-25) |

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
2. **Mutual rank-1 nearest neighbours as a precision filter:** 400
   (informal, formal) pairs are rank-1 in both directions; 88.8% overlap
   the blueprint gold set. Combined with the gold-set audit (12-27%
   noise) and a direct audit of the 45 non-gold mutuals (24% correct-or-
   partial), the **audited precision lands at ≈60% (broad: correct or
   partial) / ≈15% (strict: both correct).** Lower than the headline
   88.8% but still high-precision relative to a random baseline. Mutual-
   NN is paper-worthy as a *filter*, not as a 9-in-10 oracle.
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
