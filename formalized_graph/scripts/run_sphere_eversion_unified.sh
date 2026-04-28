#!/bin/bash
#SBATCH --job-name=sphere-eversion-unified
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/sphere_eversion_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/sphere_eversion_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Unified graph extraction for sphere-eversion using lean-graph fork.
#
# What this does:
#   1. Clones sphere-eversion (if not already present)
#   2. Wires formalized_graph/lean-graph into sphere-eversion's lakefile
#      (overriding the inherited importGraph, which lacks unified mode)
#   3. Runs `lake build` — downloads Mathlib oleans from the cloud cache
#   4. Runs `lake exe graph --mode unified` — produces DOT + nodes CSV
#   5. Ingests the DOT into a fresh SQLite DB
#
# Output:
#   formalized_graph/data/generated/sphere_eversion_unified.db
#
# Runtime estimate: ~3-4h (Mathlib olean download ~30min, build ~30min,
#                   extraction ~1-2h for the full Mathlib+SphereEversion env)

set -euo pipefail

export PATH="$HOME/.elan/bin:$PATH"
module load foster/python/miniconda/3.8 2>/dev/null || true

# ── Paths ─────────────────────────────────────────────────────────────────────
WORK_DIR="/gscratch/amath/simku22/TheoremSearch"
PROJECT_DIR="$WORK_DIR/formalized_graph/data/formalization_projects/sphere-eversion"
DATA_DIR="$WORK_DIR/formalized_graph/data/generated"
LEAN_GRAPH="$WORK_DIR/formalized_graph/lean-graph"
SCRIPT_DIR="$WORK_DIR/formalized_graph/scripts"

DOT_OUT="$PROJECT_DIR/unified_graph.dot"
NODES_OUT="$PROJECT_DIR/unified_graph_nodes.csv"
DB_OUT="$DATA_DIR/sphere_eversion_unified.db"

mkdir -p /gscratch/amath/simku22/logs
mkdir -p "$DATA_DIR"

echo "=== [$(date)] Step 1: Clone sphere-eversion ==="
if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    git clone --depth=1 https://github.com/leanprover-community/sphere-eversion "$PROJECT_DIR"
else
    echo "Already cloned, pulling latest..."
    git -C "$PROJECT_DIR" pull --ff-only || echo "Pull failed, using existing state"
fi

echo "=== [$(date)] Step 2: Wire lean-graph into lakefile ==="
python3 "$SCRIPT_DIR/setup_unified_extractor.py" "$PROJECT_DIR"

echo "=== [$(date)] Step 3: lake build (downloads Mathlib oleans from cloud cache) ==="
cd "$PROJECT_DIR"

# lake tries the Mathlib cloud cache first; a full build is the fallback.
# LAKE_PKG_CACHE_PATH speeds up repeated runs on gscratch.
export LAKE_PKG_CACHE_PATH="/gscratch/amath/simku22/.lake_cache"
mkdir -p "$LAKE_PKG_CACHE_PATH"

lake build 2>&1 | tail -20

echo "=== [$(date)] Step 4: Run unified graph extraction ==="
# --mode unified: all 6 edge types (proof, sig, extends, field, def, docref)
# --include-lean: captures Init.Prelude, core Lean nodes (congrArg etc.)
# --to SphereEversion: loads the SphereEversion module tree (+ Mathlib transitively)
# Output: unified_graph.dot + unified_graph_nodes.csv (written alongside DOT)
lake exe graph \
    --mode unified \
    --include-lean \
    --to SphereEversion \
    "$DOT_OUT"

echo "=== [$(date)] Step 5: Ingest DOT into SQLite ==="
python3 -m pip install loguru tqdm --quiet

python3 "$SCRIPT_DIR/ingest_unified_dot.py" \
    --dot   "$DOT_OUT" \
    --nodes "$NODES_OUT" \
    --db    "$DB_OUT" \
    --project SphereEversion

echo "=== [$(date)] Done. DB at: $DB_OUT ==="

# Quick sanity check
python3 - <<'PYEOF'
import sqlite3, os
db = os.environ.get("DB_OUT", "")
if not db:
    import glob
    db = glob.glob("/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/generated/sphere_eversion_unified.db")[0]
conn = sqlite3.connect(db)
n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
e = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
print(f"Final: {n:,} nodes, {e:,} edges")
for kind, cnt in conn.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind ORDER BY COUNT(*) DESC"):
    print(f"  {kind:<12} {cnt:>10,}")
PYEOF
