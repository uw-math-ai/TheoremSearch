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
| Informalization | Kind-specific Jinja templates (`theorem.md.j2`, `definition.md.j2`, `instance.md.j2`, `technical_entry.md.j2`); Qwen3-32B (Gemini 2.5 Pro fallback); each prompt receives dep summaries | Per-statement *slogans* via `slogan_prompt` × `slogan_model` registry (9 prompts × 2 models = 18 supported configs; current: `minimal`, `formal` prompts on `qwen3-235b` and `pilot-claude-sonnet-4-6`); `comprehensive` prompt uses `informal_dependency.methods` as trust score |
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
| nDCG@10 (Table 1) | LSv2 rerank **0.623**; LSv2 retriever-only **0.494**; LeanFinder 0.533; LeanExplore 0.393 | **Ours (Mathlib-only retriever): 0.370** on fair-810. See §6a below. |
| Recall@10(group) (Table 2) | LSv2 reasoning **46.1%**; DIVER 38.0%; LeanStateSearch 9.3% | No premise-group concept persisted; would need to derive groups from `formal_dependency` first. |
| Covered@k (Table 2) | LSv2 reasoning 30.4% | None. |
| Proof success (Table 3, FATE-H × fixed prover loop) | LSv2 reasoning **20%**; INF-X-Retriever 16%; no-retrieval 4%. MathlibMPR-Prop: LSv2 reasoning 14% | None — we have no prover pipeline. |

---

## 6a. Ours on MathlibQR (full run, 2026-05-24)

`experiments/leansearch_v2_replication/` — 946 populated query cells × top-10
retrieval against Mathlib v427 ∪ v428 corpus (337,356 slogans). Wall: ~2.3 h.
Source filter pushed into inner CTE via session-temp table; pgvector HNSW
binary shortlist + full-precision cosine rerank. No LM reranker, no
citation weight, slogan_model=`qwen3-235b` only. Per-cell config and code
in `experiments/leansearch_v2_replication/run_eval_rds.py`. Headline:

| system | corpus | nDCG@10 | Recall@10 | top-1 rate |
|---|---|---:|---:|---:|
| LSv2 rerank (Qwen3-Reranker-8B) | Mathlib v4.28.0-rc1 | **0.623** | **0.780** | — |
| LSv2 retriever-only | Mathlib v4.28.0-rc1 | 0.494 | 0.657 | — |
| LeanFinder (reported) | n/a | 0.533 | 0.698 | — |
| LeanExplore (reported) | n/a | 0.393 | 0.569 | — |
| **Ours (Mathlib v427+v428, no rerank)** | Mathlib v427+v428 | **0.370** | **0.568** | **0.194** |

