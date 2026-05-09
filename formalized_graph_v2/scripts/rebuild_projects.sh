#!/bin/bash
#SBATCH --job-name=v2-rebuild
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --array=0-9
#SBATCH --output=/gscratch/amath/simku22/logs/rebuild_v2_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/rebuild_v2_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Rebuild 10 community projects with v4.29.0 so their oleans are
# compatible with the pre-built lean-graph binary used for extraction.
# Validated approach: APAP rebuilt successfully in ~1hr interactively.
# 16 cpus/64G per task; 8hr time limit gives generous slack.

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc
TOOLCHAIN_DIR="$HOME/.elan/toolchains/leanprover--lean4---v4.29.0"
export LIBRARY_PATH="$TOOLCHAIN_DIR/lib:${LIBRARY_PATH:-}"

PROJECTS=(
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

PROJ_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT"

echo "=== Task $SLURM_ARRAY_TASK_ID: Rebuilding $PROJECT (module: $MODULE) ==="
echo "Started: $(date)"
echo "CPUs: $SLURM_CPUS_PER_TASK, Mem: ${SLURM_MEM_PER_NODE:-?}MB"

cd "$PROJ_DIR"

# Pin toolchain to match our lean-graph binary
echo "leanprover/lean4:v4.29.0" > lean-toolchain

# Wipe stale build artifacts (built with older toolchain, incompatible headers)
echo "--- Clearing stale .lake/build directories ---"
rm -rf .lake/build
find .lake/packages -maxdepth 3 -name build -type d -exec rm -rf {} + 2>/dev/null || true

echo "--- Building $MODULE (rebuilds Mathlib too, expect 30-60min) ---"
lake build "$MODULE" 2>&1

echo "=== Result ==="
ls -la ".lake/build/lib/lean/$MODULE.olean" 2>/dev/null && echo "SUCCESS" || echo "FAILED: no olean produced"
echo "Finished: $(date)"
