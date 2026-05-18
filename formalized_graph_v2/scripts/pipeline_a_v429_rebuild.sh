#!/bin/bash
#SBATCH --job-name=pA-rebuild
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --array=0-2
#SBATCH --output=/gscratch/amath/simku22/logs/pA_rebuild_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/pA_rebuild_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Pipeline A: rebuild 3 v4.29.0 projects we haven't extracted yet.
# Reuses existing v4.29.0 lean-graph binary — no new builds needed.

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc
TOOLCHAIN_DIR="$HOME/.elan/toolchains/leanprover--lean4---v4.29.0"
export LIBRARY_PATH="$TOOLCHAIN_DIR/lib:${LIBRARY_PATH:-}"

PROJECTS=(
    "pfr:PFR"
    "Sphere-Packing-Lean:SpherePacking"
    "ClassFieldTheory:ClassFieldTheory"
)

ENTRY="${PROJECTS[$SLURM_ARRAY_TASK_ID]}"
PROJECT="${ENTRY%%:*}"
MODULE="${ENTRY##*:}"
PROJ_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT"

echo "=== Pipeline A task $SLURM_ARRAY_TASK_ID: $PROJECT (module: $MODULE) ==="
echo "Started: $(date)"

cd "$PROJ_DIR"
echo "leanprover/lean4:v4.29.0" > lean-toolchain
rm -rf .lake/build
find .lake/packages -maxdepth 3 -name build -type d -exec rm -rf {} + 2>/dev/null || true

lake build "$MODULE" 2>&1

ls -la ".lake/build/lib/lean/$MODULE.olean" 2>/dev/null && echo "SUCCESS" || echo "FAILED"
echo "Finished: $(date)"
