# Extraction Run Logs

---

## Run 1 — 50-file test

**Job:** 34329727
**Submitted:** 2026-04-04
**Scope:** 50 files (`--limit 50`, first 50 alphabetically from `Mathlib/Algebra/...`)
**Workers:** 4 parallel
**Result:** All 50 AST files generated successfully

### DB stats
- Nodes: 2,355
- Edges: 4,584
- Files: 50
- Kinds: theorem (1,754), def (541), inductive (20), constructor (20), recursor (20)
- Paths: canonical (`Mathlib/...`) — no absolute paths

### Spot check: `Algebraic.aleph0_le_cardinalMk_of_charZero`

**Source:** https://github.com/leanprover-community/mathlib4/blob/290b6cf8bece4a127f9ae1ee915a1ab3e3dfe0fa/Mathlib/Algebra/AlgebraicCard.lean#L37

```lean
theorem aleph0_le_cardinalMk_of_charZero (R A : Type*) [CommRing R] [Ring A]
    [Algebra R A] [CharZero A] : ℵ₀ ≤ #{ x : A // IsAlgebraic R x } :=
  infinite_iff.1 (Set.infinite_coe_iff.2 <| infinite_of_charZero R A)
```

**Edges recorded in DB (2):**

| Dependency | File |
|---|---|
| `Algebra` | `Mathlib/Algebra/Algebra/Defs.lean` |
| `Algebraic.infinite_of_charZero` | `Mathlib/Algebra/AlgebraicCard.lean` |

**Full expected dependency set:**

