# Results

All numbers are from our runs. Retrieval corpus = 388,105 formal slogans (Mathlib, `v2`),
embedded with Qwen3-Embedding-8B (4096-d). Gold premises = `sig`/`extends`/`field` dependency
edges from lean-graph. Splits are module-held-out (whole files held out, no leakage).

## 1. Retrieval quality (premise retrieval over Mathlib)

Recall@k of a target's gold premises, forbidden-masked, on the held-out test set.

| method | R@10 | R@100 | rare@100 | common@100 |
|---|---|---|---|---|
| raw cosine (untuned embedding) | 0.05 | 0.16 | 0.65 | 0.03 |
| frequency prior (query-independent) | 0.15 | 0.38 | ~0 | high |
| learned query head (300k train) | 0.24 | 0.54 | 0.78 | 0.38 |

- **Scaling**: R@100 rises 0.46 (10k) → 0.52 (60k) → 0.54 (300k) — diminishing returns; rare-premise
  recall is flat (~0.78, embedding-bound), common-premise recall is what grows with data.
- **Rarity control**: cosine already finds rare/specific premises (they're semantically near the
  target); the learned head's gain is mostly on common/foundational premises (the prior's territory),
  but it still beats the prior on rare premises (0.78 vs ~0).
- **Query-shuffle control**: feeding a target's gold-eval a *different* target's query collapses
  recall 0.55 → 0.01. So the learned head is ~98% query-conditioned — it did **not** bake in a
  popularity prior.

## 2. Retrieval-augmented formalization — Mathlib (familiar library)

Formalize informal → formal, no-RAG vs RAG (retrieved premise names in context). Hand-judged
strict correctness (✓ = same proposition).

| formalizer | no-RAG | RAG | relative |
|---|---|---|---|
| Qwen3-8B (reconstruction eval, n=24) | 12.5% | 25.0% | 2.0× |
| Qwen3-8B (ProofNet, vetted gold, n=22) | 13.6% | 31.8% | 2.3× |
| Sonnet (ProofNet, vetted gold, n=12) | 83% | 75% | no help / slight hurt |

- Across model sizes (0.6/1.7/4/8B) the **relative** RAG lift grows as the model shrinks
  (premise-name recall: 0.6B 5.4×, 8B 2.2×).
- On Mathlib, a strong model (Sonnet) already knows the API; retrieval is redundant and occasionally
  distracting (it sometimes dropped a hypothesis it would otherwise include).
- RAG wins are name-grounding: it supplies the correct Mathlib identifier the model otherwise invents
  (`Metric.ball`, `IsSeparable`, `SecondCountableTopology`, `∈ s` membership, …).

## 3. Unfamiliar library (brownian-motion, v4.30) — the strong-model result

Target library extracted with `lean/extract_lib_decls.lean` (1,144 indexable decls; 18 sandboxed
targets). Formalizer = **Sonnet**, verified sandboxed (no source/gold access). Metric =
**hand-judged correctness** vs the real declaration; typecheck (well-formedness) and compute are
secondary — typecheck is a gate, trivially gamed by retrying, not the result.

| condition | what the model gets | correctness | typecheck | tokens | tool calls |
|---|---|---|---|---|---|
| no-RAG | nothing | 0/18 (0%) | 0/18 | 10.4k | 1 |
| RAG | top-15 retrieved premises (name+sig) | 9/18 (50%) | 10/18 | 28.8k | 2 |
| library-access | grep the whole pruned library | 14/18 (78%) | 15/18 | 145.3k | 99 |
| RAG + library | both (retrieval first, search fallback) | 14/18 (78%) | 16/18 | 129.3k | 75 |

- **Library knowledge is the bottleneck**, not capability: a frontier model scores 0% on an
  unfamiliar library with no access.
- **Retrieval is the compute-efficient point**: RAG reaches 50% at ~20% of the tokens and ~2% of the
  tool calls of full search.
- **Library search tops out at 78%**; RAG+library matches it (78%) more cheaply. RAG's ceiling is
  **retrieval recall** (top-15 ≈ 0.28), not the model.
- **Typecheck overstates every grounded condition** (56/83/89%) vs correctness (50/78/78%) — the gap
  is compiling-but-wrong statements, which is exactly why we report correctness.

**Compiler-in-the-loop variant** (K=3 retries, 13 standalone targets) in
[`compiler_loop_results.md`](compiler_loop_results.md): correctness no-RAG 0% / RAG 77% / library 85%
/ RAG+library 69% — the loop mainly lets RAG repair malformed attempts.

## 4. Large corpus, post-cutoff Mathlib — retrieval at scale

24 theorems added in the v4.30 cycle (unseen by the model), retrieved over the older `v2` corpus
(~295k decls). Full write-up + provenance notes in [`large_corpus_results.md`](large_corpus_results.md).

| condition | correctness (exact + hi-confidence-equiv) | tokens | tool calls |
|---|---|---|---|
| no-RAG | 5/24 (21%) | 52k | 276 |
| RAG | 8/24 (33%) | 14k | 68 |
| library-search | 6/24 (25%) | 52k | 275 |
| RAG + library | 8/24 (33%) | 37k | 188 |

- **Corpus-size crossover**: unlike the small brownian library (where search beat RAG), at Mathlib
  scale **RAG ≥ library search** (33% vs 25%) at ~40% the token cost — grep can't enumerate 295k decls.
- Absolute scores are low by construction (obscure post-cutoff targets, name-blanked back-translated
  queries) and **floored by informalizer quality** (~10/24 fail in every condition because the NL
  query dropped load-bearing detail). The result is the delta between conditions, not the absolute.

## Caveats
- Hand-judged samples are small (n=12–24) and single-judge; report paired **McNemar** for the
  per-condition comparisons (same targets across conditions).
- Mathlib informal queries are model-generated slogans; the unfamiliar-library and large-corpus
  queries are back-translated. For RAG-vs-no-RAG *deltas* this cancels (same query both arms);
  ProofNet uses human-written informal as an independent check.
- We report **correctness**, not typecheck. Typecheck (well-formedness) is shown only as a secondary
  gate — it is trivially gamed by retrying and overstates correctness (compiling-but-wrong statements).
- **Provenance/version to pin** (large-corpus): the `v2` corpus Mathlib rev is recorded in the
  ingestion provenance (`projects.mathlib_rev`); the target diff used a v4.29 listing as a proxy and
  should be re-aligned to it before the "never-seen" claim is formalized.
