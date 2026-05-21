# Schema Reference

## SQLite database (`corpus_v3.db`)

Three tables. Indexes on `nodes.full_name`, `nodes.module`, `nodes.project_id`,
`edges.source_id`, `edges.target_id`, `edges.edge_type`. WAL journal mode.

### `projects`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `name` | TEXT UNIQUE NOT NULL | e.g. `Mathlib_v429`, `ClassFieldTheory`, `Batteries_v428` |
| `url` | TEXT | github URL (nullable) |
| `kind` | TEXT NOT NULL DEFAULT `'lean_repo'` | |
| `lean_toolchain` | TEXT | e.g. `v4.29.0` |
| `mathlib_rev` | TEXT | nullable |
| `git_commit` | TEXT | nullable, project's checked-out commit |
| `lean_graph_commit` | TEXT | which lean-graph commit produced the NDJSON |
| `extracted_at` | TIMESTAMP DEFAULT `CURRENT_TIMESTAMP` | |

### `nodes`

One row per Lean declaration, deduplicated by `full_name` across all projects.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `project_id` | INTEGER NOT NULL REFERENCES `projects(id)` | first project that ingested this decl |
| `full_name` | TEXT UNIQUE NOT NULL | e.g. `Mathlib.Algebra.Group.Defs.AddGroup` |
| `kind` | TEXT NOT NULL | `thm`, `def`, `inductive`, `structure`, `instance`, `axiom`, `opaque`, `unknown` |
| `module` | TEXT | e.g. `Mathlib.Algebra.Group.Defs` |
| `file_path` | TEXT | derived: module with dots → slashes + `.lean` |
| `signature` | TEXT | pretty-printed Lean type (from `_statements.jsonl`); empty if not surfaced |
| `docstring` | TEXT | from `_statements.jsonl`; empty if none |

**Cross-project name collision:** if `Real.add` exists in both `Mathlib_v427`
and `Mathlib_v429`, it gets exactly one row in `nodes` (whichever project
ingested first owns it via `INSERT OR IGNORE`). The schema doesn't currently
support strict per-toolchain isolation — see "known limitations" in the
README if that matters for your use.

### `edges`

| Column | Type | Notes |
|---|---|---|
| `source_id` | INTEGER NOT NULL REFERENCES `nodes(id)` | |
| `target_id` | INTEGER NOT NULL REFERENCES `nodes(id)` | |
| `edge_type` | TEXT NOT NULL | one of: `extends`, `field`, `sig`, `proof`, `def`, `docref` |

PRIMARY KEY `(source_id, target_id, edge_type)` — multiple edges between
the same source and target are allowed only if they have different types.

#### Edge types

| Type | What it means |
|---|---|
| `extends` | Structure A extends structure B — `A.extends B` |
| `field` | A's body projects a field of B — `a.b` access |
| `sig` | B's name appears in A's type signature (hypothesis or conclusion) |
| `proof` | B's name appears in A's proof body |
| `def` | B's name appears in A's definition body (non-proof) |
| `docref` | B's name appears as a `[[Lean name]]` reference in A's docstring |

## NDJSON file format (`ndjson/<project>.ndjson`)

Newline-delimited JSON, one declaration per line.

```json
{
  "name": "Commute.exp_right",
  "decl_type": "thm",
  "module": "Mathlib.Analysis.Normed.Algebra.Exponential",
  "docstring": "",
  "in_degree": 4,
  "is_instance": false,
  "edges": [
    {"target": "NormedSpace.exp", "kind": "sig",
     "binder": "explicit", "position": "conclusion", "role": "fn", "via_proj": false},
    {"target": "Commute",         "kind": "sig",
     "binder": "explicit", "position": "conclusion", "role": "fn", "via_proj": false},
    {"target": "IsTopologicalRing", "kind": "sig",
     "binder": "inst",     "position": "hyp",        "role": "fn", "via_proj": false},
    {"target": "Eq.trans", "kind": "proof"},
    {"target": "of_eq_true", "kind": "proof"}
  ]
}
```

### Node fields

| Field | Type | Notes |
|---|---|---|
| `name` | string | fully-qualified declaration name |
| `decl_type` | string | `thm`, `def`, `structure`, `inductive`, `instance`, ... |
| `module` | string | containing module name |
| `docstring` | string | possibly empty |
| `in_degree` | int | precomputed count of incoming edges across whole graph |
| `is_instance` | bool | whether this is a typeclass instance (named or anonymous) |
| `edges` | array | outgoing edges (see below) |

### Edge object fields

All edges have:

| Field | Type | Notes |
|---|---|---|
| `target` | string | fully-qualified name of the referenced decl |
| `kind` | string | one of `extends`, `field`, `sig`, `proof`, `def`, `docref` |

**Sig edges** additionally have:

| Field | Type | Values |
|---|---|---|
| `binder` | string | `explicit` (default), `implicit`, `strictImplicit`, `inst` (typeclass instance argument) |
| `position` | string | `hyp` (in a hypothesis) or `conclusion` (in the return type / goal) |
| `role` | string | `fn` (function being applied) or `arg` (argument) |
| `via_proj` | bool | whether the target is reached through a structure projection |

Proof / def / field / docref edges have only `target` + `kind`.

## `*_statements.jsonl` file format

Per line:

```json
{
  "name": "Finsupp.support_smul_eq",
  "module": "Mathlib.Data.Finsupp.SMul",
  "decl_type": "theorem",
  "signature": "Finsupp.support_smul_eq.{u_1, u_3, u_6} {α : Type u_1} ... ",
  "docstring": ""
}
```

Used by `ingestion/ingest.py` to populate `signature` and `docstring` on the
corresponding `nodes` rows during ingestion. Not required if you only use the
NDJSON directly (the structural graph is complete without it).
