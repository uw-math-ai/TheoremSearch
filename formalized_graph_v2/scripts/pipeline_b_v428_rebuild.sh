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

# Redirect all build outputs to node-local SSD to avoid NFS olean loss on gscratch.
# Covers both the project's own .lake/build and every package's .lake/build so that
# dependency oleans (Aesop, Batteries, etc.) are written to SSD too.
LOCAL_BASE="/tmp/proj-${PROJECT}-${SLURM_JOB_ID:-$$}"
mkdir -p "$LOCAL_BASE/build"

# Wipe stale build dirs and replace with SSD symlinks
rm -rf .lake/build
ln -sfn "$LOCAL_BASE/build" .lake/build

find .lake/packages -maxdepth 1 -mindepth 1 -type d 2>/dev/null | while read -r pkg_dir; do
    pkg_name=$(basename "$pkg_dir")
    mkdir -p "$LOCAL_BASE/packages/$pkg_name"
    mkdir -p "$pkg_dir/.lake"
    rm -rf "$pkg_dir/.lake/build"
    ln -sfn "$LOCAL_BASE/packages/$pkg_name" "$pkg_dir/.lake/build"
done

trap "echo '--- Syncing project build from SSD to gscratch ---'; \
      rm -f '$PROJ_DIR/.lake/build'; \
      [ -d '$LOCAL_BASE/build' ] && mv '$LOCAL_BASE/build' '$PROJ_DIR/.lake/build' || true; \
      find '$PROJ_DIR/.lake/packages' -maxdepth 1 -mindepth 1 -type d 2>/dev/null | while read -r pkg_dir; do \
          pkg_name=\$(basename \"\$pkg_dir\"); \
          rm -f \"\$pkg_dir/.lake/build\"; \
          [ -d '$LOCAL_BASE/packages/'\"\$pkg_name\" ] && mv '$LOCAL_BASE/packages/'\"\$pkg_name\" \"\$pkg_dir/.lake/build\" || true; \
      done" EXIT

lake build "$MODULE" 2>&1
ls -la ".lake/build/lib/lean/$MODULE.olean" 2>/dev/null && echo "SUCCESS" || echo "FAILED"
