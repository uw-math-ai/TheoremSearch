# Corpus Size History

Tracks DB stats at each major milestone.

| Date | Nodes | Edges | DB Size | Source | Notes |
|------|-------|-------|---------|--------|-------|
| ~2026-02 | 183,807 | 39,439,843 | 1.9 GB | `BRAINDUMP.md` § "Current State" | Pre-precision-filter. All implicit tactic traces included — extreme noise (110:1 implicit:direct ratio). |
| 2026-03-01 | 185,703 | 1,772,669 | 50.4 MB | `CORPUS_TECHNICAL_REPORT.md` § 3 | After geometric range containment + `isDirect` filtering. Pruned 99.3% of implicit edges. Theorems/lemmas only. |
| 2026-04-04 | 2,355 | 4,584 | — | `run_logs.md` § Run 1 | 50-file test (SLURM job 34329727). Sanity check only. |
| 2026-04-05 | 292,361 | 1,447,190 | 144 MB | `run_logs.md` § Final Rebuild + SQL query (see below) | Full Mathlib extraction with new `ExtractData.lean`. All declaration kinds. 7,353/7,860 files (93.5%). All edges direct (`is_implicit = 0`). |
| 2026-04-07 | 313,574 | 1,640,670 | 145.5 MB | `run_logs.md` § Run 7 + SQL query (see below) | Module syntax fix (`const2ModIdx` compare). 7,858/7,860 files (99.97%). +21k nodes, +193k edges recovered. |
| 2026-05-07 | 380,933 | 16,155,963 | 1.6 GB | `run_logs.md` § V2 — Mathlib ingestion | V2 pipeline switch: Evan's lean-graph parser (kernel env walk) replaces v1 InfoTree. 6 typed edge categories (proof/sig/def/field/docref/extends). +21% nodes, +885% edges, +377k signatures. |
| 2026-05-09 | 385,504 | 16,395,193 | ~1.6 GB | `run_logs.md` § V2 — Community projects + SQL query | V2 + 9 v4.29.0 community projects (apap, cam-combi, chandra-furst-lipton, combinatorial-games, forbidden-matrix, gibbs-measure, misc-yd, PersistentDecomp, add-combi). brownian-motion + toric deferred (pin Mathlib v4.30.0-rc1). Most projects extend Mathlib namespace, so unique-node deltas are small. Local DB: `formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db`. |
| 2026-05-18 | 404,491 | 18,410,881 | 1.7 GB | `run_logs.md` § V2 — Pipeline B/C resolution + new project additions | Multi-toolchain extension: added PrimeNumberTheoremAnd (v4.28.0), sphere-packing-math-inc (v4.28.0), formal-conjectures (v4.27.0), plus Sphere-Packing-Lean and ClassFieldTheory from May 16 Pipeline A. Fresh Mathlib clones built per toolchain (`mathlib4_v428`, `mathlib4_v427`) with lean-graph `lean-v4.28` / `lean-v4.27` branches. 4 projects failed extraction (sphere-eversion proofwidgets npm; SciLean BLAS FFI; FormalBook rc1 API drift; lean-stat-learning-theory Lake API). Per-project `lean_toolchain`/`mathlib_rev`/`git_commit` metadata recorded for the 3 new rows. Local DB: `formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db`. |

### SQL verification (2026-04-05)

```sql
SELECT 'nodes', COUNT(*) FROM nodes
UNION ALL SELECT 'edges', COUNT(*) FROM edges
UNION ALL SELECT 'edges_direct', COUNT(*) FROM edges WHERE is_implicit = 0
UNION ALL SELECT 'edges_implicit', COUNT(*) FROM edges WHERE is_implicit = 1;
-- nodes|292361  edges|1447190  edges_direct|1447190  edges_implicit|0

SELECT kind, COUNT(*) FROM nodes GROUP BY kind ORDER BY COUNT(*) DESC;
-- theorem|219652  def|61584  constructor|4001  recursor|3383  inductive|3383  opaque|261  unknown|97

-- DB size from: du -sh global_corpus.db → 144M
```

---

## LeanDojo comparison (Benchmark 4)

