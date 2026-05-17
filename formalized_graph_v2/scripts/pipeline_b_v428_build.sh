#!/bin/bash
#SBATCH --job-name=pB-build
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/pB_build_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/pB_build_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Pipeline B: build Mathlib @ 8f9d9cff6bd7 + lean-graph @ lean-v4.28 branch
# under v4.28.0 toolchain. Workspace: mathlib4_v428/

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc

# Install toolchain; force-reinstall if Widget oleans are missing (past corruption seen on HYAK).
WIDGET_DIR="$HOME/.elan/toolchains/leanprover--lean4---v4.28.0/lib/lean/Lean/Widget"
if [ ! -f "$WIDGET_DIR/Types.olean" ]; then
    echo "--- v4.28.0 toolchain corrupt or missing — reinstalling ---"
    elan toolchain uninstall leanprover/lean4:v4.28.0 2>/dev/null || true
fi
elan toolchain install leanprover/lean4:v4.28.0 || true

TOOLCHAIN_DIR="$HOME/.elan/toolchains/leanprover--lean4---v4.28.0"
export LIBRARY_PATH="$TOOLCHAIN_DIR/lib:${LIBRARY_PATH:-}"

WORK="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4_v428"
MATHLIB_REV="8f9d9cff6bd7"
LEAN_GRAPH_BRANCH="lean-v4.28"

if [ ! -d "$WORK" ]; then
    echo "--- Cloning Mathlib at $MATHLIB_REV ---"
    git clone https://github.com/leanprover-community/mathlib4 "$WORK"
    cd "$WORK"
    git checkout "$MATHLIB_REV"
else
    echo "--- Workspace already exists at $WORK ---"
    cd "$WORK"
fi

echo "leanprover/lean4:v4.28.0" > lean-toolchain

# Add lean-graph dependency if not already present.
if ! grep -q "lean-graph" lakefile.lean 2>/dev/null && ! grep -q "lean-graph" lakefile.toml 2>/dev/null; then
    if [ -f lakefile.lean ]; then
        echo "--- Adding lean-graph @ $LEAN_GRAPH_BRANCH to lakefile.lean ---"
        cat >> lakefile.lean <<EOF

require «lean-graph» from git "https://github.com/aurasoph/lean-graph" @ "$LEAN_GRAPH_BRANCH"
EOF
    elif [ -f lakefile.toml ]; then
        echo "--- Adding lean-graph @ $LEAN_GRAPH_BRANCH to lakefile.toml ---"
        cat >> lakefile.toml <<EOF

[[require]]
name = "lean-graph"
git = "https://github.com/aurasoph/lean-graph"
rev = "$LEAN_GRAPH_BRANCH"
EOF
    fi
fi

# lean-graph ships its own ImportGraph library. Keeping Mathlib's importGraph require alongside
# it causes Lake to route ImportGraph.* to the wrong package, making lean-graph's Export/Graph/
# Tools modules unreachable. Remove importGraph so lean-graph's ImportGraph is the sole provider.
# Mathlib's code only imports ImportGraph.{Imports,RequiredModules,Meta,Lean.Name}, all present
# in lean-graph's ImportGraph tree.
if [ -f lakefile.lean ] && grep -q '"importGraph"' lakefile.lean; then
    echo "--- Removing importGraph from lakefile (lean-graph ships its own ImportGraph) ---"
    sed -i '/require.*"importGraph"/d' lakefile.lean
fi

# Redirect .lake/build to node-local NVMe SSD to avoid slow gscratch I/O during compilation.
LOCAL_BUILD="/tmp/mathlib-v428-${SLURM_JOB_ID:-$$}"
rm -rf "$WORK/.lake/build"
mkdir -p "$LOCAL_BUILD"
ln -sfn "$LOCAL_BUILD" "$WORK/.lake/build"
trap "echo '--- Syncing .lake/build from SSD to gscratch ---'; rm -f '$WORK/.lake/build'; [ -d '$LOCAL_BUILD' ] && mv '$LOCAL_BUILD' '$WORK/.lake/build' || true" EXIT

echo "--- lake update lean-graph (cache hook may fail on HYAK; tolerated) ---"
lake update lean-graph 2>&1 || echo "  (lake update exited non-zero — expected if cache hook failed)"

# Mathlib.Tactic.Linter.FindDeprecations uses `parseImports` which was added to Lean core
# after v4.28; stub it out so lake build doesn't abort on this linter-only module.
if [ -f Mathlib/Tactic/Linter/FindDeprecations.lean ]; then
    echo "--- Stubbing FindDeprecations.lean (parseImports absent in v4.28) ---"
    echo "-- stubbed: parseImports not available in Lean v4.28.0" > Mathlib/Tactic/Linter/FindDeprecations.lean
fi

echo "--- Building Mathlib + lean-graph (long) ---"
lake build Mathlib graph export_statements 2>&1

echo "=== Result ==="
ls -la .lake/packages/lean-graph/.lake/build/bin/graph 2>/dev/null && echo "lean-graph: OK" || echo "lean-graph: MISSING"
ls -la .lake/build/lib/lean/Mathlib.olean 2>/dev/null && echo "Mathlib: OK" || echo "Mathlib: MISSING"
