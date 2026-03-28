# Agent Context: formalized_graph Stage 1 Pipeline

Paste this at the start of a new Claude Code session to restore context.

---

## What this project is

A precision-verified mathematical dependency graph of the Lean 4 / Mathlib ecosystem, stored in a SQLite database (`formalized_graph/data/generated/global_corpus.db`). The Lean compiler probe (`ExtractData.lean`) hooks into the InfoTree to extract exact theorem dependencies. `rebuild.py` turns the raw `.ast.json` artifacts into a clean graph with geometric range containment.

---

## Current focus: Stage 1 (Ground Truth Extraction)

We are fixing the extraction pipeline and running a full Mathlib rebuild on a SLURM cluster.

### Two bugs fixed (committed 2026-03-26)

**1. `ExtractData.lean` — defEndPos precision**
`selectionRange.endPos` (name span only) → `range.endPos` (full declaration body end).
Needed so rebuild.py has exact proof-block boundaries per theorem.

**2. `rebuild.py` — interval misattribution**
Old: built intervals only from premises where `defPath == current_file`. Theorems never referenced within their own file got no interval, and their edges were silently credited to the preceding definition.
New: global pre-scan of ALL ASTs using `(defPos.line, defEndPos.line)` directly.
Verified fix: Pi.algHom_comp now gets its 7 correct edges instead of 0.

### Known unfixed issues
- `out_degree`/`in_degree` columns are all 0 — query edges table directly
- All `kind` fields are `"unknown"` — not yet classified
- `formalized_graph/data` is a broken symlink on non-Mac machines (see cluster section)
- ~12% of Mathlib nodes missing (macro-generated names, private decls, timeouts)

---

## Database schema

```
projects  (id, name, url, is_mathlib)
nodes     (id, project_id, full_name, kind, file_path, docstring, statement, in_degree, out_degree)
edges     (source_id, target_id, is_implicit, tactic_context)
          is_implicit: 0 = direct syntactic, 1 = implicit compiler trace
```

**Useful QA query:**
```sql
SELECT t.full_name, t.file_path
FROM nodes s
JOIN edges e ON e.source_id = s.id AND e.is_implicit = 0
JOIN nodes t ON e.target_id = t.id
WHERE s.full_name = 'Real.pi_pos';
-- Expected: Real.pi, Real.two_le_pi, lt_of_lt_of_le (3 edges, ground truth verified)
```

---

## Cluster extraction (HYAK/SLURM)

**Cluster**: klone.hyak.uw.edu | account=amath | partition=cpu-g2
**Working dir on cluster**: `/gscratch/amath/simku22/TheoremSearch`

### Gotchas (hit these already)
1. `formalized_graph/data` clones as a broken symlink — fix with:
   `rm formalized_graph/data && mkdir -p formalized_graph/data/mathlib formalized_graph/data/generated`
2. Home directory quota exceeded during `lake build` — always work from gscratch
3. Always run: `module load coenv/python/3.11.9`
4. Always run: `export PATH="$HOME/.elan/bin:$PATH"`

### Full sequence on a fresh node
```bash
salloc -p cpu-g2 --account=amath --time=4:00:00 --mem=200G --cpus-per-task=64 --nodes=1
export PATH="$HOME/.elan/bin:$PATH"
module load coenv/python/3.11.9
mv ~/TheoremSearch /gscratch/amath/simku22/   # if not already there
cd /gscratch/amath/simku22/TheoremSearch/formalized_graph/data/mathlib/mathlib4
lake build

# Test run first
cd /gscratch/amath/simku22/TheoremSearch
python3 formalized_graph/scripts/ingest_all.py --limit 50
python3 -m formalized_graph.ingestion.rebuild

# Full array job
sbatch --partition=cpu-g2 --account=amath --array=0-99%14 \
  --cpus-per-task=4 --mem=16G --time=02:00:00 \
  --wrap='export PATH="$HOME/.elan/bin:$PATH" && module load coenv/python/3.11.9 && cd /gscratch/amath/simku22/TheoremSearch && python3 formalized_graph/scripts/ingest_all.py --total-tasks 100'

# After all tasks finish
python3 -m formalized_graph.ingestion.rebuild
```

### scp DB back locally
```bash
scp simku22@klone.hyak.uw.edu:/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/generated/global_corpus.db \
    "formalized_graph/data/generated/global_corpus.db"
```

---

## Key files

| File | Purpose |
|------|---------|
| `formalized_graph/lean/ExtractData.lean` | Lean compiler probe (InfoTree traversal) |
| `formalized_graph/ingestion/rebuild.py` | Rebuilds nodes + edges from .ast.json files |
| `formalized_graph/ingestion/factory.py` | Parallel extraction orchestrator |
| `formalized_graph/scripts/ingest_all.py` | Entry point, supports --limit, --total-tasks, --task-id |
| `formalized_graph/scripts/cluster_init.sh` | One-shot cluster setup script |
| `formalized_graph/data/generated/global_corpus.db` | The SQLite database |

---

## Next after the rebuild
- Verify edge counts and spot-check known theorems (Pi.algHom_comp, Real.pi_pos)
- Fix the broken symlink in the repo permanently
- RDS migration (AWS PostgreSQL) for team access — `database.py` currently SQLite only
