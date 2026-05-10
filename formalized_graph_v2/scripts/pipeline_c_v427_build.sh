#!/bin/bash
#SBATCH --job-name=pC-build
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/pC_build_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/pC_build_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Pipeline C: build Mathlib @ a3a10db0e9d6 + lean-graph @ lean-v4.27 branch
# under v4.27.0 toolchain. Workspace: mathlib4_v427/

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc
TOOLCHAIN_DIR="$HOME/.elan/toolchains/leanprover--lean4---v4.27.0"
export LIBRARY_PATH="$TOOLCHAIN_DIR/lib:${LIBRARY_PATH:-}"

WORK="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4_v427"
MATHLIB_REV="a3a10db0e9d6"
LEAN_GRAPH_BRANCH="lean-v4.27"

if [ ! -d "$WORK" ]; then
    echo "--- Cloning Mathlib at $MATHLIB_REV ---"
    git clone https://github.com/leanprover-community/mathlib4 "$WORK"
    cd "$WORK"
    git checkout "$MATHLIB_REV"
else
    echo "--- Workspace already exists at $WORK ---"
    cd "$WORK"
fi

echo "leanprover/lean4:v4.27.0" > lean-toolchain

if ! grep -q "lean-graph" lakefile.lean 2>/dev/null && ! grep -q "lean-graph" lakefile.toml 2>/dev/null; then
    if [ -f lakefile.lean ]; then
        cat >> lakefile.lean <<EOF

require «lean-graph» from git "https://github.com/aurasoph/lean-graph" @ "$LEAN_GRAPH_BRANCH"
EOF
    elif [ -f lakefile.toml ]; then
        cat >> lakefile.toml <<EOF

[[require]]
name = "lean-graph"
git = "https://github.com/aurasoph/lean-graph"
rev = "$LEAN_GRAPH_BRANCH"
EOF
    fi
fi

echo "--- lake update lean-graph ---"
lake update lean-graph 2>&1 || echo "  (lake update exited non-zero — expected if cache hook failed)"

echo "--- Building Mathlib + lean-graph (long) ---"
lake build Mathlib graph export_statements 2>&1

echo "=== Result ==="
ls -la .lake/packages/lean-graph/.lake/build/bin/graph 2>/dev/null && echo "lean-graph: OK" || echo "lean-graph: MISSING"
ls -la .lake/build/lib/lean/Mathlib.olean 2>/dev/null && echo "Mathlib: OK" || echo "Mathlib: MISSING"
