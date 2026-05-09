#!/bin/bash
# Extract a project using the pre-built lean-graph binary from Mathlib.
# Avoids adding lean-graph as a dependency (which conflicts with importGraph).
#
# Usage: bash run_extract_direct.sh <project-name> <module-name>
# Example: bash run_extract_direct.sh add-combi AddCombi

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"

PROJECT="${1:?Usage: bash run_extract_direct.sh <project-name> <module-name>}"
MODULE="${2:?Usage: bash run_extract_direct.sh <project-name> <module-name>}"

BIN="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4/.lake/packages/lean-graph/.lake/build/bin"
MATHLIB_LIB="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4/.lake/build/lib"
PROJ_LIB="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT/.lake/build/lib"
OUT_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/generated/ndjson"

mkdir -p "$OUT_DIR"

echo "=== Extracting $PROJECT (module: $MODULE) ==="

echo "--- Graph ---"
LEAN_PATH="$PROJ_LIB:$MATHLIB_LIB" "$BIN/graph" --mode unified --to "$MODULE" "$OUT_DIR/${PROJECT}.ndjson" 2>&1 || true

echo "--- Statements ---"
LEAN_PATH="$PROJ_LIB:$MATHLIB_LIB" "$BIN/export_statements" -- --to "$MODULE" --pretty --output "$OUT_DIR/${PROJECT}_statements.jsonl" 2>&1 || true

echo "=== Result ==="
wc -l "$OUT_DIR/${PROJECT}.ndjson" 2>/dev/null || echo "No graph output"
wc -l "$OUT_DIR/${PROJECT}_statements.jsonl" 2>/dev/null || echo "No statement output"
