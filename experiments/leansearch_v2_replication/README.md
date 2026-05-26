# MathlibQR replication

Replicates LeanSearch v2's Table 1 single-query retrieval eval (MathlibQR,
200 decls × ≤6 query styles = 946 populated cells) against our retriever.

## Pipeline

`run_eval_rds.py` talks to the v2 RDS directly via the bastion tunnel.
For each populated `(decl, style)` cell:

1. Embed the query with Qwen3-Embedding-8B via Nebius, prefixed with the
   deployed retrieval instruction (`Given a math search query, retrieve
   theorems mathematically equivalent to the query.\n`) and L2-normalized.
2. Binary-HNSW shortlist on `embedding`, restricted to Lean Repo slogans
   via a session-temp table `lean_slogan_ids` (~388K rows, built once).
3. Full-precision cosine rerank, top-10.
4. Score: a hit is `paper_id ∈ {Mathlib_v427, Mathlib_v428}` AND
   `formal_metadata.decl_name == MathlibQR.full_name` (byte-exact).
   Recall@10 = 1/0; nDCG@10 = 1/log2(rank+1) at first hit.

The deployed `/graph/embedding` endpoint times out at 10s on this query
because its source filter is post-applied to a 200-candidate ANN
shortlist, of which <4% are Lean Repo (and the binary index does not
iterate to recover). The session-temp-table inner join makes the
filter index-visible so pgvector's `hnsw.iterative_scan = relaxed_order`
can reach the required 200 Lean Repo candidates.

Methodology decisions are documented in
`formalized_graph/docs/paper_writing/leansearch_v2_comparison.md` §6.

## Prereqs

- RDS tunnel open on localhost:5432 (bastion `premise-rl` →
  Aurora `theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com`)
- `.env` at repo root with `AWS_*`, `RDS_SECRET_ARN`, `NEBIUS_API_KEY`
- Benchmark JSONs at
  `formalized_graph/docs/paper_writing/leansearch_v2_external/benchmark/`
  (re-clone with `git clone --depth 1 https://github.com/frenzymath/LeanSearch-v2.git`
  into that path)
- Python: `psycopg2-binary boto3 openai` under `coenv/python/3.13.11`

## Run

```sh
module load coenv/python/3.13.11
python3 run_eval_rds.py --query "..."     # ad-hoc single query, print top-10
python3 run_eval_rds.py --pilot 30        # first 30 cells → data/{per_query_pilot30.jsonl, summary_pilot30.json}
python3 run_eval_rds.py                    # full 946 cells → data/{per_query.jsonl, summary.json}
```

Wall: ~30–90 min for the full run, bottlenecked on Nebius latency
(~1.0–1.5s/embed) and the 200-candidate cosine rerank (~1–4s).

## Outputs

`data/per_query.jsonl` — one row per cell with `top10` array and
`hit_rank` / `recall@10` / `ndcg@10`.

`data/summary.json` — `overall`, `by_style`, `by_difficulty`, `by_kind`
aggregations, each computed on full-946 and on the fair-810 shared
subset (`MathlibQR_shared171.json`'s `shared_declarations`).
Includes `corpus_coverage` listing how many of the 200 MathlibQR
`full_name`s our v427/v428 `formal_metadata` actually contains —
the ceiling on Recall@10.
