#!/bin/bash
#SBATCH --job-name=lean-extract
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/extract_v2_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/extract_v2_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Extracts dependency graph + statements for a single project.
#
# Usage:
#   sbatch run_extract.sh mathlib
#   sbatch run_extract.sh pfr
#
# The project must already be built (lake build completed).
# lean-graph must be built as a dependency in the project.

set -euo pipefail

export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc
LEAN_TOOLCHAIN="$HOME/.elan/toolchains/leanprover--lean4---v4.29.0"
export LIBRARY_PATH="$LEAN_TOOLCHAIN/lib:${LIBRARY_PATH:-}"

PROJECT="${1:?Usage: sbatch run_extract.sh <project-name>}"
WORK_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2"
OUT_DIR="$WORK_DIR/data/generated/ndjson"

mkdir -p "$OUT_DIR" /gscratch/amath/simku22/logs

# Resolve project directory and module name
if [ "$PROJECT" = "mathlib" ] || [ "$PROJECT" = "Mathlib" ]; then
    PROJECT_DIR="$WORK_DIR/data/mathlib4"
    MODULE="Mathlib"
    PROJECT_NAME="Mathlib"
else
    PROJECT_DIR="$WORK_DIR/data/projects/$PROJECT"
    # Derive module name from project's lakefile (first lean_lib name)
    # Fall back to capitalized project name
    MODULE="${2:-$PROJECT}"
    PROJECT_NAME="$PROJECT"
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: Project directory not found: $PROJECT_DIR"
    exit 1
fi

cd "$PROJECT_DIR"

echo "=== Extracting $PROJECT_NAME ==="
echo "Project dir: $PROJECT_DIR"
echo "Module: $MODULE"
echo "Output: $OUT_DIR/${PROJECT_NAME}.ndjson"

# Build the project + graph executable with system gcc (HYAK's GLIBC 2.28
# is too old for Lean v4.29.0's bundled clang). Skips already-built modules.
echo "--- Building $MODULE + graph executable ---"
lake build "$MODULE" 2>&1
lake build graph 2>&1

# Step 1: Extract dependency graph
echo "--- Step 1: lean-graph unified extraction ---"
lake exe graph --mode unified --to "$MODULE" "$OUT_DIR/${PROJECT_NAME}.ndjson" 2>&1

echo "--- Step 2: export_statements ---"
lake exe export_statements -- --to "$MODULE" --pretty \
    --output "$OUT_DIR/${PROJECT_NAME}_statements.jsonl" 2>&1

echo "=== $PROJECT_NAME extraction complete ==="
echo "Graph: $(wc -l < "$OUT_DIR/${PROJECT_NAME}.ndjson") declarations"
echo "Statements: $(wc -l < "$OUT_DIR/${PROJECT_NAME}_statements.jsonl") signatures"
