# LeanSearch v2 vs. ours — comparison for paper writing

Status: working notes. All "ours" claims grounded in `schema.md` / `samples.md`
/ `api/README.md`. All "LSv2" claims grounded in `leansearch_v2_external/`
(README, `src/leansearchv2/`, `benchmark/`) and arXiv:2605.13137v2.

---

## 1. Scope of corpus

| | LeanSearch v2 | Ours (v2 schema) |
|---|---|---|
| Sources | Mathlib only, single revision (v4.28.0-rc1) | arXiv (1,841,292 papers), Lean Community blueprints (21 repos), Lean repos (30) |
| Side | Formal only | Both: 12,137,642 statements total; 388,105 with `formality=formal`; rest informal |
| Filter | User-facing kinds: `theorem`, `definition`, `instance`, `abbrev`, `opaque`, `axiom`; drops `_proof_1` / `match_*` (`is_internal`); inductive/structure/class kept *for informalization context* but not exported | All statements retained regardless of kind; `kind` is a free-text column |
| Cross-formality bridge | None — formal world only | `informal_metadata.lean` is the blueprint `\lean{...}` annotation; populated rows give ground-truth informal-↔-formal pairs (e.g. `Real.marcinkiewicz_zygmund', Real.marcinkiewicz_zygmund`) |
| Corpus size shipped | Pre-built cuVS index on HuggingFace; exact decl count not disclosed in paper | 12.1M statements, 16.5M slogans, 12.1M embeddings |

**Headline:** LSv2 is a *narrow, deep* Mathlib-only corpus; ours is a *broad,
shallow-on-Lean-side* multi-source corpus where the blueprint subset is the
analogue of theirs and the arXiv subset is unique to us.

---

## 2. Corpus construction pipeline

| Stage | LSv2 (`src/leansearchv2/corpus/`) | Ours |
|---|---|---|
| Static extraction | `jixia` (Lean static analyzer, submoduled at v4.28.0-rc1) → raw per-file JSON | Lean elaborator extract for Lean repos; regex parser for arXiv (`arxiv_parse_status.parsing_method='regex'`) |
| Merge | `merge_to_jsonl.py` — flatten + resolve refs | Loaded into Postgres `statement` + `formal_metadata` / `informal_metadata` |
| Dependency graph | Built internally during informalization: `typeReferences` (+ `valueReferences` for non-Prop), topo-sort via Kahn's algorithm, bottom-up | Persisted as first-class tables: `informal_dependency` (18.3M rows) and `formal_dependency` (11.3M rows) with edge-type annotations |
| Informalization | Kind-specific Jinja templates (`theorem.md.j2`, `definition.md.j2`, `instance.md.j2`, `technical_entry.md.j2`); Qwen3-32B (Gemini 2.5 Pro fallback); each prompt receives dep summaries | Per-statement *slogans* via `slogan_prompt` × `slogan_model` registry (8 prompts × 2 models = 16 supported configs; current: `minimal`, `formal` prompts on `qwen3-235b` and `pilot-claude-sonnet-4-6`); `comprehensive` prompt uses `informal_dependency.methods` as trust score |
| Embedding | Qwen3-Embedding-8B (dim 4096, normalized); single embedding per declaration | Same model. Multiple embeddings per statement (one per slogan), excluding `insufficient_context=true` |
| Index | cuVS CAGRA, built with `intermediate_graph_degree=128`, `graph_degree=64`, `build_algo=ivf_pq`, metric=cosine; search `itopk_size=1024`, `search_width=4` | pgvector: binary-quantized HNSW on `bit(4096)` for shortlist; full-precision `vector(4096)` cosine for rerank |
| Reranker | Qwen3-Reranker-8B (paper) / 4B (public deployment) cross-encoder; binary `yes`/`no` token logit softmax | None LM-based. Score = cosine + `citation_weight × ln(citations)` for `/graph/embedding` |

**Headline:** LSv2's pipeline is a *clean linear ETL* terminating in a flat
index. Ours persists the dep graph and supports *multiple slogans per
statement* — a many-to-one between embeddings and source statements that
LSv2 doesn't have.

---

## 3. Retrieval API surface

### LSv2 `POST /search` (`src/leansearchv2/server.py`)

```jsonc
// Request
{ "query": ["..."], "num_results": 10, "rerank": true, "retrieve_k": null }

// Response — list[list[SearchResult]]
[[ { "result": { "module_name": [...], "kind": "theorem", "name": [...],
                 "signature": "...", "type": "...", "value": null,
                 "docstring": "...", "informal_name": "...",
                 "informal_description": "..." },
     "distance": 0.123 } ]]
```

