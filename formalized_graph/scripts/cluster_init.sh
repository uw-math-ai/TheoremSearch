#!/bin/bash
# Run once on a fresh cluster node to install elan/lean/lake and clone the repo.
# Usage: bash cluster_init.sh
set -euo pipefail

REPO_URL="https://github.com/uw-math-ai/TheoremSearch.git"
REPO_DIR="$HOME/TheoremSearch"
MATHLIB_DIR="$REPO_DIR/formalized_graph/data/mathlib/mathlib4"

# 1. Install elan (Lean version manager, includes lake)
if ! command -v elan &>/dev/null; then
    echo "=== Installing elan ==="
    curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
        | sh -s -- -y --no-modify-path
fi
export PATH="$HOME/.elan/bin:$PATH"
echo "lake: $(lake --version)"

# 2. Clone TheoremSearch repo
if [[ ! -d "$REPO_DIR/.git" ]]; then
    echo "=== Cloning TheoremSearch ==="
    git clone "$REPO_URL" "$REPO_DIR"
else
    echo "Repo already present, pulling latest..."
    git -C "$REPO_DIR" pull
fi

# 3. Clone mathlib4 and install its pinned Lean toolchain
if [[ ! -d "$MATHLIB_DIR/.git" ]]; then
    echo "=== Cloning mathlib4 ==="
    mkdir -p "$(dirname "$MATHLIB_DIR")"
    git clone https://github.com/leanprover-community/mathlib4.git "$MATHLIB_DIR"
fi

echo "=== Installing Lean toolchain pinned by mathlib4 ==="
elan toolchain install "$(cat "$MATHLIB_DIR/lean-toolchain")"

# 4. Python deps
echo "=== Installing Python dependencies ==="
pip install loguru tqdm --quiet

echo ""
echo "=== Setup complete ==="
echo "Next: cd $MATHLIB_DIR && lake build"
echo "Then: cd $REPO_DIR && sbatch --array=0-99 --wrap='python3 formalized_graph/scripts/ingest_all.py --total-tasks 100'"
