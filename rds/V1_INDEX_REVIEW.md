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
- Every `slogan_id` sampled (0.5%) is also in `theorem_search_qwen8b`, which
  carries its own copy of the embedding: this looks like the table
  `theorem_search_qwen8b` was built from.
- Code: `experiments/final_test_revised.py` (default `PG_TABLE`; its stage 1
  orders by `binary_quantize(...) <~> ...`, i.e. **uses the HNSW index**),
  `experiments/evaluation/bm25_slogan_search.py` (default table name, joins by
  `slogan_id`), `archive/prod/rds.py`, `archive/prod/pca.ipynb`.
- Pointing those experiments at `theorem_search_qwen8b` (same slogan_ids,
  embedding column, and an equivalent per-source HNSW) would likely free the
  whole 244 GB table.

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