Three endpoints total: `POST /search`, `POST /search_with_profile`, `GET /health`.
No graph traversal. No cross-paper notion (corpus is single-corpus). No filters
by author/citations/date/source. The instruction string is hard-coded into the
pipeline (see `RetrievalPipeline.INSTRUCTION`).

### Ours `/graph/*` (`api/README.md`)

Three endpoints: `/graph/embedding`, `/graph/statement/{id}`, `/graph/paper`.

- `GET /graph/embedding` — NL retrieval analogous to LSv2's `/search`. Adds
  filters: `sources`, `types`, `authors`, `min_citations`, `in_journal`,
  `citation_weight`. Two-phase binary→full cosine. UUID `statement_id`.
- `GET /graph/statement/{id}` — what LSv2 has no analogue of: one-hop graph
  walk in `direction ∈ {src, dep, both}`, choice of `formality ∈ {informal,
  formal}`. Edge payload includes provenance (`methods`, `location`, or
  `edge_type`). Opt-in `return=representations` adds cross-paper semantic
  neighbours at cosine ≥ 0.8 from a *different* `paper_id`.
- `GET /graph/paper` — whole-paper subgraph; auto-switches informal vs.
  formal edges based on `paper.kind == 'lean_repo'`.

**Headline:** LSv2 is a *single-shot retriever*; ours is a *retrieval + graph
navigator*. The closest LSv2 has to our `representations` is none — they
return a flat hit list and stop.

---

## 4. Reranking / reasoning beyond retrieval

| | LSv2 | Ours |
|---|---|---|
| Cross-encoder rerank | Qwen3-Reranker-8B, P(yes) over yes/no tokens; default `retrieve_k = max(top_k×2, 50)` | None |
| Score boost | None | `citation_weight × ln(citation_count)` on `/graph/embedding` |
| Iterative loop | Reasoning mode: decompose → search → filter → judge, ≤3 revision rounds. Sonnet 4.5 for sketch / judge / revision, Kimi K2 for filter | None in core API. Possible to build externally by chaining `/graph/embedding` + `/graph/statement` |
| Output of reasoning | Premise *groups* — sets of interchangeable lemmas that jointly support a proof | N/A. We expose dependency edges directly; "what would prove this theorem" is not a first-class call |

---

## 5. Benchmarks shipped

### LSv2 (`leansearch_v2_external/benchmark/`)

| File | Rows | What it is |
|---|---|---|
| `MathlibQR.json` | 200 decls × up to 6 query styles = **946 populated query rows** (1200 cells, 254 empty) | Single-query retrieval eval. Styles: `q1a_lean` (Lean-flavored), `q1b_latex`, `q1c_natural` (plain English), `q2_slogan`, `q3_nickname`, `q4_special_case`. Difficulty 101 Easy / 99 Hard. Kinds: theorem 74, structure 39, class 29, def 26, instance 25, inductive 6, lemma 1. |
| `MathlibQR_shared171.json` | 171 decls = 810 fair-subset queries | Subset present across all systems' corpora (handles Mathlib version skew across competitors). |
| `MathlibMPR.json` | **69 theorems**, 204 premise groups total (171 `original` + 33 `alternative`), mean **2.96 groups/query**, 1–8 groups, mean **1.75 lemmas/group**, 1–6 | Global premise retrieval eval. Sourced from merged Mathlib PRs (`pr` field). Schema: `id`, `pr`, `formal_main_result`, `NL_main_result`, `formal_statement` (with `sorry`), `premise_group: [{kind, docs}]`. |
| `MathlibMPR_Prop_ids.txt` | 50 ids | Prop-only subset for downstream prove eval. |
| `FATE-H.jsonl` | 100 problems | External: redistributed under CC-BY-4.0 from FATE paper (Jiang et al. 2025). Schema: `informal_statement`, `formal_statement` (with `by`), `informal_proof`, `tag`, `name`. |

### Ours

- `experiments/blueprint_matching/` — q1–q4 numbers per `api_reference.md`,
  driven by the `informal_metadata.lean` ground-truth bridge between
  blueprint informal statements and Mathlib `decl_name`s. *I have not yet
  read the q*.txt outputs in this comparison pass; flag this gap.*
- No published equivalent of MathlibMPR (premise groups). Our
  `formal_dependency` rows are the raw material a premise-group benchmark
  could be built from, but we ship no curated eval set today.

**Headline:** LSv2 ships **two** purpose-built benchmarks (MathlibQR for
single-query retrieval; MathlibMPR for global premise) plus a borrowed
prover benchmark (FATE-H). Ours ships the bridge data (`informal_metadata.lean`)
but no benchmark file under version control with the same first-class status.

---

## 6. Evaluation metrics

