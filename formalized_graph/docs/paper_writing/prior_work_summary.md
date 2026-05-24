# Prior Work — Our Group's Published Paper

PDF: [`../prior_work/2602.05216v2-1-9.pdf`](../prior_work/2602.05216v2-1-9.pdf)
Title: **Semantic Search over 9 Million Mathematical Theorems** (arXiv:2602.05216v2, March 2026)
Authors: Alexander, Leonen, Szeto, Remizov, Tejeda, Alper, Inchiostro, Ilin.

Read this before making claims about the corpus, retrieval setup, or
benchmark numbers — anything in here is already public and the new EMNLP
paper must stay consistent with it.

## Corpus and retrieval (unchanged for new paper)

| component | value |
|---|---|
| total statements | **9.2M** |
| sources | arXiv (99.5%) + ProofWiki, Stacks Project, Open Logic, CRing, Stacks & Moduli, HoTT, Infinitely Large Napkin |
| slogan LLM (default) | DeepSeek V3.1, temperature 0.2, max tokens 1024 |
| slogan context (default) | Body + Abstract |
| embedder | Qwen3-Embedding-8B (4096-dim) |
| index | pgvector HNSW, binary-quantize → Hamming shortlist → cosine rerank |
| shortlist size | `max(200, 12·k)` clamped to `[200, 800]` |
| scoring | `cosine + λ · log(max(citations, 1))` (citation weight optional) |
| reranker (ablation) | Qwen3-Reranker-0.6B over top-100 |

## Evaluation set

- **111 mathematician-written queries** across 14 arXiv tags (mostly AlgGeo, Analysis, PDEs)
- Validation universe: 7,356 papers (math.AG-tagged authors with ≥1 exact match)
- Queries written **blind** by 3 research mathematicians; 2-stage LLM + human verification per query↔theorem pair
- Small-size defense: explicitly cites LeanSearch (50 queries) and ARQMath-3 (78)

## Headline metrics

Reported as `theorem-level / paper-level`, Hit@k + MRR@20.

| method | Hit@1 | Hit@10 | Hit@20 | MRR@20 |
|---|---:|---:|---:|---:|
| Google Search† | – / 0.162 | – / 0.378 | – / 0.378 | – / 0.237 |
| arXiv Search† | – / 0.009 | – / 0.018 | – / 0.027 | – / 0.011 |
| ChatGPT 5.2 + search | – / 0.117 | – / 0.180 | – / 0.198 | – / 0.139 |
| Gemini 3 Pro | – / 0.171 | – / 0.252 | – / 0.270 | – / 0.196 |
| Qwen3 8B (ours) | 0.171 / 0.243 | 0.387 / 0.505 | 0.450 / 0.568 | 0.243 / 0.328 |
| **Qwen3 8B + reranker** | **0.189 / 0.324** | **0.432 / 0.613** | **0.450 / 0.631** | **0.270 / 0.416** |

† paper-level only — can't return individual theorems.

## Ablations reported

- **Context window**: Body / Body+Abstract / Body+IntroSection (Body+IntroSection wins by ~2.6pp Hit@1)
- **Slogan LLM**: Claude Opus 4.5 > Gemini 3 Pro > DeepSeek V3.1 > DeepSeek R1 (Body+Abstract context)
- **Prompt**: prompted vs unprompted (prompted wins on Qwen, loses on Gemma)
- **Embedder**: Gemma 0.3B / Qwen3 0.6B / Qwen3 8B, with/without reranker
- **Embedding space diagnostics**: PCA + UMAP on 10k sample (1k per category × 10 categories)
- **Filter for ablations**: math.AG-tagged, primary-author exact match → 7,356 statements / 8 authors

## What this paper does NOT cover (= our new EMNLP contributions)

1. **No formal Lean theorems in the corpus.** 9.2M is all informal. Our 36,708 sloganed Lean decls across 24 non-Mathlib projects are net new.
2. **No bidirectional retrieval.** Only NL→corpus. The (3) agreement analysis (formal↔informal) is novel.
3. **No agreement / disagreement analysis** as a quality signal — see [literature scan](#) for adjacent prior art (Artetxe & Schwenk margin-based bitext mining, reciprocal-NN reranking).
4. **No per-project breakdown** of yield. We can stratify by repo across the 24 projects (Physlib, SpherePacking, Carleson, PrimeNumberTheoremAnd, etc.).
5. **No same-formality nearest-neighbour analysis.** Our (5a)/(5b) is exploratory but unprecedented in this group's work.

## Constraints this places on the new paper

- **Metric choice locked.** Hit@k + MRR. Don't introduce Recall@k unless framed as a synonym (Hit@k is identical to Recall@1 when there's one gold per query).
- **Eval size lower bound: ~100.** Anything in 100-400 hand-curated is defensible (matches their 111 and literature norms).
- **Shortlist params locked.** `max(200, 12·k)` clamped `[200, 800]`. Use identical numbers so the new paper inherits the prior-paper's latency claim.
- **Reranker should be at least mentioned**, since +2 Hit@1 is on the table essentially for free.
- **Dataset is public.** Cite as `huggingface.co/datasets/uw-math-ai/theorem-search-dataset`.
- **Search tool / API.** Public at `theoremsearch.com`; MCP at `api.theoremsearch.com/mcp`.

## Open Qs the prior paper invites

- They never report **directional asymmetry** because they only have one direction. We do — should that asymmetry get its own table or be folded into the bidirectional-agreement section?
- They explicitly mention "premise selection for formal proof search" as a use case but don't evaluate it. If our paper goes there, that's an extension.
