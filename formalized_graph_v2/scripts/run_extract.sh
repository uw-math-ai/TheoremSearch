#!/bin/bash
#SBATCH --job-name=lean-extract
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
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

# Step 1: Extract dependency graph
echo "--- Step 1: lean-graph unified extraction ---"
lake exe graph --mode unified --to "$MODULE" "$OUT_DIR/${PROJECT_NAME}.ndjson" 2>&1

echo "--- Step 2: export_statements ---"
lake env lean --run "$WORK_DIR/lean-graph/MainExportStatements.lean" -- \
    --to "$MODULE" --pretty --output "$OUT_DIR/${PROJECT_NAME}_statements.jsonl" 2>&1

echo "=== $PROJECT_NAME extraction complete ==="
echo "Graph: $(wc -l < "$OUT_DIR/${PROJECT_NAME}.ndjson") declarations"
echo "Statements: $(wc -l < "$OUT_DIR/${PROJECT_NAME}_statements.jsonl") signatures"
