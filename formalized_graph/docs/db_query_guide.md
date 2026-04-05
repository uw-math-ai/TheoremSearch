# TheoremSearch DB Query Guide

Paste this file into an agent session (e.g. Claude Code) to get started querying the mathematical dependency graph.

---

## What this database is

A precision-verified dependency graph of the Lean 4 / Mathlib ecosystem. Every edge represents a real compiler-traced dependency: theorem A's proof uses theorem B. Extracted by hooking into the Lean InfoTree during elaboration.

**File:** `formalized_graph/data/generated/global_corpus.db` (SQLite, ~131 MB)

To open it:
```bash
sqlite3 formalized_graph/data/generated/global_corpus.db
```

Or from Python:
```python
import sqlite3
conn = sqlite3.connect("formalized_graph/data/generated/global_corpus.db")
conn.row_factory = sqlite3.Row
```

---

## Schema

### `projects` — source repositories

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Internal ID |
| `name` | TEXT | Repository name (e.g. `"Mathlib"`) |
| `url` | TEXT | GitHub URL (nullable) |
| `is_mathlib` | BOOLEAN | 1 if this is Mathlib itself |
| `ingested_at` | TIMESTAMP | When ingested |

### `nodes` — theorems, definitions, lemmas, etc.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Internal ID |
| `project_id` | INTEGER FK | Which project this belongs to |
| `full_name` | TEXT UNIQUE | Lean fully-qualified name, e.g. `Real.pi_pos` |
| `kind` | TEXT | Declaration kind: `theorem`, `def`, `lemma`, `inductive`, `instance`, `abbrev`, `opaque`, `axiom`, `unknown` |
| `file_path` | TEXT | Canonical module path, e.g. `Mathlib/Analysis/SpecialFunctions/Trigonometric/Basic.lean` |
| `docstring` | TEXT | Lean docstring (currently empty — not yet extracted) |
| `statement` | TEXT | Type signature (currently empty — not yet extracted) |
| `in_degree` | INTEGER | Always 0 — query edges table directly (see note below) |
| `out_degree` | INTEGER | Always 0 — query edges table directly (see note below) |

> **Note:** `in_degree`/`out_degree` columns are not populated. Compute them live from the `edges` table.

### `edges` — verified dependencies

| Column | Type | Description |
|--------|------|-------------|
| `source_id` | INTEGER FK | The theorem that depends on something |
| `target_id` | INTEGER FK | The thing being depended on |
| `is_implicit` | BOOLEAN | 0 = direct syntactic reference, 1 = implicit/typeclass compiler trace |
| `tactic_context` | TEXT | Always `"compiler_trace"` |

Primary key: `(source_id, target_id)` — one edge per pair, deduplicated.

Indexes: `idx_nodes_name` on `nodes(full_name)`, plus `idx_edges_source` and `idx_edges_target`.

---

## Scale

```sql
SELECT COUNT(*) FROM nodes;   -- ~292,361
SELECT COUNT(*) FROM edges;   -- ~1,447,190
SELECT COUNT(*) FROM projects;
```

---

## Example queries

### What does a theorem directly depend on?

```sql
-- Direct (syntactic) dependencies of Real.pi_pos
SELECT t.full_name, t.kind, t.file_path
FROM nodes s
JOIN edges e ON e.source_id = s.id AND e.is_implicit = 0
JOIN nodes t ON e.target_id = t.id
WHERE s.full_name = 'Real.pi_pos';
-- Expected: Real.pi, Real.two_le_pi, lt_of_lt_of_le
```

### What theorems use a given theorem?

```sql
-- Who depends on Nat.add_comm?
SELECT s.full_name, s.kind, s.file_path
FROM nodes s
JOIN edges e ON e.source_id = s.id
JOIN nodes t ON e.target_id = t.id
WHERE t.full_name = 'Nat.add_comm'
LIMIT 20;
```

### Compute in-degree (how many things use this theorem)