| Dependency | What it is |
|---|---|
| `Cardinal.aleph0` (ℵ₀ notation) | The cardinality constant |
| `Cardinal.mk` (# notation) | Cardinal of a type |
| `IsAlgebraic` | The predicate on elements |
| `CommRing` | Type class on R |
| `Ring` | Type class on A |
| `Algebra` | Type class R → A ✓ (in DB) |
| `CharZero` | Type class on A |
| `Cardinal.infinite_iff` | `Infinite α ↔ ℵ₀ ≤ #α` |
| `Set.infinite_coe_iff` | `Infinite ↥s ↔ s.Infinite` |
| `Algebraic.infinite_of_charZero` | Theorem just above — the actual content ✓ (in DB) |

**Analysis:** The 2 captured edges are correct. Missing dependencies (`Cardinal.infinite_iff`, `Set.infinite_coe_iff`, type class constants) are from files outside the 50-file test set — expected. Structure-wise this is a thin wrapper: real work is in `infinite_of_charZero` (which uses `Nat.cast_injective` and `isAlgebraic_nat`). This theorem just converts between the `Set.Infinite` predicate and the cardinal inequality `ℵ₀ ≤ #...` via two iff lemmas.

### Decision
Results look good. Running full Mathlib array job to capture all cross-file dependencies.

---

## Run 2 — Full Mathlib array job (cancelled)

**Job:** 34330041
**Submitted:** 2026-04-04
**Scope:** All ~7,860 Mathlib files, 100 SLURM tasks (`--array=0-99%50`), 4 workers/task
**Result:** Cancelled — complex files (e.g. `ModuleCat/Stalk.lean`, `CommAlgCat/FiniteType.lean`, `Field/IsField.lean`) timing out at 600s

### Finding
A subset of heavy Mathlib files (deep category theory / algebraic geometry) exceed the 600s per-file timeout. These files re-elaborate a large transitive import closure and cannot complete in time.

### Decision
Implement two-pass retry strategy (Option B):
- Pass 1: run all files at 600s timeout
- Pass 2: identify files missing `.ast.json`, re-run those at 3600s timeout
This should achieve near-complete coverage without the complexity of a Lake build integration.

---

## Run 3 — Full array after heartbeat fix

**Job:** 34330305
**Submitted:** 2026-04-04T10:27
**Scope:** All ~7,860 Mathlib files, 100 SLURM tasks, 4 workers/task, 600s timeout
**Duration:** ~20 min
**Result:** COMPLETED — first successful full-coverage extraction pass

### Fixes applied since Run 2
- `ExtractData.lean`: added `const2ModIdx` filter to skip imported constants before `findDeclarationRanges?` (was iterating ~200k constants per file)
- `ExtractData.lean`: passed `Options.empty |>.set \`maxHeartbeats (0 : Nat)` into `commandState` — default was 400k heartbeat limit causing ~40% of files to fail
- `factory.py`: removed temp extractor copy/delete pattern — all tasks now share the absolute path to `ExtractData.lean` (was a race condition)

---

## Run 4 — Full array (second pass)

**Job:** 34333466
**Submitted:** 2026-04-04T12:19
**Duration:** ~65 min
**Result:** COMPLETED

---

## Run 5 — Full array (third pass)

**Job:** 34335622
**Submitted:** 2026-04-04T13:59
**Duration:** ~17 min
**Result:** COMPLETED

---

## Run 6 — Retry pass (missing files, 3600s timeout)

**Job:** 34337133
**Submitted:** 2026-04-04T16:47
**Scope:** Files missing `.ast.json` from prior passes (`--retry --timeout 3600 --total-tasks 100`)
**Workers:** 2 per task (heavy files need more RAM per worker)
**Duration:** ~2 hours
**Result:** COMPLETED
**Coverage:** 7,353 / 7,860 files (93.5%) — remaining ~500 files are macro-generated or private declarations with no extractable content

---

## Rebuild attempts

### Rebuild 1 — FAILED (job 34337134, 2026-04-04T16:47)
Ran concurrently with Run 6 retry pass. SQLite `database is locked` error — two processes writing simultaneously.

### Rebuild 2 — TIMEOUT (job 34339613, 2026-04-04T20:29)
Timed out during degree recalculation: correlated subquery over 292k nodes × 1.4M edges exceeded 1 hour in SQLite.

### Rebuild 3 — TIMEOUT (job 34344586, 2026-04-04T23:05)
Same timeout issue.

### Fix applied
Removed `in_degree`/`out_degree` recalculation from `rebuild.py` entirely — these can be computed live from the `edges` table. The correlated subquery is too slow for SQLite at this scale.

---

## Final Rebuild — COMPLETED

**Job:** 34348977
**Submitted:** 2026-04-05T01:10
**Duration:** ~63 min
**Result:** COMPLETED

### Final DB stats
- Nodes: 292,361
- Edges: 1,447,190
- DB size: ~131 MB
- Files extracted: 7,353 / 7,860 (93.5%)

### Kind breakdown
| Kind | Count |
|------|-------|
| theorem | ~180k |
| def | ~80k |
| inductive | ~10k |
| instance | ~10k |
| others (abbrev, axiom, opaque, constructor, recursor) | ~12k |

### Spot check: `Algebraic.aleph0_le_cardinalMk_of_charZero`
Full run now returns all 10 expected dependencies (vs 2 in the 50-file test where cross-file deps were absent). Confirmed correct.

---

## Coverage gap investigation (2026-04-07)

### Finding: all 507 missing files use new Lean 4 module syntax

The 507 Mathlib files without `.ast.json` were investigated. Key evidence:
- SLURM retry logs (job 34337133) show only 1 timeout across all 100 tasks
- `find -newer` shows only 2 new `.ast.json` files written during retry — the rest ran (exit code 0) but wrote nothing
- `grep -rl "^public import\|^module$"` against the 507 missing files: **507/507 match**

All 507 files use the new Lean 4 `public import` / `module` / `@[expose] public section` syntax. ExtractData.lean re-elaborates them without error but finds no declarations because the InfoTree structure for this module syntax differs from what our probe expects.

### Sample files
```
Mathlib/Algebra/Group/Commute/Defs.lean
Mathlib/Algebra/Group/Units/Basic.lean
Mathlib/Algebra/Group/Defs.lean
Mathlib/Algebra/Group/End.lean
Mathlib/Algebra/Group/Torsion.lean
Mathlib/Algebra/Group/Subsemigroup/Operations.lean
Mathlib/Algebra/PresentedMonoid/Basic.lean
Mathlib/Logic/Basic.lean
Mathlib/Logic/Equiv/List.lean
Mathlib/Logic/Embedding/Set.lean
```

### Conclusion
- The 93.5% coverage ceiling is entirely explained by a single cause: the new module syntax
- No amount of timeout/retry will help — the files run successfully, they just produce no output
- Fix requires updating `ExtractData.lean` to handle `public import` / `module` declaration style
- Once fixed, coverage should approach ~100%

---

## Run 7 — Retry with const2ModIdx fix (in progress)

**Job:** 34429968
**Submitted:** 2026-04-07
**Scope:** ~507 files missing `.ast.json` (all using new `module` syntax)
**Fix applied:** `collectDeclarations` now compares module name instead of just checking `const2ModIdx.contains` — current-file constants in new module syntax are no longer filtered out
**Config:** 10 SLURM tasks (`--array=0-9`), 4 CPUs, 16G RAM, 2h timeout, 3600s per file
**Test:** `Mathlib/Algebra/Group/Defs.lean` produced 780 declarations / 1,186 premises (5.5 MB .ast.json) before submitting

### Result
- Files extracted: 7,858 / 7,860 (99.97%)
- Task 0 hit 2h time limit at 50/51 files — 2 files remain unextracted

### Rebuild

**Job:** 34432610 (`--dependency=afterok:34429968`)
**Duration:** ~62 min
**Result:** COMPLETED

### Final DB stats
- Nodes: 313,574 (was 292,361 → +21,213 from module syntax fix)
- Edges: 1,640,670 (was 1,447,190 → +193,480)
- DB size: 145.5 MB
- File coverage: 7,858 / 7,860 (99.97%)

---

## Multi-project ingestion — Clone phase (2026-04-08)

Cloned all 32 Lean 4 projects from https://leanprover-community.github.io/lean_projects.html into `data/formalization_projects/`.

### Clone sizes (notable)

| Project | Size | Notes |
|---------|------|-------|
| FLT | 19 GB | Full build cached in repo |
| equational_theories | 445 MB | Partial build artifacts |
| seymour | 25 MB | |
| SciLean | 18 MB | |
| physlib | 12 MB | |
| Brouwer | 9.4 MB | |
| 24 others | < 6 MB each | Lightweight |

Next: `lake build` all projects (SLURM overnight), then extract + rebuild.

## Multi-project build

**Job:** 34434728 (cancelled — elan toolchain race condition + home dir quota)
**Job:** 34645893
**Submitted:** 2026-04-15
**Scope:** 32 projects, `--array=0-31%8` (max 8 concurrent), 4 CPUs / 16G each, 4h limit
**Script:** `formalized_graph/scripts/run_build_projects.sh`
**Pre-req:** All 11 Lean toolchains (v4.18.0 through v4.30.0-rc1) pre-installed in `~/.elan` (symlinked to gscratch after home dir quota issues)

### Results (job 34646058)
- 2 COMPLETED (tasks 0, 20), 6 FAILED (broken upstream projects), 24 TIMEOUT at 4h
- Timeouts caused by each project building Mathlib from source (~4-6h each)

### Retry with cache (job 34782493)
**Submitted:** 2026-04-22
**Fix:** Added `lake -R exe cache get` to download pre-built Mathlib oleans from CI before building. Should reduce build time from hours to minutes per project.
**Config:** 12h time limit, `--array=0-31%8`

---

# V2 Pipeline (lean-graph)

Switched from per-file `ExtractData.lean` to Evan's `lean-graph` (per-project unified extraction, 6 edge types). Source: `formalized_graph_v2/`.

---

## V2 — Mathlib build + ImportGraph (2026-05-06)

**Job:** 35070606
**Scope:** Build Mathlib (commit `8a178386`) + lean-graph ImportGraph library
**Toolchain:** v4.29.0
**Result:** COMPLETED — 28 ImportGraph modules built in ~2 min (Mathlib built during `lake update`)

### Setup notes
- lean-graph added to Mathlib lakefile as: `require «lean-graph» from git "https://github.com/aurasoph/lean-graph" @ "main"`
- `lake update lean-graph` required to add to manifest
- HYAK GLIBC 2.28 too old for Lean v4.29.0 bundled clang — fixed with `LEAN_CC=/usr/bin/gcc` + `LIBRARY_PATH=$LEAN_TOOLCHAIN/lib`

---

## V2 — Mathlib extraction (2026-05-07)

**Job:** 35072742 (build + graph), 35102401 (export_statements)
**Scope:** Full Mathlib unified dependency graph + type signatures
**Duration:** ~8h build, ~40 min graph extraction, ~20 min statement export
**Result:** COMPLETED

### Output files
- `Mathlib.ndjson`: 821 MB, 380,933 declarations
- `Mathlib_statements.jsonl`: 377,849 signatures with docstrings

---

## V2 — Mathlib ingestion (2026-05-07)

**Job:** 35105524
**Optimization:** sbcast to node-local SSD (`/tmp`) for fast I/O — previous attempt (35104811) timed out at 2h on NFS; this completed in minutes
**Result:** COMPLETED

### Final DB stats (corpus_v2.db)
- **Nodes:** 380,933
- **Edges:** 16,155,963
- **DB size:** 1.6 GB

### Edge type breakdown
| Type | Count | Description |
|------|-------|-------------|
| proof | 8,424,452 | Lemmas used in proofs |
| sig | 5,724,904 | Types in theorem signatures |
| def | 1,920,671 | Definitions used in definitions |
| field | 51,606 | Structure field dependencies |
| docref | 32,744 | Docstring backtick references |
| extends | 1,586 | Structure inheritance |

### Kind breakdown
| Kind | Count |
|------|-------|
| theorem | 264,592 |
| definition | 65,683 |
| instance | 36,440 |
| structure | 3,057 |
| constructor | 3,044 |
| class | 2,276 |
| opaque | 2,023 |
| other | ~1,818 |

### Comparison to v1
| Metric | v1 (ExtractData.lean) | v2 (lean-graph) |
|--------|----------------------|-----------------|
| Nodes | 313,574 | 380,933 (+21%) |
| Edges | 1,640,670 | 16,155,963 (+885%) |
| Edge types | 1 (undifferentiated) | 6 (proof/sig/def/field/docref/extends) |
| Signatures | none | 377,849 |
| Structures | blind (0 outgoing edges) | field + extends edges |
| Core Lean | missing | included |

---

## V2 — Community projects: extraction attempt 1 (2026-05-08)

**Job:** 35123856 (array, 11 tasks)
**Scope:** 11 v4.29.0 community projects (add-combi, apap, brownian-motion, cam-combi, chandra-furst-lipton, combinatorial-games, forbidden-matrix, gibbs-measure, misc-yd, PersistentDecomp, toric)
**Approach:** Run pre-built `graph` and `export_statements` binaries (from v2 Mathlib build) against each project's existing oleans via `LEAN_PATH`, bypassing the `importGraph` ↔ `lean-graph` module name collision.
**Duration:** 10 sec – 3 min per task (all COMPLETED state)
**Result:** PARTIAL — only `add-combi` produced valid output

### Output
- `add-combi.ndjson`: 31,632 nodes, 879,381 edges; `add-combi_statements.jsonl`: 31,632 entries
- 10 other projects: empty NDJSON, "incompatible header" errors on their `.olean` files

### Diagnosis
The other 10 projects' oleans were built in April 2026 with a different Lean toolchain. Even though their `lean-toolchain` files now read v4.29.0, the cached oleans on disk were not rebuilt. Lean refuses to load oleans whose header doesn't match the running toolchain.

### Mathlib commit alignment (for reuse strategies)
- 7 projects pinned at `8a178386...` (matches v2 Mathlib commit): apap, cam-combi, chandra-furst-lipton, forbidden-matrix, gibbs-measure, misc-yd, PersistentDecomp
- 3 outliers: brownian-motion (`f23306121184...`), combinatorial-games (`69cbc416b3f5...`), toric (`b43655dfe21527...`)

---

## V2 — Community projects: rebuild plan (2026-05-09)

**Approach decision:** Brute-force rebuild each project from source under v4.29.0. Considered sharing the v2 Mathlib build dir via symlinks, but Lake's per-artifact trace validation (per Mathlib wiki + Lake docs) requires byte-identical sources, toolchains, and trace sidecars — making symlinks fragile and lakefile-edit-heavy. SLURM array parallelism makes brute force the right tradeoff.

### Validation: APAP interactive rebuild
- Ran on n3497 via salloc (8 cpu, 32G), pinned `lean-toolchain` to `leanprover/lean4:v4.29.0`, wiped `.lake/build` + dependency build dirs, ran `lake build APAP`.
- Build completed (3138 jobs, ~1hr); confirms toolchain mismatch was the only blocker. Lake DID rebuild Mathlib from source despite our v2 Mathlib being on the same commit (trace validation distrusts foreign build dirs — confirmed via web research).

### Job submitted
**Job:** 35129795 (rebuild_projects.sh array, 0–9)
**Resources:** 16 cpu, 64G mem, 8h time per task
**Wall time:** 12 min – 1h55m per project (PersistentDecomp slowest); 8/10 succeeded
**Failures:** brownian-motion + toric — both pin Mathlib at v4.30.0-rc1; our lean-graph binary is built with v4.29.0 and can't read their oleans. Deferred (would need a separately built lean-graph binary).

---

## V2 — Community projects: extraction + ingestion (2026-05-09)

**Extraction job:** 35133287 (run_extract_projects.sh array, 0–8)
**Wall time:** ~5 min total
**Result:** All 9 projects produced valid NDJSON + statements.jsonl

### Per-project NDJSON line counts
| Project | NDJSON rows |
|---|---|
| Mathlib (base) | 380,933 |
| apap | 238,897 |
| cam-combi | 223,558 |
| misc-yd | 212,368 |
| gibbs-measure | 210,745 |
| combinatorial-games | 193,155 |
| PersistentDecomp | 163,243 |
| forbidden-matrix | 132,651 |
| chandra-furst-lipton | 130,153 |
| add-combi | 31,632 |

**Ingestion job:** 35133636 (run_ingest.sh)
**Wall time:** ~10 min (sbcast + node-local SSD)
**Result:** COMPLETED

### Final DB stats (corpus_v2.db with Mathlib + 9 projects)
- **Nodes:** 385,504
- **Edges:** 16,395,193
- **DB size:** ~1.6 GB
- **Local copy:** `formalized_graph_v2/data/generated/corpus_v2_mathlib_plus_v4.29.db`

### Per-project unique node attribution
| Project | Unique nodes |
|---|---|
| Mathlib | 380,933 |
| combinatorial-games | 2,900 |
| apap | 786 |
| misc-yd | 333 |
| PersistentDecomp | 182 |
| cam-combi | 132 |
| gibbs-measure | 122 |
| forbidden-matrix | 88 |
| chandra-furst-lipton | 28 |
| add-combi | 0 |

### Edge type breakdown
| Type | Count | Δ vs Mathlib-only |
|---|---|---|
| proof | 8,578,010 | +153,558 |
| sig | 5,790,117 | +65,213 |
| def | 1,935,316 | +14,645 |
| field | 52,016 | +410 |
| docref | 38,144 | +5,400 |
| extends | 1,590 | +4 |

### Schema caveat — node attribution
`nodes.project_id` is 1:1 with `INSERT OR IGNORE ON full_name`. Most community projects extend within `Mathlib.*` namespace, so when a project's declaration name collides with a Mathlib name, only the first project to ingest gets the row. Add-combi shows 0 nodes because every name it produces already lives in Mathlib.

This means `project_id` reflects "first project that ingested this name", not "all projects that contain this declaration". Fix (deferred): introduce a many-to-many `node_projects` join table, or — preferably — handle attribution during the future RDS migration where the schema relationships differ anyway.

---

## V2 — Multi-toolchain extension: pipelines A/B/C submitted (2026-05-11)

Three independent pipelines kicked off overnight to extend beyond v4.29.0 community projects:
- **Pipeline A** (v4.29.0): rebuild + extract PFR, Sphere-Packing-Lean, ClassFieldTheory (3 more projects on the v2 Mathlib).
- **Pipeline B** (v4.28.0): fresh Mathlib clone at `8f9d9cff6bd7` + lean-graph `lean-v4.28` branch → rebuild + extract sphere-eversion, PrimeNumberTheoremAnd. Workspace: `formalized_graph_v2/data/mathlib4_v428/`.
- **Pipeline C** (v4.27.0): fresh Mathlib clone at `a3a10db0e9d6` + lean-graph `lean-v4.27` branch → rebuild + extract formal-conjectures. Workspace: `formalized_graph_v2/data/mathlib4_v427/`.

**Job chain (per pipeline):** build → rebuild → extract via `--dependency=afterok`. Submitted IDs 35135420–35135429.

### Overnight outcome — partial
- **A:** array task 0 (PFR) FAILED; tasks 1 & 2 COMPLETED.
- **B:** build FAILED → all downstream `DependencyNeverSatisfied`.
- **C:** build FAILED → all downstream `DependencyNeverSatisfied`.

---

## V2 — Pipeline A/B/C debugging session (2026-05-16)

Resumed on an interactive compute node (salloc, n3432) via Claude to diagnose all three failures. Three independent root causes:

| Pipeline | Root cause | Fix |
|---|---|---|
| A / PFR | PFR's pinned Mathlib deps (Batteries/Qq/Aesop) incompatible with Lean 4.29 core expansion: `Array.min?`, `List.scanl`, `EStateM.run_bind` now builtins → "already declared" cascade; `Qq.Match` uses `TSyntax doSeq` where 4.29 requires `doSeqIndent`. | **Abandoned** PFR. Tasks 1 & 2 already succeeded; resubmit extract only for those. |
| B / v4.28 | v4.28.0 toolchain on HYAK was **corrupt** — `~/.elan/toolchains/.../lib/lean/Lean/Widget/Types.olean` missing. `import Lake` silently fails on missing transitive olean → cascade of "unknown namespace `Lake`" errors that *looked* like a syntax problem but was actually a broken toolchain install. | `elan toolchain uninstall && install`. Added auto-detect guard to `pipeline_b_v428_build.sh` (checks `Widget/Types.olean` existence, force-reinstalls if missing). |
| B + C | lean-graph `lean-v4.27` / `lean-v4.28` packages declare `name = "leanGraph"` and ship their own `[[lean_lib]] name = "ImportGraph"`. Mathlib's pinned `importGraph` dep declares the same `ImportGraph` lib → Lake routes `ImportGraph.*` to the wrong package, lean-graph's `Export/Graph/Tools` modules become unreachable. (v4.29 branch uses `name = "importGraph"` and replaces Mathlib's dep, which is why A worked.) | Remove `importGraph` require from Mathlib's lakefile so lean-graph's `ImportGraph` is sole provider. Mathlib only directly imports `ImportGraph.{Imports, RequiredModules, Meta, Lean.Name}` — all present in lean-graph's tree. |

### Other touches
- Added `.lake/build` → node-local NVMe SSD symlink + exit-trap sync in both B and C build scripts (avoids slow gscratch I/O during compilation).
- Two-script commit `12a470d`: `pipeline_b_v428_build.sh` and `pipeline_c_v427_build.sh`.

### Resubmissions (2026-05-16)
After scancelling the 5 stuck dependents (35135421, 35135423, 35135424, 35135426, 35135429):
- Pipeline B chain → 35286332 (build) → 35286334 (rebuild 0–1) → 35286335 (extract 0–1)
- Pipeline C chain → 35286336 (build) → 35286337 (rebuild) → 35286338 (extract)
- Pipeline A extract only → 35286339 (array 1–2, skipping PFR task 0)

### Pipeline A extract — COMPLETED
Tasks 1 & 2 finished successfully. Outputs:

| Project | Nodes | Edges | NDJSON | Statements |
|---|---|---|---|---|
| Sphere-Packing-Lean | 258,321 | 9,555,292 | 451 MB | 28 MB |
| ClassFieldTheory | 239,306 | 7,886,550 | 371 MB | 28 MB |

### Pipeline B/C status (2026-05-16, eod)
B-build (35286332) and C-build (35286336) FAILED again — investigation pending. `DependencyNeverSatisfied` on both pB-rebuild (35286334) and pC-rebuild (35286337). Stuck dependents still queued: 35286334, 35286335, 35286337, 35286338. Logs: `/gscratch/amath/simku22/logs/p{B,C}_build_352863{32,36}.{out,err}`.

### Corpus state after today
**~4.1 GB** of NDJSON + statement data total across Mathlib + 11 v4.29 community projects (the original 9 from May 9 plus Sphere-Packing + ClassFieldTheory from today). Pipeline B and C results (sphere-eversion, PrimeNumberTheoremAnd, formal-conjectures) still pending the build fix.

---

## V2 — Pipeline B/C resolution + new project additions (2026-05-17 / 2026-05-18)

### Goal
Extend `corpus_v2.db` beyond the May 9 v4.29.0 baseline with projects pinned to older toolchains (v4.28.0, v4.27.0) via the lean-graph extraction pipeline on HYAK. Drove the cancelled May 16 B-build / C-build chains to completion and added 3 new advisor-requested projects (commit `8f78a40`).

### Pipelines run

| Pipeline | Toolchain | Projects attempted | Outcome |
|---|---|---|---|
| B | v4.28.0 | sphere-eversion, PrimeNumberTheoremAnd, SciLean, sphere-packing-math-inc | 2 / 4 succeeded |
| C | v4.27.0 | formal-conjectures, FormalBook | 1 / 2 succeeded |

### Successes — added to corpus

| Project | Unique nodes | Mathlib rev | Project commit | Toolchain |
|---|---:|---|---|---|
| PrimeNumberTheoremAnd | 7,693 | 8f9d9cff | a47cdd65 | v4.28.0 |
| sphere-packing-math-inc | 3,536 | 8f9d9cff | 1e98fb49 | v4.28.0 |
| formal-conjectures | 4,860 | a3a10db0 | 52784c1d | v4.27.0 |

### Failures

- **sphere-eversion (v4.28.0)** — got to ~2400/2906 modules built (Mathlib from source), died on `proofwidgets/widgetJsAll`. Manifest-restore fix prevented `lake update`'s toolchain drift (to v4.30.0-rc2), but proofwidgets pre-seed didn't take. Still pending.
- **SciLean (v4.28.0)** — blocked by BLAS FFI requirement (`LeanBLAS.FFI.FloatArray:dynlib`, `SciLean.FFI.ByteArray:dynlib`) not available on compute nodes. Hardware-level blocker.
- **FormalBook (v4.27.0)** — proof API drift between v4.27.0-rc1 (project's pinned toolchain) and v4.27.0 (what we forced): `div_add_div_same` resolution, type mismatches, aesop failures.
- **lean-stat-learning-theory** — dropped from Pipeline C: proofwidgets v0.0.98 uses `Lake.Hash.ofHashable` not present in Lake v4.27.0. Needs a v4.28+ pipeline.

### Key engineering fixes landed

1. **proofwidgets/widgetJsAll npm error** → add `~/.nvm/.../node/v22.22.2/bin` to PATH on compute nodes; pre-seed JS bundle from matching mathlib workspace (`mathlib4_v427` / `mathlib4_v428`) since same proofwidgets rev → matching `lake.trace` hashes → Lake skips npm step.
2. **`lake update` toolchain drift on sphere-eversion** (advanced `inputRev=master` deps to v4.30.0-rc2-era revs, overwrote `lean-toolchain`) → restore `lake-manifest.json` + `lean-toolchain` from git HEAD after `lake update`, then re-checkout each package to its manifest-pinned rev.
3. **Standard SSD redirect** (`/tmp/proj-*` for `.lake/build` + all package `.lake/build` dirs; EXIT-trap sync back to gscratch) per HYAK storage guidance.

### Final corpus state (`corpus_v2.db`, 1.7 GB)

- **15 projects** (Mathlib + 14 community): 3 new added on top of the May 9 baseline.
- **404,491 nodes** (Δ +18,987 vs May 9 baseline of 385,504).
- **18,410,881 edges** (Δ +2,015,688).

#### Edge type breakdown
| Type | Count |
|---|---:|
| proof | 9,940,567 |
| sig | 6,247,468 |
| def | 2,111,576 |
| field | 55,386 |
| docref | 54,266 |
| extends | 1,618 |

#### Project-level metadata backfill
For the 3 new projects, `projects` rows now carry `lean_toolchain`, `git_commit`, `mathlib_rev`, `url` — read deterministically from each project's working dir during ingestion. The 12 existing v4.29.0 rows were left at `lean_toolchain=v4.29.0` with empty `mathlib_rev`/`git_commit` (they pre-date the lean-graph v4.27/v4.28 branches and the metadata fields).

#### Snapshot files (local, `formalized_graph_v2/data/generated/`)
| File | Date | Size | Contents |
|---|---|---|---|
| `corpus_v2.db` | 2026-05-07 | 1.5 GB | Mathlib only (v4.29.0 baseline) |
| `corpus_v2_mathlib_plus_v4.29.db` | 2026-05-09 | 1.5 GB | Mathlib + 9 v4.29 community projects |
| `corpus_v2_mathlib_plus_v4.27_v4.28_v4.29.db` | 2026-05-18 | 1.7 GB | **Current.** 15 projects across v4.27/v4.28/v4.29 |

The May 7 `corpus_v2.db` is two snapshots behind. Recommendation: archive it (or symlink `corpus_v2.db` → the May 18 snapshot for callers that read the canonical name).

### Open items

- **sphere-eversion**: needs a Mathlib pre-seed (in addition to proofwidgets), or an alternative `cache get` path. Compute-node libcurl/OpenSSL also fails on `lake exe cache get` downloads (unregistered scheme), so source-only build remains the path.
- **SciLean / FormalBook / lean-stat-learning-theory**: blocked, see reasons above.
- **Stale local DB**: replace `corpus_v2.db` with a symlink to the May 18 snapshot, or archive the May 7 baseline.

---
