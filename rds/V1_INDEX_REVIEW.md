# v1 (`postgres` database) indexes and tables to review

Indexes on v1 tables that no production code uses (API, theoremsearch.com, the
legacy Streamlit apps, the query dashboard) — only experiments and `archive/`.
They are **on hold**, not scheduled for deletion. Collected 2026-09-19.

Scan counts are lifetime totals (stats have never been reset), so they say
little about current use. To see what is used now, diff against the
2026-09-19 baseline after a few days:

```bash
python rds/scripts/index_usage.py rds/usage/usage_2026-09-19T134149.json
```

Already done: `theorem_embedding_qwen8b_trunc` (table + its 70 GB HNSW and
primary key, 118 GB total) was dropped on 2026-09-19; no code referenced it.

Still used in production, **not** part of this review: `theorem_search_qwen8b`
and its indexes (public `/search` API and MCP, both legacy Streamlit apps),
the `mv_*` views, and the logging tables (`queries`, `feedback`,
`theorem_reports`, `api_search_query`).

## Indexes on hold

| Index | Table | Size | Definition | Lifetime scans |
|---|---|---:|---|---:|
| `theorem_embedding_qwen8b_binary_quantize_idx` | `theorem_embedding_qwen8b` | 7.3 GB | `hnsw ((binary_quantize(embedding))::bit(4096)) bit_hamming_ops` | 1,637 |
| `theorem_search_qwen_type_idx` | `theorem_search_qwen` | 62 MB | `btree (theorem_type)` | 32 |
| `ts_pc_not_null` | `theorem_search_qwen` | 52 MB | `btree (source, primary_category) WHERE primary_category IS NOT NULL` | 1 |
| `theorem_search_authors_not_null` | `theorem_search_qwen` | 51 MB | `btree (source) WHERE authors IS NOT NULL` | 0 |

The primary keys of these tables (below) are only worth removing together
with their tables.

## What the tables hold

All slogans below are v1 `theorem_slogan` rows (DeepSeek-V3.1, prompt
`body-only-v1` unless noted); v2 re-generated its own slogans and embeddings,
so none of this data feeds v2.

### `theorem_embedding_qwen8b` — 244 GB, ~9.0M rows
- Columns: `slogan_id bigint` (PK), `embedding vector` (4096-d,
  Qwen3-Embedding-8B).
- Size is almost all TOAST: 1060 MB heap + 7.7 GB indexes + ~235 GB of
  TOASTed 4096-d vectors.
- **Checked for dropping 2026-10-01 — cleared, not yet dropped.**
  - Unread: last access of any kind (seq or index) `2026-09-19 21:19:12 UTC`.
    Its 7.3 GB HNSW logged 0 scans in the 2026-09-24 → 09-30 diff.
  - No live reader: v1 `/search` and `/mcp` use `theorem_search_qwen8b` only
    (`api/routes/search.py:79,143`); nothing in `api/`; nothing in the website.
  - No dependent objects: no views/matviews, no inbound FKs. Its only
    constraint is its own outbound FK to `theorem_slogan`.
  - Duplicated by value, not just by id: 9,268,550 of 9,269,072 `slogan_id`
    are in `theorem_search_qwen8b`, and on a 1-in-4000 sample 2,316 of 2,316
    embeddings compared **equal** (0 differing, 0 missing).
  - A full anti-join found **522 `slogan_id` present only here** (491
    `body-only-v1`, 31 `body-and-abstract-v1`, all with live theorem rows).
    Those are preserved in `theorem_embedding_qwen8b_orphans` (522 rows,
    9808 kB, verified identical to source) — see
    `rds/helpers/preserve_qwen8b_orphans.sql`. With that table in place the
    drop is lossless.
  - Recovery if wrong: 7-day automated retention, PITR from 2026-09-24,
    daily snapshots, cluster deletion protection on.
- Code: `experiments/final_test_revised.py` (default `PG_TABLE`, in three
  places; its stage 1 orders by `binary_quantize(...) <~> ...`, i.e. **uses
  the HNSW index**), `experiments/evaluation/bm25_slogan_search.py`
  (`--embedding-table` default, joins by `slogan_id`),
  `archive/prod/rds.py`, `archive/prod/pca.ipynb`. All four now carry an
  in-file note about the pending removal.
- **Repointing is not a drop-in rename.** `theorem_search_qwen8b` has the same
  `slogan_id` and `embedding` columns, but its HNSW indexes are *partial*, one
  per source, while this table's is the only *global* HNSW in v1. An ANN query
  against it must pin a source — `WHERE source = 'arXiv'` covers 9,230,149 of
  9,269,072 rows — or no index applies and it sequentially scans 179 GB.
  `theorem_search_qwen8b` also carries only `body-only-v1` slogans, so
  `body-and-abstract-v1` embeddings exist solely in the `_orphans` table.

### `theorem_search_qwen` — 49 GB, ~7.7M rows
- Earlier denormalized search table with 1024-d Qwen embeddings (1024 dims
  suggests Qwen3-Embedding-0.6B; not recorded in the table): `slogan_id`, `theorem_id`, `paper_id`,
  `embedding vector(1024)`, `slogan_model`, `prompt_id`, `theorem_name`,
  `theorem_body`, `theorem_slogan`, … Sources: arXiv 7,708,421; Stacks Project
  13,093. All slogans DeepSeek-V3.1 / `body-only-v1`.
- Code: `llm_rag/rag_functions.py`, `archive/prod/rds.py`,
  `archive/prod/plots.ipynb`.

### `theorem_embedding_qwen` — 40 GB, ~7.7M rows
- `slogan_id` (PK), `embedding vector(1024)`: the 1024-d Qwen embeddings
  behind `theorem_search_qwen`.
- Code: `experiments/pca_plotting.py`.

### `raw_theorem_embedding_gemma` — 40 GB, ~9.3M rows
- `theorem_id` (PK), `embedding vector(768)`: Gemma embeddings of the raw
  theorem text (no slogan).
- Code: `experiments/evaluation/rrf_csv_evaluator.py`,
  `experiments/evaluation/evaluation_queries.ipynb`, `archive/prod/pca.py`.

### `theorem_embedding_gemma` — 35 GB, ~8.9M rows
- `slogan_id` (PK), `embedding vector(768)`: Gemma embeddings of slogans.
- Code: `archive/prod/pca.py`, `archive/prod/main.ipynb`.

### `theorem_search_gemma` — 31 GB, ~7.8M rows
- `slogan_id` (PK), `embedding vector(768)`, `theorem_id`, `paper_id`.
- Code: **none** (only its `CREATE TABLE` in `archive/rds_schema.sql`).