```sql
SELECT t.full_name, COUNT(*) AS in_degree
FROM edges e
JOIN nodes t ON e.target_id = t.id
GROUP BY t.id
ORDER BY in_degree DESC
LIMIT 20;
```

### Compute out-degree (how many things this theorem uses)

```sql
SELECT s.full_name, COUNT(*) AS out_degree
FROM edges e
JOIN nodes s ON e.source_id = s.id
GROUP BY s.id
ORDER BY out_degree DESC
LIMIT 20;
```

### Find all theorems in a file

```sql
SELECT full_name, kind
FROM nodes
WHERE file_path = 'Mathlib/Analysis/SpecialFunctions/Trigonometric/Basic.lean'
ORDER BY full_name;
```

### Find theorems by name prefix

```sql
SELECT full_name, kind, file_path
FROM nodes
WHERE full_name LIKE 'Real.pi%'
ORDER BY full_name;
```

### Breakdown of declaration kinds

```sql
SELECT kind, COUNT(*) AS cnt
FROM nodes
GROUP BY kind
ORDER BY cnt DESC;
```

### Find the most-used theorems (highest in-degree)

```sql
SELECT n.full_name, n.kind, COUNT(*) AS used_by
FROM edges e
JOIN nodes n ON e.target_id = n.id
GROUP BY n.id
ORDER BY used_by DESC
LIMIT 30;
```

### Spot-check a specific theorem's full dependency set (direct + implicit)

```sql
SELECT t.full_name, t.kind, e.is_implicit
FROM nodes s
JOIN edges e ON e.source_id = s.id
JOIN nodes t ON e.target_id = t.id
WHERE s.full_name = 'Algebraic.aleph0_le_cardinalMk_of_charZero'
ORDER BY e.is_implicit, t.full_name;
-- Should return ~10 dependencies
```

### Two-hop dependencies (what does my theorem transitively use?)

```sql
-- One hop: direct deps of X
WITH direct AS (
    SELECT e.target_id
    FROM edges e
    JOIN nodes s ON e.source_id = s.id
    WHERE s.full_name = 'Real.pi_pos'
)
-- Two hops: deps of deps
SELECT DISTINCT n.full_name, n.kind
FROM edges e
JOIN direct d ON e.source_id = d.target_id
JOIN nodes n ON e.target_id = n.id
LIMIT 50;
```

---

## Python snippet to load and explore

```python
import sqlite3

conn = sqlite3.connect("formalized_graph/data/generated/global_corpus.db")
conn.row_factory = sqlite3.Row

# Get direct dependencies of a theorem
def get_deps(name: str, direct_only: bool = True):
    q = """
        SELECT t.full_name, t.kind, e.is_implicit
        FROM nodes s
        JOIN edges e ON e.source_id = s.id
        JOIN nodes t ON e.target_id = t.id
        WHERE s.full_name = ?
    """
    if direct_only:
        q += " AND e.is_implicit = 0"
    return conn.execute(q, (name,)).fetchall()

# Get theorems that use a given theorem
def get_users(name: str, limit: int = 20):
    q = """
        SELECT s.full_name, s.kind
        FROM nodes s
        JOIN edges e ON e.source_id = s.id
        JOIN nodes t ON e.target_id = t.id
        WHERE t.full_name = ?
        LIMIT ?
    """
    return conn.execute(q, (name, limit)).fetchall()

for row in get_deps("Real.pi_pos"):
    print(dict(row))
```

---

## Notes for agents

- `full_name` is the unique identifier — use it as your primary lookup key
- `kind` values: `theorem`, `def`, `lemma`, `inductive`, `instance`, `abbrev`, `opaque`, `axiom`, `unknown`
- `is_implicit = 0` edges are direct syntactic uses (higher signal); `is_implicit = 1` are typeclass/instance traces
- The graph is a DAG (by construction — Lean forbids circular dependencies)
- ~6.5% of Mathlib declarations are missing (macro-generated names, private decls, files that timed out during extraction)
- `docstring` and `statement` columns are empty in this version — planned for a future extraction pass