Numbers on fair-810 subset (LSv2's reporting unit). Gap vs LSv2
retriever-only: ΔnDCG@10 = -0.124, ΔRecall@10 = -0.089.

Also evaluated unrestricted: same retriever with sources=['Lean Repo']
(community projects + v429 in candidate pool) gives nDCG@10 = 0.365 /
Recall@10 = 0.558 on the same 278-cell subset we measured before
restricting — confirms non-Mathlib distractors don't crowd the top-10
meaningfully (only 13/278 cells changed rank, all by exactly 1).

### Breakdown by decl kind (fair-810)

| kind | n | recall@10 | nDCG@10 | top-1 |
|---|---:|---:|---:|---:|
| theorem | 291 | 0.711 | 0.478 | 0.261 |
| instance | 97 | 0.732 | 0.549 | 0.371 |
| inductive | 25 | 0.520 | 0.353 | 0.240 |
| def | 105 | 0.495 | 0.288 | 0.124 |
| class | 134 | 0.410 | 0.239 | 0.075 |
| structure | 153 | 0.379 | 0.213 | 0.092 |
| lemma | 5 | 0.800 | 0.612 | 0.400 |

The kind split is the strongest single signal in the data: **we
match LSv2-retriever-class numbers on theorems and instances and trail
badly on structures/classes** — the kinds whose `decl_name` is itself
the conceptual handle ("Lattice", "Group", "Functor", "CommRing"). LSv2
embeds `decl_name + Lean signature` alongside the informal text
(`construct_lean_representation` in `corpus/build_cuvs.py`), so the
embedder sees that lexical anchor; ours embeds the slogan only.

### Breakdown by query style (fair-810)

| style | n | recall@10 | nDCG@10 | top-1 |
|---|---:|---:|---:|---:|
| q1c_natural | 170 | 0.624 | 0.415 | 0.229 |
| q3_nickname | 108 | 0.602 | 0.382 | 0.167 |
| q2_slogan   | 168 | 0.571 | 0.351 | 0.161 |
| q1b_latex   | 171 | 0.567 | 0.372 | 0.216 |
| q4_special_case | 23 | 0.522 | 0.328 | 0.130 |
| q1a_lean    | 170 | 0.494 | 0.337 | 0.194 |

Plain English (q1c_natural) wins; Lean-flavored queries (q1a_lean) trail
by ~13 pp recall — same hypothesis: our slogans are natural prose, so
queries with Lean syntax mismatch the embedding space at the surface.

### Hit-rank distribution (fair-810)

| rank | count | cum. recall |
|---|---:|---:|
| 1 | 157 | 0.194 |
| 2 |  95 | 0.311 |
| 3 |  49 | 0.372 |
| 4 |  42 | 0.423 |
| 5 |  33 | 0.464 |
| 6 |  24 | 0.494 |
| 7 |  14 | 0.511 |
| 8 |  15 | 0.530 |
| 9 |  11 | 0.543 |
| 10 |  20 | 0.568 |
| miss | 350 | — |

28% of hits land at rank 1; 60% at ranks 1–3. Ranking is healthy when
retrieval succeeds.

### Coverage

192/200 MathlibQR `full_name`s are present in our v427+v428
`formal_metadata`. The 8 missing decls (3 are v429-only:
`InformationTheory.kraft_mcmillan_inequality`,
`InformationTheory.UniquelyDecodable`,
`Representation.IntertwiningMap.instLinearMapClass`; 5 are absent
from our corpus entirely) score hard zero across all populated query
styles. Upper bound on Recall@10 is therefore 96%, not 100%.

Per-cell JSONL: `experiments/leansearch_v2_replication/data/per_query.jsonl`.
Diagnostic markdown: `data/diagnostic_no_rds.md`.

---

## 6b. Improvement push (overnight 2026-05-24/25, in flight)

After landing the baseline at 0.370 nDCG, we ran four probes to identify
which interventions could plausibly close the 0.124 gap. Each probe is
**read-only** (no corpus changes) — measures cosines that *would* result
from a hypothetical change, without committing GPU/Nebius time. Results:

| probe (n=43 q3_nickname misses) | beats current rank-1 distractor | mean Δ vs baseline |
|---|---:|---:|
| Augmented-text (verbose LSv2 template) | 2/43 (4.7%) | **-0.082 cos** (dilutes!) |
| Augmented-text (minimal `decl_name+slogan`) | 10/43 (23.3%) | -0.07 cos |
| HyDE pseudo-doc expansion | 12/43 (27.9%) | -0.05 cos vs distractor |
| LSv2-style slogan regen (qwen3-235b) | 5/43 (11.6%) | **+0.042 cos** vs old slogan |

Three key findings from probing:

1. **Dense embedders dilute.** Verbose augmentation (adding kind/module/
   header boilerplate to slogan text) makes cosine WORSE, not better.
   Confirmed in full eval: row 4 (aug-embed alone) measured 0.328 nDCG
   at 100/946 cells — below baseline. **Cancelled to save compute**;
   partial data archived as the "aug-embed doesn't help" finding.

2. **Slogan-regen helps modestly per gold but distractors also get the
   richer slogan, capping flip rate.** Worth running as one row in the
   ablation, not as the deciding intervention.

3. **The graph signal we have but LSv2 throws away is the most novel
   lever.** Smoke test on 5 Lattice cells: all retrieval levers + graph
   expansion ⇒ 5/5 hits, **nDCG 0.926**. Without graph: 0.804. Graph
   surfaces formal_dependency parents of top-K cosine candidates, which
   catches the "namesake child outranks gold" failure mode (e.g.
   `Functor.IsEquivalence` retrieved for query "functor" → surface its
   parent `Functor`).

### Overnight ablation roster (10 rows)

Each row submitted as an independent SLURM job under
`experiments/leansearch_v2_replication/run_row_template.slurm`,
parameterized via `EVAL_FLAGS`:

| # | tag | EVAL_FLAGS | status |
|---|---|---|---|
| 1 | baseline | (none) | done — 0.370 / 0.568 |
| 2 | dedupe_annk1000 | `--dedupe --ann-k 1000` | running, partial 0.374 / 0.575 |
| 3 | + trigram + hyde | + `--hybrid-trigram --hyde ensemble` | queued |
| 4 | augembed only | `--embed-model qwen3-8b-augminimal --dedupe --ann-k 1000` | **cancelled** (0.328 nDCG at 100 cells, confirmed dud) |
| 5 | augembed + all | row4 + trigram + hyde | **cancelled** (dependency on row 4) |
| 6 | lsv2-only + all | `--embed-model qwen3-8b-lsv2slogan --dedupe --ann-k 1000 --hybrid-trigram --hyde ensemble` | chained, ~7 h |
| 7 | formal + lsv2 ensemble + all | `--embed-model qwen3-8b ...` (after stage-2b embed lsv2 → qwen3-8b model_name) | chained, ~7 h |
| 8 | all + graph | `... --graph-expand` | queued |
| 9 | graph-only | `--dedupe --ann-k 1000 --graph-expand` | queued |
| 10 | ensemble + all + graph (kitchen sink) | row 7 + `--graph-expand` | chained, ~7 h |

### Pipeline backup (so this is reproducible)

All overnight infrastructure is in `experiments/leansearch_v2_replication/`:

- `run_eval_v2.py` — eval harness; toggles `--dedupe`, `--ann-k`,
  `--hybrid-trigram`, `--hyde {off,replace,ensemble}`, `--graph-expand`,
  `--embed-model`.
- `regen_lsv2_slogans.py` + `.slurm` — generates lsv2-style slogans for
  Mathlib v427+v428 via Nebius qwen3-235b. Writes to slogan table under
  `(prompt_name='lsv2-style', model_name='qwen3-235b')`. Resume-safe.
- `pipeline/generate_slogans/prompts/lsv2-style.j2` — the prompt template.
- `embed_slogans.py` + two `.slurm` wrappers
  (`embed_lsv2_slogans.slurm` writes to `qwen3-8b-lsv2slogan`,
  `embed_lsv2_to_qwen8b.slurm` writes to `qwen3-8b` for ensemble).
- `reembed_augminimal.py` + `.slurm` — the augembed re-embed (now confirmed
  dud but the script remains so others can reproduce the negative result).
- `probe_augtext.py`, `probe_query_and_slogan.py`, `diagnose.py` — the
  read-only probes documented in §6b above.

Persistent RDS state (after overnight pipeline completes):
- New row in `slogan_prompt`: `name='lsv2-style'`
- New rows in `slogan` table: ~337K under `(lsv2-style, qwen3-235b)`
- New row in `embedding_model`: `name='qwen3-8b-augminimal'`
- New row in `embedding_model`: `name='qwen3-8b-lsv2slogan'`
- New ~337K rows in `embedding` for the augminimal model
- New ~337K rows in `embedding` for the lsv2slogan model
- New ~337K rows in `embedding` for the existing qwen3-8b model (ensemble)

Cost (estimated): ~$40 Nebius for slogan regen + ~30 GPU-min for two embed
passes on 8× RTX 6000.

Per-cell results from each row: `data/per_query_v2_<tag>.jsonl` +
`data/summary_v2_<tag>.json`. Final 9-row ablation table will be written
back into this §6a/§6b on completion.

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
- That we exceed their nDCG@10 — measured 2026-05-24, we trail LSv2
  retriever-only by 0.124 nDCG / 0.089 Recall on fair-810. See §6a.
- That `/graph/embedding` is "the same" pipeline. Differences: pgvector
  binary-HNSW vs. cuVS CAGRA; no LM reranker; multiple slogans per
  statement; cross-source filters.
- That our slogans match their informalization template format. Ours are
  natural-language summaries (1–4 sentences, ASCII). Theirs is a
  multi-field template (`informal_name`, `informal_description`) bundled
  with the Lean signature at embedding time — `construct_lean_representation`
  in `corpus/build_cuvs.py` emits a header-prefixed template, *not* a bare
  natural-language summary. §6a's by-kind breakdown is consistent with this
  being the main driver of the retriever-side gap.

---

## 8. Open questions / data we still need

- [ ] Pull `experiments/blueprint_matching/q*.txt` and translate to the same
      metric language (nDCG@10, Recall@10) for an apples-to-apples row in a
      results table.
- [x] Run MathlibQR (810 fair queries) against `/graph/embedding` —
      done 2026-05-24, see §6a. Used a Mathlib-only session-temp-table
      variant of the deployed SQL (deployed `/graph/embedding` times out
      with its post-filter on the 4% Lean-Repo selectivity).
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
