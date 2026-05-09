#!/bin/bash
#SBATCH --job-name=v2-extract
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --array=0-10
#SBATCH --output=/gscratch/amath/simku22/logs/extract_v2_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/extract_v2_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Extracts all 11 v4.29.0 community projects using pre-built lean-graph
# binaries from the Mathlib build (bypasses importGraph conflict).
#
# Usage: sbatch run_extract_projects.sh

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export ELAN_TOOLCHAIN="leanprover/lean4:v4.29.0"

# Project directory name → module name mapping
PROJECTS=(
    "add-combi:AddCombi"
    "apap:APAP"
    "brownian-motion:BrownianMotion"
    "cam-combi:LeanCamCombi"
    "chandra-furst-lipton:ChandraFurstLipton"
    "combinatorial-games:CombinatorialGames"
    "forbidden-matrix:ForbiddenMatrix"
    "gibbs-measure:GibbsMeasure"
    "misc-yd:MiscYD"
    "PersistentDecomp:PersistentDecomp"
    "toric:Toric"
)

ENTRY="${PROJECTS[$SLURM_ARRAY_TASK_ID]}"
PROJECT="${ENTRY%%:*}"
MODULE="${ENTRY##*:}"

BIN="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4/.lake/packages/lean-graph/.lake/build/bin"
MATHLIB_LIB="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4/.lake/build/lib"
PROJ_LIB="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT/.lake/build/lib/lean"
OUT_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/generated/ndjson"

mkdir -p "$OUT_DIR"

echo "=== Task $SLURM_ARRAY_TASK_ID: Extracting $PROJECT (module: $MODULE) ==="

# Check project oleans exist
if [ ! -d "$PROJ_LIB" ]; then
    echo "ERROR: No oleans at $PROJ_LIB — was the project built?"
    exit 1
fi

echo "--- Graph ---"
LEAN_PATH="$PROJ_LIB:$MATHLIB_LIB" "$BIN/graph" --mode unified --to "$MODULE" "$OUT_DIR/${PROJECT}.ndjson" 2>&1 || true

echo "--- Statements ---"
LEAN_PATH="$PROJ_LIB:$MATHLIB_LIB" "$BIN/export_statements" -- --to "$MODULE" --pretty --output "$OUT_DIR/${PROJECT}_statements.jsonl" 2>&1 || true

echo "=== Result ==="
wc -l "$OUT_DIR/${PROJECT}.ndjson" 2>/dev/null || echo "No graph output"
wc -l "$OUT_DIR/${PROJECT}_statements.jsonl" 2>/dev/null || echo "No statement output"
