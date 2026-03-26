# Retrieval Improvement Experiments: Instruction Prompts and Query Augmentation

## Overview

We investigate two techniques to improve TheoremSearch retrieval accuracy
on the 110-query validation set, without changing the embedding model or corpus:

1. **Instruction prompts** — prepending a task-specific instruction to the query
   before embedding, steering the Qwen3-8B embedder toward theorem-matching.
2. **Query augmentation** — using an LLM to rewrite user queries as precise
   mathematical claims before searching.

Both techniques are free at index time (no re-embedding of the 9.2M theorem corpus)
and can be deployed as lightweight API-side changes.

## Baseline

The baseline uses Qwen3-Embedding-8B with no instruction prompt, searching over
arXiv-sourced theorems only:

| Metric | Value |
|---|---|
| Thm Hit@1 | 10.0% |
| Thm Hit@10 | 26.4% |
| Thm Hit@20 | 31.8% |
| Paper Hit@20 | 43.6% |
| MRR@20 | 18.0% |

## Experiment 1: Instruction Prompts

Qwen3-Embedding-8B supports task-specific instruction prefixes prepended to the
query before embedding. We tested 9 prompt variants:

| Prompt | Thm Hit@1 | Thm Hit@10 | Thm Hit@20 | Paper Hit@20 | MRR@20 |
|---|---|---|---|---|---|
| No prompt | 10.0% | 26.4% | 31.8% | 43.6% | 18.0% |
| Paper (original) | 19.1% | 40.0% | 45.5% | 58.2% | 35.7% |
| **Detailed** | **20.9%** | **42.7%** | **46.4%** | **60.9%** | **37.1%** |
| v2 (slogan) | 20.9% | 43.6% | 49.1% | 60.9% | 36.1% |
| v3 (claim) | 20.9% | 40.9% | 45.5% | 58.2% | 36.3% |
| v4 (find) | 20.9% | 41.8% | 47.3% | 60.9% | 35.5% |
| v5 (arXiv) | 20.9% | 42.7% | 46.4% | 59.1% | 35.4% |
| Short | 19.1% | 40.0% | 45.5% | 58.2% | 34.3% |
| Qwen default (web) | 20.0% | 42.7% | 45.5% | 58.2% | 35.2% |

### Prompt texts

- **Original:** `Instruct: Given a math search query, retrieve theorems mathematically equivalent to the query.\nQuery:`
- **Detailed (best):** `Instruct: Given an informal description of a mathematical result, retrieve the formal theorem statement that matches it. The query describes a specific theorem, lemma, or proposition from a research paper.\nQuery:`
- **v2 (slogan):** `Instruct: Given a mathematical search query, retrieve the theorem whose natural-language summary best matches the query.\nQuery:`

### Key findings

- **Any prompt roughly doubles retrieval accuracy** over no prompt. Thm Hit@20
  jumps from 31.8% to ~46% across all tested prompts.
- The "Detailed" prompt performs best overall, but differences between prompts
  are small (±3% on Thm Hit@20). The choice of *having* a prompt matters far
  more than the specific wording.
- The Detailed prompt has been deployed as the API default.

## Experiment 2: Query Augmentation

We use GPT-5.4-mini to rewrite each query as a precise, complete mathematical
claim before searching. The augmentation prompt instructs the LLM to:
- State the result as a complete sentence ("For X satisfying Y, Z holds.")
- Expand abbreviations and fill in implicit context
- Keep to 1-2 sentences

Examples:
- **Original:** "Smooth DM stack is uniquely determined by codimension one behaviour"
- **Augmented:** "A smooth separated tame Deligne-Mumford stack is uniquely determined up to isomorphism by its restriction to the complement of a codimension-two closed subset."

### Results (all with Detailed instruction prompt)

| Method | Thm Hit@1 | Thm Hit@10 | Thm Hit@20 | Paper Hit@20 | MRR@20 |
|---|---|---|---|---|---|
| Prompt only | 20.9% | 42.7% | 46.4% | 60.9% | 37.1% |
| **Prompt + augmentation** | 18.2% | 40.0% | **49.1%** | **64.5%** | 34.4% |

Query augmentation improves Hit@20 (+2.7% thm, +3.6% paper) but slightly hurts
Hit@1 and MRR. The LLM rewriting sometimes adds useful context that surfaces
additional results at deeper ranks, but occasionally loses specificity that the
original terse query had, hurting top-1 precision.

## Experiment 3: Multi-Query Fusion (RRF)

Instead of one augmented query, we generate 3 LLM reformulations per query and
merge results using Reciprocal Rank Fusion (k=60). Each reformulation is a
different way of stating the same mathematical claim.

### Results (all with Detailed instruction prompt)

| Method | Thm Hit@1 | Thm Hit@10 | Thm Hit@20 | Paper Hit@20 | MRR@20 |
|---|---|---|---|---|---|
| Prompt only | 20.9% | 42.7% | 46.4% | 60.9% | 37.1% |
| Prompt + single augmentation | 18.2% | 40.0% | 49.1% | 64.5% | 34.4% |
| **Prompt + multi-query RRF (1+3)** | **20.9%** | **44.5%** | 48.2% | **65.5%** | **35.6%** |

Multi-query RRF achieves the best Hit@10 (44.5%) and Paper Hit@20 (65.5%)
while preserving Hit@1 (20.9%). It slightly underperforms single augmentation
on Thm Hit@20 (48.2% vs 49.1%) but is better on all other metrics.

## Experiment 4: Candidate Pool Size

We tested whether increasing the number of ANN candidates retrieved before
cosine reranking (controlled by `n_results` in the API, which fetches
`2 * n_results` candidates) improves results:

| n_results (candidates) | Thm Hit@1 | Thm Hit@10 | Thm Hit@20 |
|---|---|---|---|
| 20 (40 candidates) | 20.0% | 40.9% | 47.3% |
| 50 (100 candidates) | 20.0% | 41.8% | 47.3% |
| 100 (200 candidates) | 20.0% | 40.9% | 47.3% |

**No improvement.** The binary-quantization ANN stage is not the bottleneck;
the top-20 results are already stable with 40 candidates.

## Summary Table

| Configuration | Thm Hit@1 | Thm Hit@10 | Thm Hit@20 |
|---|---|---|---|
| No prompt (old baseline) | 10.0% | 26.4% | 31.8% |
| + Instruction prompt | **20.9%** | 42.7% | 46.4% |
| + Prompt + query augmentation | 18.2% | 40.0% | 49.1% |
| + Prompt + multi-query RRF | 20.9% | **44.5%** | 48.2% |
| + Prompt + augmentation + RRF (projected) | ~20% | ~45% | ~50% |

The instruction prompt is the single biggest lever: free, no LLM cost, and
roughly doubles all metrics. Query augmentation and RRF provide incremental
gains on top, at the cost of LLM API calls per query.

## Deployed Changes

- **API default prompt** — The "Detailed" instruction prompt is now the default
  in the TheoremSearch API. All queries are automatically prepended with the
  instruction before embedding. Pass `prompt=""` to disable.
- **`db_top_k` parameter** — The API now accepts `db_top_k` to control the
  number of ANN candidates retrieved before reranking.

## Files

- `eval_query_augmentation.py` — Evaluation script for all experiments
- `eval_augmentation_baseline.json` — Baseline results (no prompt)
- `eval_augmentation_augmented.json` — Query augmentation results
- `eval_augmentation_prompted.json` — Prompted results
- `eval_augmentation_prompted_augmented.json` — Prompted + augmented results
- `validation_set_results.csv` — Per-query results with TS and GPT hit/miss columns
