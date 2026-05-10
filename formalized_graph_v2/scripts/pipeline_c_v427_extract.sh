#!/bin/bash
#SBATCH --job-name=pC-extract
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/pC_extract_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/pC_extract_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export ELAN_TOOLCHAIN="leanprover/lean4:v4.27.0"

PROJECT="formal-conjectures"
MODULE="FormalConjecturesForMathlib"

BIN="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4_v427/.lake/packages/lean-graph/.lake/build/bin"
PROJ_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT"
PROJ_LIB="$PROJ_DIR/.lake/build/lib/lean"
OUT_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/generated/ndjson"

mkdir -p "$OUT_DIR"
[ -d "$PROJ_LIB" ] || { echo "ERROR: No oleans at $PROJ_LIB"; exit 1; }

PATHS="$PROJ_LIB"
for pkg in "$PROJ_DIR"/.lake/packages/*/.lake/build/lib/lean; do
    [ -d "$pkg" ] && PATHS="$PATHS:$pkg"
done

echo "=== Pipeline C extract: $PROJECT ($MODULE) ==="
LEAN_PATH="$PATHS" "$BIN/graph" --mode unified --to "$MODULE" "$OUT_DIR/${PROJECT}.ndjson" 2>&1 || true
LEAN_PATH="$PATHS" "$BIN/export_statements" -- --to "$MODULE" --pretty --output "$OUT_DIR/${PROJECT}_statements.jsonl" 2>&1 || true
wc -l "$OUT_DIR/${PROJECT}.ndjson" 2>/dev/null || echo "no output"
