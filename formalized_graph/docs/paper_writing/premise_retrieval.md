# Premise retrieval + RAG-augmented formalization

Distilled facts from the project committed at
`experiments/lean_premise_retrieval/` (authored by @aurasoph,
2026-05-25 snapshot). This doc is the paper-writing-level summary;
the project's own `README.md` + `docs/RESULTS.md` are the canonical
source for numbers.

## Retrieval task

NL query (slogan or back-translated statement) → ranked list of formal
decl names predicted to be premises of the target. Corpus is the full
v2 formal side (388,105 decls). Embedding model: Qwen3-Embedding-8B
(`qwen3-8b` in [`schema.md`][schema], 12.2M rows). Premise label
supervision: lean-graph (Evan Wang) `sig`/`extends`/`field` edges of the
target's signature.

### Retrieval-quality headlines (Mathlib v2, 388k decls)

| retriever | Recall@100 | notes |
|---|---:|---|
| raw cosine over Qwen3-8B slogans | 0.16 | floor |
| frequency prior (popularity) | 0.38 | label-distribution control |
| **learned linear query head** | **0.54** | 1× `nn.Linear(4096, 4096, bias=False)`, identity-init, contrastive on 300k samples (random neg N=1536 + popular neg N=512), AdamW, 6 epochs |

Rare-premise recall saturates at ~0.78 (embedding-bound); common-premise
scales with train size 0.03 → 0.38.

## Formalization task

Sandboxed model (no library source access): NL description + retrieved
premises → Lean statement. Typecheck against built Mathlib + optionally
target library. **Correctness is hand-judged**; typecheck rate is a
secondary gate (overstates by 5–17 pp; e.g. 22/24 typecheck vs 5/24
correct on no-RAG large-corpus).

### Headline numbers, 5 settings

| setting | model | n | no-RAG | RAG | other arms |
|---|---|---:|---:|---:|---|
| Mathlib (familiar) | Qwen3-8B | ~30 | 12.5% | **25.0%** | — |
| Mathlib (familiar) | Sonnet (strong) | ~30 | 83% | 75% | — |
| brownian-motion (unfamiliar, sandboxed) | Sonnet | 18 | 0% | **50%** | search 78%; RAG+search 78% |
| brownian-motion + compiler loop K=3 | Sonnet | 13 | — | 50→77% | search 78→85%; RAG+search 78→69% (premature convergence) |
| Mathlib v4.30 post-cutoff | Sonnet | 24 | 21% | **33%** | library-search 25%; RAG+search 33% at ~40% token cost |

"High-confidence-equivalent" metric (large-corpus row): exact match OR
logically equivalent restatement (e.g. `p ∈ primesLE n` ≡ `p.Prime ∧
p ≤ n`). Different endpoint conventions / `EReal↔ENNReal` /
`additive↔multiplicative` do *not* count.

## Methodology callouts (themselves findings)

1. **Sandbox the formalizer.** A tool-enabled agent will read library
   source where the gold lives. RAG arms must run without file/internet
   access.
2. **Forbidden masking.** Retrieval must exclude
   `{target} ∪ transitive-reverse-deps` (via lean-graph). Otherwise the
   answer leaks, or the model proposes circular rewrites.
3. **Typecheck ≠ correctness.** Section 6 of `docs/RESULTS.md` shows
   no-RAG with 22/24 typecheck and 5/24 correct. Score by hand or by
   pairwise equivalence judge; not by typecheck alone.
4. **RAG hurts strong models on familiar libraries.** Sonnet on Mathlib
   loses 8pp (83 → 75) when given retrieved premises — model already
   knows API and re-prompting displaces the correct recall.

## How this fits the EMNLP paper

The project demonstrates **graph-supervised premise retrieval** (via
lean-graph formal-dep edges, embedded in a trained query head) and
**RAG-augmented formalization** on (a) cross-library transfer
(brownian-motion sandboxed) and (b) post-cutoff Mathlib. Both are
controlled for memorization.

Complementary findings already in this paper_writing/ tree:

- [`cross_project_twins.md`][cpt]: 446 dual-rater confirmed formal↔formal
  twins across project boundaries (n=50 audit, extrapolated from 367k
  `cross_project_f2f` matches). This **generalizes the unfamiliar-library
  transfer claim from N=18 to population scale.**
- [`formalization_candidates.md`][fc] + `formalization_candidate_neighborhood`
  (14,084 rows): pre-joined anchor → formal-sibling pairs from the
  **informal-dep** graph (18.3M edges over arXiv prose). Distinct
  supervision source from lean-graph's formal-dep edges.
- [`bidirectional_matching.md`][bm]: 1,595-pair NL↔FL Hit@k/MRR baseline
  using the same Qwen3-Embedding-8B retriever — the embedding floor that
  the trained query head improves over.

## Proposed third arm: informal-dep graph-pack

Aurasoph's "graph signal" is the formal-dep graph used only as
supervision; their retrieval at inference time is cosine over slogans
+ a trained linear head. Our informal-dep graph is a different
signal entirely — it predicts which **NL siblings** an unformalized
statement has, which then jump to formal siblings via `nl_fl_match`.

Three-arm comparison on the same N=24 post-cutoff Mathlib targets:

| arm | retrieval | new vs reuse |
|---|---|---|
| no-RAG | none | reuse `ml30_norag.json` |
| RAG (cosine + learned head) | aurasoph's `FormalRetriever.search_by_vec` | reuse `ml30_rag.json` |
| **graph-pack** | informal-dep two-hop (NL query → anchor → resolved FL siblings via `formalization_candidate_neighborhood`) | new — design in `experiments/lean_premise_retrieval/INTEGRATION.md` |
| library-search | tool-using agent | reuse `ml30_libsearch.json` |

Headline test: McNemar on hand-judged correctness, RAG vs graph-pack
on the same 24 paired targets. Secondary: per-query token-out cost.

## Open questions

- Does informal-dep retrieval surface premises that cosine+head misses,
  or the same premises ranked differently?
- Does the informal-dep graph's value persist under aurasoph's
  forbidden mask (target + reverse-dep closure)? Some anchors may have
  resolved decls entirely inside the forbidden set.
- For the unfamiliar-library setting (where RAG was decisive 0% → 50%):
  does informal-dep help if the library's blueprint is arxiv-indexed?
  brownian-motion's blueprint *is* indexed (it was a cycle-1 smoke-test
  candidate source) so this is testable.

[schema]: ./schema.md
[cpt]: ./cross_project_twins.md
[fc]: ./formalization_candidates.md
[bm]: ./bidirectional_matching.md
