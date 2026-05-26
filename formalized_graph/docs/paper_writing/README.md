# paper_writing/ — second brain for the EMNLP paper

This directory exists to offload every paper-relevant fact (schemas, sample
rows, API surfaces, scale numbers, experiment summaries, related-work
comparisons) into terse markdown so future sessions can ground themselves
without re-deriving anything from the live system.

## Contents

| file | purpose |
|---|---|
| [`schema.md`](./schema.md) | v2 RDS table schemas, in data-flow order (paper → statement → metadata → slogan → embedding), with one-paragraph explainers. |
| [`samples.md`](./samples.md) | Two real rows per table, chosen so embedding / `lean` / `decl_name` / `docstring` are populated. Embedding vectors shown as `<dim, norm, head, tail>`. |
| [`api_reference.md`](./api_reference.md) | Thin pointer to `api/README.md` (canonical) plus paper-writing-relevant gotchas (e.g. legacy `/search` integer-IDs are not graph-addressable). |
| [`leansearch_v2_comparison.md`](./leansearch_v2_comparison.md) | Working notes comparing our corpus + pipeline against LeanSearch v2. |
| [`prior_work_summary.md`](./prior_work_summary.md) | Distilled facts from the group's prior paper (arXiv:2602.05216) — locked corpus/retrieval/metric choices and what the new EMNLP paper adds on top. PDF lives in [`../prior_work/`](../prior_work/). |
| [`cycle_consistency.md`](./cycle_consistency.md) | Verified pilot numbers for the F → NL → F' experiment (Mathlib + 4 extension repos, n=300). Headlines: dep context lifts Mathlib typecheck 33→63% (Haiku 4.5) / **47→93%** (GPT-5 single-seed). **Multi-seed (n=180 across 3 seeds)** refines to **+32.8pp on pilot / +35.6pp on post-cutoff** (statistically equivalent — memorization defense holds). **Three memorization controls** rule out training-set recall: T-anon-restored = 93% (typing alone), closed-book recall = 35% (memorization floor). **Judge calibration on ConsistencyCheck (n=117)**: Sonnet 80.3% / GPT-5 90.6% accuracy vs human experts. NL→F→NL' loop closure shows graph helps in reverse direction too (+25pp). |
| [`bidirectional_matching.md`](./bidirectional_matching.md) | Headline Hit@k/MRR numbers for the blueprint gold-pair NL↔FL matching experiment (1,595 pairs, qwen3-8b embedding, both directions). Code in `experiments/nl_fl_matching/`. |
| [`formalization_candidates.md`](./formalization_candidates.md) | Schema + how-to-query for the 27,065-row match dataset (CSV + JSONL under `experiments/nl_fl_matching/data/`). Aimed at agents looking for low-hanging fruit to formalize. Includes the 500-anchor dependency-neighborhood walk (RDS table `formalization_candidate_neighborhood`, 14,084 rows). |
| [`smoke_test_candidates.md`](./smoke_test_candidates.md) | The 3 verified unformalized blueprint statements (A, B, F) chosen to drive the first "graph helps prover" comparison. Includes the grep-verification methodology that catches blueprint annotations missing a `\lean{}` macro. |
| [`harness_design.md`](./harness_design.md) | Aristotle-based proof-only comparison harness. Two arms per candidate: no-graph (target + sorry) vs with-graph (target + k=1 resolved-sibling premise pack). Draft Lean signatures, success metrics, budget. |
| [`cross_project_twins.md`](./cross_project_twins.md) | f→f cross-project NN sweep (36,708 project formals, paper-exclusion). **446 twins at sim ≥ 0.85 after excluding two parallel-formalization repo-pairs** (raw count 1,391); 14 at sim ≥ 0.95. |
| [`nongold_random_sweep.md`](./nongold_random_sweep.md) | Strand G: n=500 random non-gold project formals → top-K informals. 9.3% have rank-1 sim ≥ 0.85; ~80% of those are cross-source (Lean ↔ arxiv) matches that the corpus does not yet record. |
| [`figure_style.md`](./figure_style.md) | **Prescriptive** figure-style spec for the paper. Palette (hex), typography, layout, drop-in matplotlib `rcParams` block, drop-in TikZ preamble, prompt template for invoking Claude as a figure emitter. §11 codifies the **dual-plane theme** (red informal / blue formal / green `\lean{}` links). Two worked examples under [`figures/src/`](./figures/src/): `anchor_neighborhood.{tex,py}` is the micro view (one anchor + neighbors, TikZ); `candidate_in_context.py` is the macro view (60+55 nodes spotlit in 3D matplotlib). |
| [`premise_retrieval.md`](./premise_retrieval.md) | Aurasoph's premise-retrieval + RAG-formalization project (committed under `experiments/lean_premise_retrieval/`). Headline: trained linear query head lifts R@100 from 0.16 → 0.54 over 388k Mathlib decls; RAG helps weak models (Qwen3-8B 12.5% → 25%) and unfamiliar libraries (Sonnet 0% → 50% on brownian-motion sandboxed), hurts strong models on familiar APIs (Sonnet 83% → 75% on Mathlib). Three-arm extension with our informal-dep graph-pack designed in `experiments/lean_premise_retrieval/INTEGRATION.md`. |

## Contributor prompt

Copy/paste this when bringing a new model into the work:

> You are contributing to `formalized_graph/docs/paper_writing/` — a
> "second brain" for the EMNLP paper. The goal is to offload every
> paper-relevant fact (schemas, sample rows, API surfaces, scale numbers,
> experiment summaries) into terse markdown so future sessions can ground
> themselves without re-deriving anything from the live system.
>
> Before answering or writing:
>
> 1. Read every file in this directory. Cross-reference with the canonical
>    sources they point to (e.g. `api_reference.md` points to
>    `api/README.md`).
> 2. Ground new claims in the live RDS (db `v2` on
>    `theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com`)
>    or the repo code — never invent numbers or schema details.
> 3. Prefer adding a new short file or extending an existing one over
>    long prose. Link between files with relative paths.
>
> Style: terse, factual, table-heavy. No narrative. No restating things
> already documented in repo CLAUDE.md or `api/README.md` — link to them.
>
> Ask before assuming. If a fact looks stale, verify against the DB or
> code and update in place rather than appending duplicates.
