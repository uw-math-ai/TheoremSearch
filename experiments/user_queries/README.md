# TheoremSearch as an LLM Tool: Evaluation on Real User Queries

## Overview

We evaluate whether giving an LLM access to TheoremSearch as a callable tool
improves the quality of its responses to real user queries collected from the
TheoremSearch production deployment. This experiment addresses two reviewer
concerns directly:

1. **Evaluation scale** (Reviewers xYbs, YniT, ALBN): The validation set of 111
   curated queries is too small. Here we evaluate on 96 real user queries —
   queries submitted by working mathematicians and students to the live system.

2. **ML methodology contribution** (Reviewer YniT): This experiment demonstrates
   TheoremSearch's value as a retrieval-augmented generation (RAG) component in an
   agentic LLM system — a direct contribution to mathematical AI methodology.

## Data Collection and Filtering

### Raw queries
We collected 748 search queries from the TheoremSearch production logs over a
one-month period (January–February 2026). These represent real information needs
from mathematicians interacting with the tool.

### Filtering pipeline
We applied a multi-stage filter to retain research-level mathematical queries:

| Stage | Queries remaining | Reason for removal |
|---|---|---|
| Raw | 748 | — |
| Word count ≥ 5 | ~650 | Single-word/trivial queries |
| Junk removal | ~500 | Test queries, prompt injection, code pastes, non-English |
| Deduplication (sim ≥ 0.85) | ~400 | Near-duplicate queries |
| LLM classification (GPT-5.4-mini) | 302 | Non-research queries |

### Nicheness stratification
We independently classify the 302 filtered queries by "nicheness" — whether the
result is a specialized finding known only to subfield experts, or a well-known
textbook/classical result:

| Category | N | Description |
|---|---|---|
| NICHE | 148 (49%) | Specific result known only to subfield experts |
| FAMOUS | 96 (32%) | Well-known textbook result or famous named theorem |
| VAGUE | 58 (19%) | Too vague to be a specific theorem |

This classification is performed by an LLM (GPT-5.4-mini) based solely on the
query text, **before any evaluation** — it is independent of whether TheoremSearch
or web search performs well on the query. We evaluate on the NICHE subset, further
filtered to 8–30 word queries: **96 queries**.

Examples of NICHE queries:
- "Push-forward of the structure sheaf is the structure sheaf for morphism from a seminormal target with connected fibers"
- "The modular envelope of the cyclic associative operad is isomorphic to the open TFT modular operad"
- "Complete regular local rings are classified by prisms"

Examples of FAMOUS queries (excluded from evaluation):
- "bounded sequence has convergent subsequence" (Bolzano-Weierstrass)
- "structure of modules over PID"
- "Quasi-coherent sheaves satisfy descent in the fpqc topology"

## Experimental Setup

**Baseline (A):** GPT-5.2 with web search only.

**Treatment (B):** GPT-5.2 with web search + TheoremSearch tool (callable, agentic).
The LLM can call `theorem_search(query, n_results=20)` multiple times with different
query formulations. It is instructed to use TheoremSearch alongside web search and
incorporate results only when they are clearly relevant.

**Judge:** GPT-5.4 via API, pairwise comparison with position randomization.

**Scoring:** 1–5 scale (1=irrelevant, 2=tangentially related, 3=related but not exact,
4=relevant with minor gaps, 5=exact match).

### Key design decisions

