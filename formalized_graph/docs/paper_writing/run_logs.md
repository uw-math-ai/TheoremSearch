# paper_writing/ run logs

Terse journal of multi-query / multi-hour evaluation runs done for the EMNLP
paper. One bullet per run, pre and post. Detailed per-query output lives in
`experiments/<run>/data/`.

---

## 2026-05-24 — MathlibQR replication, pilot 30

- Node n3433, RDS-direct via bastion tunnel (EC2 `184.33.198.139`).
- `experiments/leansearch_v2_replication/run_eval_rds.py --pilot 30`.
- 30/30 done in 191s (~6.4s/cell, occasional 16s outliers from iterative HNSW scan).
- Pilot result: recall@10 = 0.367 / ndcg@10 = 0.172 (full-946 metric on 30-cell pilot);
  recall@10 = 0.440 / ndcg@10 = 0.207 (fair-810 subset of pilot, n=25).
- Coverage: 192/200 MathlibQR decls present in v427/v428 formal_metadata; 8 missing
  (e.g. `Nat.RecursiveIn`, `GCDMonoid.gcd_mul_lcm` — likely v429-only or renamed).
- Style spread: q3_nickname best (recall 0.60), q1c_natural worst (0.17, n=6).

## 2026-05-24 — MathlibQR replication, full 946 (Lean Repo, aborted at 278/946)

- Same node/tunnel. `python3 run_eval_rds.py` with `sources=['Lean Repo']`,
  temp table 388,105 rows (all 27 Lean Repos: Mathlib v427/v428/v429 + community projects).
- Aborted because non-Mathlib slogans (Batteries, blueprints, v429) took top-10 slots
  without ever being counted as hits — deflates our score artificially.
- Partial JSONL preserved at `data/per_query_leanrepo_partial.jsonl` (278 cells).

## 2026-05-24 — MathlibQR replication, full 946 (Mathlib v427+v428 only, pre-run)

- Same node/tunnel. Restricted temp table to `external_id ∈ {Mathlib_v427, Mathlib_v428}`:
  337,356 slogans. Apples-to-apples with LSv2's Mathlib-only corpus.
- Smoke test: "lattice" now lands `Lattice` (the class) at rank 2; previously fell out of
  top-10 because v429 `Lattice.ofIsLUBofIsGLB` and community-project distractors crowded.
- Expected wall: similar to Lean Repo run (~100 min) — corpus size only 13% smaller.
- LSv2 retriever-only baseline to beat (arXiv:2605.13137 Table 1, fair-810):
  nDCG@10 = 0.494, Recall@10 = 0.657.

## 2026-05-24 — MathlibQR replication, full 946 (Mathlib v427+v428, post-run)

