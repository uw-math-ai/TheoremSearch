# nl_fl_matching/

NL↔FL retrieval pilot. Produces the ranked-candidate dataset that feeds the
EMNLP paper's bidirectional-matching experiments.

## Layout

| file | what it does |
|---|---|
| `pools.py` | Query-side fetchers (`project_formals`, `blueprint_informals`, `informal_sample`) and the candidate-pool name registry (`CANDIDATE_FILTERS`). |
| `topk.py` | Per-query ANN search. Two-phase: binary-quantized HNSW shortlist → cosine rerank. Mirrors `api/routes/graph.py::_REPRESENTATIONS_SQL`. |
| `store.py` | Idempotent writer for `nl_fl_match_pilot` (upsert on `(query, direction, exclusion, rank, embedding_model)`). |
| `schema.sql` | DDL for `nl_fl_match_pilot`. Read by `store.ensure_table`. |
| `smoke_test.py` | 100-query sanity run. Validates SQL + table + timing before any full sweep. |
| `runners/` | _(planned)_ one orchestration script per task — f2i, i2f, self-match. |
| `analysis/` | _(planned)_ `eval.py` (Hit@k + MRR), `agreement.py`, `nl_corr.py`. |

## Tasks this dataset supports

| task | description | runner | direction / exclusion / pool |
|---|---|---|---|
| 1 | project formal → closest informal (any paper) | `runners/run_f2i.py` | `f2i` / `statement` / `all_informals` |
| 2 | sampled informal → closest project formal | `runners/run_i2f.py` | `i2f` / `statement` / `project_formals` |
| 3 | bidirectional agreement of (1)+(2) | `analysis/agreement.py` | derived |
| 4 | NL-method correlation with (1)'s pairs | `analysis/nl_corr.py` | derived |
| 5a | project formal → closest other formal | `runners/run_self.py --formality formal --exclusion {statement,paper}` | `f2f` / either / `project_formals` |
| 5b | blueprint informal → closest other informal | `runners/run_self.py --formality informal --exclusion {statement,paper}` | `i2i` / either / `blueprint_informals` |

## Run the smoke test

```bash
python -m experiments.nl_fl_matching.smoke_test
```

Expected: ~100 project formals × top-10 candidates from the 11.7M informal
pool ≈ 30-60s end-to-end, similarity distribution non-degenerate (p50 in
roughly `[0.4, 0.7]`).