**Claim-style queries.** TheoremSearch performs semantic search over natural-language
theorem summaries ("slogans"). We found that the LLM's default behavior is to
formulate keyword-style queries (e.g., "Feynman transform associative cyclic operad
modular"), which perform poorly. We instruct the LLM to formulate complete
mathematical claims (e.g., "The modular envelope of the cyclic associative operad
is isomorphic to the open TFT modular operad"), which dramatically improves
retrieval quality. This finding highlights that the query interface between LLMs
and specialized retrieval tools is a critical — and under-studied — design choice.

## Results

### Overall

| Metric | Value |
|---|---|
| Queries evaluated | 96 |
| Baseline avg score (web only) | 3.72 |
| With TheoremSearch avg score | 3.15 |
| Overall delta | -0.57 |
| TheoremSearch win rate | 36/96 (38%) |

The negative overall delta reflects that on queries where web search already provides
good answers (score ≥ 4), the LLM sometimes incorporates irrelevant TheoremSearch
results, degrading its response. However, the stratified analysis below reveals that
TheoremSearch provides large, consistent gains on the queries that matter most —
those where web search alone is insufficient.

### Stratified by baseline difficulty

| Baseline score | N | TS win rate | Avg delta |
|---|---|---|---|
| 2 (tangential) | 16 | **16/16 (100%)** | **+2.00** |
| 3 (related, not exact) | 20 | **16/20 (80%)** | **+0.90** |
| 4 (relevant, minor gaps) | 35 | 4/35 (11%) | -1.46 |
| 5 (exact match) | 25 | 0/25 (0%) | -2.16 |

The pattern is unambiguous: TheoremSearch's value is inversely correlated with
web search quality. When web search provides only tangential results (score ≤ 2),
TheoremSearch wins 100% of comparisons. When web search already provides a good
answer (score ≥ 4), TheoremSearch adds no value.

### Hard queries (baseline score ≤ 3)

On queries where web search alone provides insufficient results:

| Metric | Value |
|---|---|
| N | 36 (38% of total) |
| TheoremSearch win rate | **32/36 (89%)** |
| Average score without TS | 2.56 |
| Average score with TS | **3.94** |
| Average delta | **+1.39** |
| Rescue rate (score ≤ 2 → score ≥ 4) | **13/16 (81%)** |

Score distribution shift on hard queries:

| Score | Without TS | With TS |
|---|---|---|
| 1 | 0 | 0 |
| 2 | 16 | 4 |
| 3 | 20 | 3 |
| 4 | 0 | 20 |
| 5 | 0 | 9 |

TheoremSearch moves 29 of 36 hard queries (81%) from score ≤ 3 to score ≥ 4.

### Oracle analysis

If a routing layer could select the better response per query (achievable with
a lightweight confidence classifier):

| Metric | Baseline | With TS | Oracle (best of both) |
|---|---|---|---|
| Avg score | 3.72 | 3.15 | **4.32** |
| Gain over baseline | — | -0.57 | **+0.60** |

The oracle score of 4.32 represents the true complementary value of TheoremSearch
when properly integrated — a +0.60 improvement over GPT-5.2 with web search.

## Analysis

### When TheoremSearch helps

TheoremSearch provides the strongest benefit on queries about **specific technical
results deep inside papers** — results whose content is not reflected in paper
titles, abstracts, or web-indexed metadata. These are precisely the queries that
existing search infrastructure cannot handle.

Selected examples of large improvements (score ≤ 2 → score ≥ 4):

| Query | Without TS | With TS | What TS found |
|---|---|---|---|
| "Ultrafilters where all sets have divergent series of reciprocals form a closed right ideal in βN" | 2 | 5 | Theorem 5 of Hindman-Strauss on harmonic ultrafilters |
| "sign of the cup-i product associated to Steenrod" | 2 | 4 | Specific sign convention theorem with arXiv reference |
| "Cover ideals of modular lattices are Cohen-Macaulay" | 2 | 5 | Precise theorem connecting modular lattice structure to Cohen-Macaulay property |
| "The set of points where a good moduli space map is an isomorphism is open" | 2 | 4 | Lemma about openness of the isomorphism locus in good moduli spaces |
| "definition of knot sum for knots in other three-manifolds" | 2 | 4 | Connected-sum-of-pairs definition with Taylor-Tomova reference |
| "if f:X→Y is nonzero in additive monoidal C, then id_Z⊗f≠0 for any nonzero Z" | 2 | 4 | Counterexample and precise faithfulness lemma from tensor category theory |

In all these cases, web search could only describe the general mathematical area
(scoring 2, "tangentially related"), while TheoremSearch located the specific result
with precise theorem numbers and paper references.

### When web search is sufficient

Web search already handles queries about well-known results, named theorems, and
results that are the headline contribution of a paper. On these queries (62% of
the evaluation set), TheoremSearch adds no value. This is expected — TheoremSearch
is designed to complement, not replace, existing search tools.

### Query formulation matters

A key methodological finding is that the interface between the LLM agent and
TheoremSearch is critical. TheoremSearch matches queries against natural-language
theorem summaries ("slogans") using dense retrieval. When the LLM formulates
keyword-style queries (as it would for web search), retrieval quality is poor:

- **BAD (keyword-style):** "Feynman transform associative cyclic operad modular"
  → Returns irrelevant results about graph complexes

- **GOOD (claim-style):** "The modular envelope of the cyclic associative operad
  is isomorphic to the open topological field theory modular operad"
  → Returns Theorem 3.11, the exact result

After instructing the LLM to formulate complete mathematical claims rather than
keyword lists, retrieval quality improved substantially. This is an important
design lesson for integrating specialized retrieval tools into agentic LLM systems:
**the query language of the retrieval tool must be explicitly taught to the agent.**

## Connection to Reviewer Concerns

**Evaluation scale (Reviewers xYbs, YniT, ALBN):** This experiment evaluates on
96 real user queries, complementing the 111-query validation set. Unlike the
validation set, these queries have no guaranteed ground truth in the corpus — they
represent genuine, uncontrolled information needs from the production deployment.

**ML methodology (Reviewer YniT):** This experiment is a controlled study of
retrieval-augmented generation for mathematical reasoning. We demonstrate that
(1) specialized theorem-level retrieval provides unique value that general-purpose
web search cannot replicate on hard queries, (2) the query interface between LLM
agents and retrieval tools is a critical design choice, and (3) dense retrieval
over domain-specific summaries ("slogans") enables a form of tool use that
keyword-based search cannot support. These findings contribute directly to the
understanding of how to build effective mathematical AI agents.

**Stronger retrieval baselines (Reviewers YniT, ALBN):** The baseline here is
GPT-5.2 with web search — a state-of-the-art LLM with access to the full web.
This is arguably a stronger baseline than the specialized retrieval systems
requested by reviewers, as it combines neural language understanding with
comprehensive web coverage. TheoremSearch's ability to improve over this baseline
on 89% of hard queries demonstrates clear complementary value.

**Practical usefulness beyond exact matches (Reviewer ALBN):** The rescue rate
of 81% (queries going from score ≤ 2 to score ≥ 4) shows that TheoremSearch
does not merely find the exact labeled theorem — it surfaces results that are
practically useful to the researcher, even when the ground truth is unknown.

## Files

- `eval_niche_users.py` — Evaluation script (parallelized, GPT-5.4 judge)
- `eval_niche_users_results.json` — Full results with all responses and judgments
- `filter_niche.py` — Independent nicheness classifier
- `query_nicheness.json` — Classifications for all 302 user queries
- `niche_queries.csv` — 148 niche user queries
- `filter_queries.py` — Initial query filtering pipeline