- Wall: 8124s ≈ 2.3 h. Aurora throughput swung between 1.2s/cell and 30s/cell.
- **Overall full-946:** recall@10 = 0.553, nDCG@10 = 0.365, top1 = 0.198.
- **Fair-810 (LSv2's reporting unit):** recall@10 = 0.568, nDCG@10 = 0.370, top1 = 0.194.
- Gap to LSv2 retriever-only: ΔnDCG = -0.124, ΔRecall = -0.089. Our retriever
  trails their retriever-only by ~12 pp nDCG.
- Strongest signal: **by-kind split.** Theorems (0.711 recall) and instances
  (0.732) match LSv2-retriever-class numbers; structures (0.379) and classes
  (0.410) trail badly. Consistent with the embed-text hypothesis (we embed
  slogan only; LSv2 embeds `decl_name + Lean signature + informal`).
- Mathlib-only restriction (vs the aborted Lean Repo run): +0.005 nDCG /
  +0.000 recall on the 278-cell overlap — negligible. Non-Mathlib distractors
  weren't the issue.
- 192/200 decls covered; 8 missing (3 v429-only, 5 absent). Hard ceiling
  Recall@10 = 0.96 not 1.00.
- Full per-cell results: `experiments/leansearch_v2_replication/data/per_query.jsonl`.
  Headline writeup: `formalized_graph/docs/paper_writing/leansearch_v2_comparison.md` §6a.

## 2026-05-24 — Augmented-text probe (50 q3_nickname misses)

- `experiments/leansearch_v2_replication/probe_augtext.py` — for each miss,
  embed gold's `<decl_name>+<slogan>` vs original rank-1 distractor's slogan.
- **Verbose LSv2-template** (`[kind]: slogan / docstring / decl_name / module / body`):
  only 2/43 (4.7%) flips above current rank-1 distractor; mean cosine 0.615
  vs distractor 0.697 — **augmentation DILUTES the embedding** on dense
  instruction-tuned encoders.
- **Minimal** (`<decl_name>\n<slogan>`): 10/43 (23.3%) flips above distractor;
  18/43 (41.9%) makes top-10. Best of the three.
- **decl_name alone** (no slogan): 2/43 (4.7%) — too sparse for dense.
- Verdict: verbose LSv2-template is bad; minimal is best, but with caveat
  that distractor symmetry in a full re-embed wipes out most of the gain.
- Saved: `data/probe_q3_nickname_n43.json`.

## 2026-05-24 — HyDE + slogan-regen probes (50 q3_nickname misses each)

- `experiments/leansearch_v2_replication/probe_query_and_slogan.py`.
- **HyDE** (LLM expands query → pseudo-doc → embed as doc): 12/43 (27.9%)
  flips above distractor. Pseudo-docs are high quality (e.g. Dieudonné's
  theorem expansion). Modest improvement, distractor symmetry caps it.
- **Slogan-regen** (LSv2-style prompt, qwen3-235b): only 5/43 (11.6%) beats
  distractor BUT 30/43 (69.8%) beats old slogan on the same gold —
  consistent +0.042 Δcosine. Improves gold-side embedding but not enough
  to flip distractors alone.
- Verdict: neither is solo enough to close 12-pp gap; combinations needed.
- Saved: `data/probe_hyde_n43.json`, `data/probe_regen_n43.json`.

## 2026-05-25 — Phase A1 + augminimal full re-embed (overnight chain start)

- **Re-embed (Phase C)** — `reembed_augminimal.py` SLURM 35531632 → 35531667 →
  succeeded after fixing per-shard tunnel ports + RDS_HOST override.
  Result: 337,356 augminimal embeddings written under
  `embedding.model_name='qwen3-8b-augminimal'`.
- **Eval A1 (35531989)** — `run_eval_v2.py --dedupe --ann-k 1000` running on
  cpu-g2 n3446. Partial 583/810 fair cells: recall 0.575, nDCG 0.374
  (+0.005 nDCG over baseline). Modest improvement, as expected for
  retrieval-side levers alone.
- **Eval row4 (35532399)** — `--embed-model qwen3-8b-augminimal --dedupe
  --ann-k 1000`. Partial 100/946: recall 0.480, nDCG 0.328 — **UNDER baseline**.
  Confirmed dud: aug-embed dilutes gold equally with namesake distractors.
  **Cancelled at ~110 cells to save compute.** Plus row 5 (aug + all levers)
  cancelled by dependency.

## 2026-05-25 — HM1 LSv2-style slogan regen chain (overnight, in flight)

- New prompt template: `pipeline/generate_slogans/prompts/lsv2-style.j2`
  (kind-aware system principles, dep names in context, ASCII-only).
- New prompt row registered in DB: `slogan_prompt.name='lsv2-style'`.
- **Stage 1 regen** (SLURM 35532772, 16 shards): generates 337K slogans via
  Nebius qwen3-235b with the lsv2-style prompt. Writes to slogan table
  under `(prompt_name='lsv2-style', model_name='qwen3-235b')`. ETA ~3.5 h
  due to Nebius rate limiting (~1.6 calls/sec/shard × 16 = 25/sec total).
  Estimated cost ~$40 (in_tok 475/call × 337K × $0.20/M + out_tok
  38/call × $0.60/M).
- **Stage 2a embed** (SLURM 35532798, 8 GPUs, gpu-rtx6k): embeds lsv2-style
  slogan TEXT as-is into a new `embedding_model.name='qwen3-8b-lsv2slogan'`.
  Used by row 6 ("lsv2-only" eval). ETA ~30 min after regen completes.
- **Stage 2b embed-to-qwen8b** (SLURM 35532814, 8 GPUs): ALSO embeds the
  same slogans into the existing `qwen3-8b` model_name so the harness's
  default retrieval naturally picks up BOTH formal AND lsv2-style slogans
  per decl (multi-slogan ensemble at retrieval). Used by row 7 and row 10.

## 2026-05-25 — Graph-expansion experiment (HM3)

- New `--graph-expand` flag on `run_eval_v2.py`: for each top-K cosine
  candidate, look up its `formal_dependency` parents via extends/field/sig
  edges (filtered to Mathlib v427+v428), surface those parents as
  additional candidates, RRF-fuse with cosine.
- Mechanism: directly attacks the "namesake child outranks gold" failure
  (e.g. `Functor.IsEquivalence` retrieved for "functor" → graph surfaces
  its parent `Functor`).
- Smoke (5 Lattice cells, all levers + graph): 5/5 hits, nDCG 0.926. The
  same smoke without graph was nDCG 0.804.
- Uses graph signal LSv2 explicitly throws away after corpus build.

## 2026-05-25 — Overnight ablation roster (9 rows, in flight)

| # | tag | EVAL_FLAGS | SLURM | status |
|---|---|---|---|---|
| 1 | baseline | (none) | n/a | DONE (0.370/0.568) |
| 2 | dedupe + annk1000 | `--dedupe --ann-k 1000` | 35531989 | RUNNING, ~30 min ETA |
| 3 | + trigram + hyde | + `--hybrid-trigram --hyde ensemble` | 35532113 | PEND on row2 |
| 4 | augembed only | `--embed-model qwen3-8b-augminimal --dedupe --ann-k 1000` | 35532399 | **CANCELLED** (proven dud, 0.328 nDCG at 100 cells) |
| 5 | augembed + all | as row4 + trigram + hyde | 35532400 | **CANCELLED** (dependent on row4) |
| 6 | lsv2-only + all | `--embed-model qwen3-8b-lsv2slogan ...` | 35532799 | PEND on regen + embed |
| 7 | formal + lsv2 ensemble + all | `--embed-model qwen3-8b ...` (post-stage-2b) | 35532815 | PEND on regen + embed-2b |
| 8 | all + graph | `... --graph-expand` | 35532986 | PEND on CPU quota |
| 9 | graph-only | `--dedupe --ann-k 1000 --graph-expand` | 35532987 | PEND on CPU quota |
| 10 | ensemble + all + graph (kitchen sink) | row 7 + `--graph-expand` | 35533004 | PEND on stage-2b |

## 2026-05-25 — Morning status (overnight aftermath)

**What happened overnight:**

- **Rows 3, 8, 9 all hit SLURM's 8h time limit before finishing** (Aurora slowness blew past my estimate). Partial JSONLs preserved.
- **Regen completed all 16 shards** (exit 0 each) but only inserted **179K of 337K target slogans** — the time-bound + Nebius rate-limiting capped each shard at ~10-20K rows.
- **All embed array tasks failed** with `ModuleNotFoundError: No module named 'torch'` — gpu-rtx6k compute nodes don't have torch installed and we can't write to the system python. The other agent had retrofitted reembed_augminimal.py with a `--device nebius` path which is why row 4's augminimal eval had embeddings to query.
- **Rows 6, 7, 10 (chained on failed embed) marked `DependencyNeverSatisfied`** — never ran.

**Surprise good news — partial data from killed rows is dramatically better than projected:**

| row | partial cells | recall@10 fair-810 | nDCG@10 fair-810 | vs LSv2 (0.657/0.494) |
|---|---:|---:|---:|---|
| baseline | 810 (full) | 0.568 | 0.370 | -0.089 / -0.124 |
| row 2 dedupe+annk | 815 (full) | 0.569 | 0.371 | -0.088 / -0.123 (no change) |
| **row 3 trigram+hyde** | **724** (87%) | **0.699** | **0.462** | **+0.042 / -0.032** |
| **row 8 all+graph** | **514** (63%) | **0.698** | **0.484** | **+0.041 / -0.010** |
| **row 9 graph-only** | **796** (98%) | **0.658** | **0.450** | **+0.001 / -0.044** |

Row 8 partial nDCG **0.484** is within 0.01 of LSv2 retriever-only **0.494**. Row 8's recall **0.698 BEATS LSv2's 0.657**.

**Recovery actions (submitted at ~11:45 AM PDT):**

- Resubmitted rows 3/8/9 (SLURM 35542221/22/23) with `--time=14:00:00`; eval is resume-safe so they only finish remaining cells.
- Resubmitted regen array (35542332) with `--time=08:00:00`; resume-safe so it picks up only the missing 158K.
- Replaced `embed_slogans.py` GPU path with a Nebius API path (mirrors what the augminimal job used). Resubmitted embed arrays (35542333 → qwen3-8b-lsv2slogan; 35542334 → qwen3-8b ensemble) on cpu-g2 partition (no torch needed).
- Chained rows 6 (35542335), 7 (35542352), 10 (35542353) on the respective embed completions.

If row 8 finishes the remaining 296 cells with the partial-trend performance, its final nDCG plausibly lands **0.47-0.50**. Combined with row 10 (kitchen sink including formal+lsv2 ensemble) we may credibly beat LSv2 retriever-only.
