# Lean Corpus v3

A graph corpus of Lean 4 projects with typed dependency edges, declaration
signatures, and docstrings. Built from the `lean-graph` extractor
(<https://github.com/aurasoph/lean-graph>), covers Mathlib + Batteries at
three toolchains plus 24 community projects.

## What's here

```
lean-graph-corpus-v3/
├── README.md                this file
├── SCHEMA.md                full DB + NDJSON field reference
├── projects_manifest.txt    human-readable list of all 30 projects
├── corpus_v3.db             SQLite, all projects ingested into 3 tables
├── ndjson/                  60 files: per-project raw extractions
│   ├── Mathlib_v429.ndjson      + _statements.jsonl
│   ├── ClassFieldTheory.ndjson  + _statements.jsonl
│   └── ... 30 projects
├── jobs/                    sbatch files (klone) to reproduce ndjson/
└── ingestion/               Python: ndjson/ → corpus_v3.db
    ├── database.py
    └── ingest.py
```

## Projects covered (30 total)

- **Mathlib** at v4.27.0, v4.28.0, v4.29.0 — names: `Mathlib_v427`, `Mathlib_v428`, `Mathlib_v429`
- **Batteries** at v4.27.0, v4.28.0, v4.29.0 — `Batteries_v427/8/9`
- **24 community projects**:
  - v4.29: pfr, misc-yd, cam-combi, ClassFieldTheory, PersistentDecomp,
    gibbs-measure, chandra-furst-lipton, Sphere-Packing-Lean, FLT, apap,
    brownian-motion, carleson, physlib, forbidden-matrix, toric, add-combi,
    cslib, combinatorial-games, flt-regular
  - v4.28: sphere-packing-math-inc, sphere-eversion, PrimeNumberTheoremAnd, HarderNarasimhan
  - v4.27: formal-conjectures

See `projects_manifest.txt` for the full list with repo URLs, ref pins, and
the Lean `lean_lib` name used as the extraction root.

## Quick start: querying the DB

```python
import sqlite3
conn = sqlite3.connect('corpus_v3.db')
conn.row_factory = sqlite3.Row

# All theorems that depend on Eq.trans through proof edges
c = conn.execute('''
    SELECT n.full_name, n.module
    FROM nodes n
    JOIN edges e ON e.source_id = n.id
    JOIN nodes t ON t.id = e.target_id
    WHERE t.full_name = 'Eq.trans' AND e.edge_type = 'proof'
    LIMIT 50
''')
for row in c:
    print(row['full_name'], '|', row['module'])

# Filter out anonymous instances from results
c = conn.execute('SELECT COUNT(*) FROM nodes WHERE is_instance = 0')
```

Each project's NDJSON also stands on its own — if you only want one project's
graph you can stream-parse `ndjson/<project>.ndjson` directly. See SCHEMA.md
for the line format.

## Schema overview

Three tables: `projects`, `nodes`, `edges`. Six edge types: `extends`,
`field`, `sig`, `proof`, `def`, `docref`. Nodes have `is_instance` flag,
`in_degree` (precomputed), `signature`, and `docstring` columns. Edges
between same source/target are deduplicated per `edge_type`. Full schema in
`SCHEMA.md`.

## Filter policy

What we **drop**:

- Compiler-generated artifacts: recursors, `noConfusion`, match-block decls,
  auxiliary lemmas without source positions
- Structural plumbing: `*.toFoo` coercions from `extends`, structure field
  projection functions (`Mul.mul`, `Norm.norm`)
- Tactic-internal namespaces: `Lean.Meta`, `Lean.Elab`, `Lean.Core`,
  `Lean.Server`, `Lean.Lsp`, `Lean.Grind`, `Lean.Omega`, `Mathlib.Tactic`,
  `Mathlib.TacticAnalysis`, `Mathlib.Meta`, `Std.Internal`, `Std.Tactic`,
  `Aesop`, `Qq`. (Note: this excludes a fair amount of Lean compiler and
  metaprogramming infrastructure. If you need it, use `--include-aux` when
  re-extracting, or filter `corpus_v3.db` per your downstream criteria.)

What we **keep and tag**:

- Anonymous typeclass instances (e.g. `instMonadReaderOfMonadReaderOf`,
  `AddGroupNorm.instAdd`) — present as nodes with `is_instance: true`.
  Filter via `WHERE is_instance = 0` if you don't want them.

Full filter source: `LeanGraph/Graph/FilterCommon.lean` in the lean-graph
repo (commit recorded in `projects.lean_graph_commit`).

## Diff vs `corpus_v2.db` (simku22's earlier corpus)

| | corpus_v2.db | corpus_v3.db |
|---|---|---|
| Projects | 15 (Mathlib v4.29 + 14 community) | 30 (Mathlib×3 + Batteries×3 + 24 community) |
| Schema | nodes + edges + projects | same, **+ `is_instance`, `in_degree`, `lean_graph_commit`** |
| Sig edges | `target`, `kind` | + `binder`, `position`, `role`, `via_proj` |
| Anonymous instances | dropped | kept, flagged via `is_instance` |
| Phantom-edge bug | present (prefix-strip in `getParentDeclaration`) | fixed via source-range matching |

## Reproduce from scratch

The `jobs/` directory has one self-contained `sbatch` file per project plus
parameterized ones for Mathlib and Batteries. Each clones its project at a
pinned commit, adds `leanGraph` as a Lake dependency, builds, and extracts
into `ndjson/`. All use the `ckpt-all` partition with `--requeue`.

```bash
cd jobs/

# Community projects (24)
for f in build_*.sbatch; do sbatch "$f"; done

# Mathlib v4.29 (uses cached build workspace if present)
sbatch mathlib_v429_extract.sbatch

# Mathlib v4.28 / v4.27 (build from source)
sbatch --job-name=mathlib-v428-build-extract \
       --export=ALL,MATHLIB_TAG=v4.28.0,TC=leanprover/lean4:v4.28.0,LG_BRANCH=lean-v4.28,VLABEL=v428 \
       mathlib_build_extract.sbatch
sbatch --job-name=mathlib-v427-build-extract \
       --export=ALL,MATHLIB_TAG=v4.27.0,TC=leanprover/lean4:v4.27.0,LG_BRANCH=lean-v4.27,VLABEL=v427 \
       mathlib_build_extract.sbatch

# Batteries at each toolchain
for v in v429 v428 v427; do
    case $v in v429) tag=v4.29.0 lg=lean-v4.29 tc=leanprover/lean4:v4.29.0;;
              v428) tag=v4.28.0 lg=lean-v4.28 tc=leanprover/lean4:v4.28.0;;
              v427) tag=v4.27.0 lg=lean-v4.27 tc=leanprover/lean4:v4.27.0;;
    esac
    sbatch --job-name=batteries-$v-build-extract \
           --export=ALL,BATTERIES_TAG=$tag,TC=$tc,LG_BRANCH=$lg,VLABEL=$v \
           batteries_build_extract.sbatch
done

# After all 30 extractions land:
sbatch ingest_corpus.sbatch
```

Adding a new community project: copy any existing `build_<project>.sbatch`,
edit the six variables at the top (PROJECT, REPO, REF, TC, LG_BRANCH,
MAIN_LIB), submit.

## Provenance

- Built on UW Hyak / `klone` by aurasoph, May 2026
- `lean-graph` HEAD: branch `main` at commit recorded in `projects.lean_graph_commit`
- Toolchains: `leanprover/lean4` v4.27.0 / v4.28.0 / v4.29.0
- Apptainer image: `/gscratch/scrubbed/aurasoph/lean-check.sif`
- Built using `ckpt-all` with `--requeue`