| Metric | LSv2 | Ours equivalent |
|---|---|---|
| nDCG@10 (Table 1) | LSv2 rerank **0.623**; LeanFinder 0.533 | Not reported in same form. Blueprint q1–q4 in `experiments/blueprint_matching` use recall@k against `informal_metadata.lean` ground truth — not directly comparable. |
| Recall@10(group) (Table 2) | LSv2 reasoning **46.1%**; DIVER 38.0%; LeanStateSearch 9.3% | No premise-group concept persisted; would need to derive groups from `formal_dependency` first. |
| Covered@k (Table 2) | LSv2 reasoning 30.4% | None. |
| Proof success (Table 3, FATE-H × fixed prover loop) | LSv2 reasoning **20%**; INF-X-Retriever 16%; no-retrieval 4%. MathlibMPR-Prop: LSv2 reasoning 14% | None — we have no prover pipeline. |

---

## 7. What we should claim in the paper (and what we shouldn't)

**Where we win or are differentiated:**
- *Cross-formality bridge.* `informal_metadata.lean` is a ground-truth
  informal↔formal link that LSv2 has no analogue of (their corpus is
  formal-only).
- *Multi-source scope.* 1.84M arXiv papers + Lean blueprints + Lean repos
  vs. Mathlib-only. The arXiv side is unique.
- *Persisted dependency graph.* Edges are queryable (`edge_type`, `methods`,
  `location`, ranker-grade `position`/`binder`/`role` on signatures);
  LSv2 builds a dep DAG internally but throws it away after corpus build.
- *Many-slogans-per-statement.* Lets us study prompt/model sensitivity
  (`slogan_prompt` × `slogan_model`) on retrieval; LSv2 fixes one
  informalization per decl.
- *Cross-paper restatement surface* via `/graph/statement/{id}?return=representations` (cosine ≥ 0.8, different `paper_id`). LSv2 has no cross-paper notion because there is only one paper (Mathlib).

**Where LSv2 is ahead and the paper needs to acknowledge / address:**
- *Reranker.* No LM cross-encoder rerank in our pipeline. On the same
  retrieval shortlist they would beat us in nDCG.
- *Reasoning loop.* Decompose-search-filter-judge for global premise retrieval
  with 46.1% Recall@10(group). We have no iterative loop in the API today.
- *Curated benchmarks.* MathlibQR (200 decls × 6 styles) and MathlibMPR (69
  theorems with premise groups) are reusable artifacts. Our `blueprint_matching`
  experiment is an in-house eval, not a benchmark file the community can drop
  into a leaderboard.
- *Downstream prove eval.* They tie retrieval quality to a fixed prover loop;
  we don't.

**Specifically do NOT claim:**
- That we exceed their nDCG@10 — we have not measured against MathlibQR.
- That `/graph/embedding` is "the same" pipeline. Differences: pgvector
  binary-HNSW vs. cuVS CAGRA; no LM reranker; multiple slogans per
  statement; cross-source filters.
- That our slogans match their informalization template format. Ours are
  natural-language summaries (1–4 sentences, ASCII). Theirs is a
  multi-field template (`informal_name`, `informal_description`) bundled
  with the Lean signature at embedding time — `construct_lean_representation`
  in `corpus/build_cuvs.py` emits a header-prefixed template, *not* a bare
  natural-language summary.

---

## 8. Open questions / data we still need

- [ ] Pull `experiments/blueprint_matching/q*.txt` and translate to the same
      metric language (nDCG@10, Recall@10) for an apples-to-apples row in a
      results table.
- [ ] Run MathlibQR (810 fair queries) against `/graph/embedding` with
      `types=` restricted to Lean kinds — gives us the one number we are
      currently missing to make a fair head-to-head row.
- [ ] Decide whether to build a premise-group benchmark from `formal_dependency`,
      or to evaluate against MathlibMPR directly (their ground truth is
      Mathlib `decl_name`s, which our `formal_metadata.decl_name` matches by
      construction — feasible).
- [ ] Confirm which Mathlib revision our `formal_metadata` rows correspond
      to. LSv2 pins v4.28.0-rc1; comparable-corpus claims need the same pin.
- [ ] Exact size of LSv2's deployed corpus (not disclosed in paper; would
      need to load their HF dataset).

---

## 9. References

- LSv2 paper: arXiv:2605.13137 (v2, 2026-05-14). PDF at
  `https://arxiv.org/pdf/2605.13137`.
- LSv2 repo: `leansearch_v2_external/` (this directory). README is the
  best single source; numbers in §6 verified from
  `benchmark/MathlibQR.json` and `benchmark/MathlibMPR.json`.
- LSv2 public deployment: `https://leansearch.net/search` (Qwen3-Reranker-**4B**
  per README — paper Table 1 uses the 8B).
- Our schema: `schema.md`. Sample rows: `samples.md`. Our API: `api/README.md`.
