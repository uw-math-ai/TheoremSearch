# API Reference (paper-writing lens)

**Canonical doc:** [`api/README.md`](../../../api/README.md). Read that first — it covers every endpoint, params, response shape, `mode=full|minimal`, and the `return=representations` opt-in.

> **Agents:** fetch `api/README.md` from the repo root (relative path `../../../api/README.md`) for the full API definitions — they are not duplicated here.

This file just records the bits that are paper-relevant but not in the API README.

---

## Endpoint ↔ paper section mapping

| Endpoint | Paper claim it supports |
|---|---|
| `GET /graph/embedding` | NL → corpus retrieval. Same two-phase pattern as the blueprint experiment (binary-quantized HNSW shortlist → full-precision cosine rerank). The numbers in `experiments/blueprint_matching/q1.txt`–`q2.txt` come from this exact code path. |
| `GET /graph/statement/{id}?direction=both` | Local graph structure. Edge annotations (`location`, `methods`, `edge_type`) are the per-edge provenance you can cite when explaining how `informal_dependency` and `formal_dependency` were built. |
| `GET /graph/statement/{id}?return=representations` | **Q4 of the blueprint experiment, productionised.** Returns cross-paper semantic neighbours above cosine ≥ 0.8 (constant `_REPRESENTATION_SIMILARITY_THRESHOLD` in `api/routes/graph.py`), always from a *different* `paper_id`. If the paper claims "we surface restatements / equivalent results across the corpus," this is the endpoint that does it. |
| `GET /graph/paper` | Whole-paper subgraph — useful for figures/case-studies in the paper. Auto-switches between informal (`informal_dependency`) and formal (`formal_dependency`) based on `paper.kind == 'lean_repo'`. |

---

## The legacy `POST /search` surface (not in api/README)

Still deployed at `api.theoremsearch.com/search` and behind `/mcp`. Queries the **flat `theorem_search_qwen8b` table** with integer `theorem_id` / `slogan_id` and string `paper_id` like `"1909.00474v2"`.

**Do not cite `/search` in the paper unless you're explicitly contrasting the prod search surface with the graph surface** — the ID space is incompatible with everything under `/graph/*` and with the `v2` schema documented in [`schema.md`](./schema.md). The graph experiments and the new API both use UUID `statement_id` from the `statement` table.

---

## Cross-references

- Tables and column types behind these endpoints: [`schema.md`](./schema.md).
- Real sample rows (incl. an `embedding` row showing dim/norm/head/tail): [`samples.md`](./samples.md).
- Embedding pipeline + dimension/norm details: `embedding_model` row in `samples.md` (qwen3-8b, dim=4096, instruction-prefixed at embed time).
- Blueprint-matching experiment that mirrors the production retrieval: `experiments/blueprint_matching/` (q1–q4).
