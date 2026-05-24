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
