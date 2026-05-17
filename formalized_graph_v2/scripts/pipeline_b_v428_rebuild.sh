#!/bin/bash
#SBATCH --job-name=pB-rebuild
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --array=0-3
#SBATCH --output=/gscratch/amath/simku22/logs/pB_rebuild_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/pB_rebuild_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc
TOOLCHAIN_DIR="$HOME/.elan/toolchains/leanprover--lean4---v4.28.0"
export LIBRARY_PATH="$TOOLCHAIN_DIR/lib:${LIBRARY_PATH:-}"

PROJECTS=(
    "sphere-eversion:SphereEversion"
    "PrimeNumberTheoremAnd:PrimeNumberTheoremAnd"
    "SciLean:SciLean"
    "sphere-packing-math-inc:SpherePacking"
)

ENTRY="${PROJECTS[$SLURM_ARRAY_TASK_ID]}"
PROJECT="${ENTRY%%:*}"
MODULE="${ENTRY##*:}"
PROJ_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT"

echo "=== Pipeline B rebuild: $PROJECT ($MODULE) ==="
cd "$PROJ_DIR"
echo "leanprover/lean4:v4.28.0" > lean-toolchain
rm -rf .lake/build
find .lake/packages -maxdepth 3 -name build -type d -exec rm -rf {} + 2>/dev/null || true

lake build "$MODULE" 2>&1
ls -la ".lake/build/lib/lean/$MODULE.olean" 2>/dev/null && echo "SUCCESS" || echo "FAILED"