**Source:** Yang et al. 2023, ReProver paper. Mathlib commit `29dcec074de168ac2bf835a77ef68bbe069194c5` (Lean 4 v4.10.0-rc1, mid-2024).

| Metric | LeanDojo Benchmark 4 | Our corpus (2026-04-05) |
|--------|---------------------|------------------------|
| Mathlib .lean files | 4,447 | 7,860 (larger, newer Mathlib) |
| Files traced/extracted | 5,674 (full dep closure incl. Batteries, Lean core) | 7,353 / 7,860 (93.5%, Mathlib only) |
| Reported file failures | None (100% on that snapshot) | 2 files (0.03%) |
| Corpus entries | ~180,973 (full dep tree); est. 150–160k Mathlib-only | 313,574 nodes (235,580 theorems) |
| "Premises" / edges | 167,779 distinct constants in tactic proofs | 1,640,670 syntactic dependency edges |

**Why LeanDojo is not a useful baseline for our 6.5% miss rate:**
- Their method is traced execution during normal compilation; ours is InfoTree re-elaboration. Different failure modes.
- They only count tactic-style proofs; term-style proofs appear in their data but are excluded from benchmark counts.
- They don't report file-level failure rates at all — their "100%" applies to a smaller, older snapshot.
- Their premise count (167k distinct constants) is not comparable to our edge count (1.44M syntactic uses).

**Our theorem count (235,580) already exceeds their estimated Mathlib-only count (150–160k)**, reflecting that we capture all proof styles plus `to_additive`-generated declarations that LeanDojo locates by source position rather than counting separately.

---

## Key transitions

**1.9 GB → 50 MB (Feb → Mar 2026)**
Switched from capturing all compiler traces to only direct syntactic edges via geometric range containment. Edge count dropped from 39M to 1.7M. Source: `CORPUS_TECHNICAL_REPORT.md` § 4A.

**50 MB → 144 MB (Mar → Apr 2026)**
New `ExtractData.lean` captures all declaration kinds (def, inductive, constructor, recursor, opaque), not just theorems/lemmas. Node count jumped 185k → 292k. DB grew due to broader coverage, not bloat. Edge count dropped slightly (1.77M → 1.45M) due to tighter interval attribution. Source: `run_logs.md` § Final Rebuild.

**93.5% → 99.97% (2026-04-07)**
All 507 missing files used the new Lean 4 `public import` / `module` syntax. Fixed by comparing module names in `const2ModIdx` instead of just checking membership. Result: +21,213 nodes, +193,480 edges. Only 2 files remain (genuine timeouts). Source: `run_logs.md` § Run 7.

**v1 → v2 (2026-05-07)**
Switched from InfoTree-based extraction (`ExtractData.lean`) to Evan's `lean-graph` kernel-environment walker. Edges jumped 1.6M → 16.2M (10×) due to 6 typed categories vs single undifferentiated edge. Added 377,849 type signatures + docstrings. Captured structures (field/extends edges) and core Lean declarations that v1 missed. Source: `run_logs.md` § V2 — Mathlib ingestion.

**Mathlib-only → Mathlib + 9 community projects (2026-05-09)**
Extracted 9 v4.29.0 community projects on top of base Mathlib. Each project rebuilt with v4.29.0 toolchain (parallel SLURM array, ~30–60min per project), then extracted via pre-built lean-graph binaries with `LEAN_PATH` pointing at project oleans. brownian-motion + toric deferred — they pin Mathlib at v4.30.0-rc1 and would need a separately built lean-graph binary. Source: `run_logs.md` § V2 — Community projects.

**Single-toolchain → multi-toolchain corpus (2026-05-18)**
Added projects pinned to older toolchains (v4.27.0, v4.28.0) by building separate Mathlib workspaces per toolchain with the matching `lean-graph` branches (`lean-v4.27`, `lean-v4.28`). Successful adds: PrimeNumberTheoremAnd, sphere-packing-math-inc (v4.28.0); formal-conjectures (v4.27.0). Per-project `lean_toolchain`, `mathlib_rev`, `git_commit` recorded in the `projects` table for the first time. Source: `run_logs.md` § V2 — Pipeline B/C resolution.
