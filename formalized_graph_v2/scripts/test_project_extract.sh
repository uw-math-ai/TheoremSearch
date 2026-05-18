#!/bin/bash
#SBATCH --job-name=test-proj
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/test_proj_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/test_proj_%j.err

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
export LEAN_CC=/usr/bin/gcc
export LIBRARY_PATH="$HOME/.elan/toolchains/leanprover--lean4---v4.29.0/lib"

PROJECT="${1:?Usage: sbatch test_project_extract.sh <project-name> <module-name>}"
MODULE="${2:?Usage: sbatch test_project_extract.sh <project-name> <module-name>}"

PROJ_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph/data/formalization_projects/$PROJECT"
OUT_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/generated/ndjson"
mkdir -p "$OUT_DIR"

cd "$PROJ_DIR"

echo "=== Extracting $PROJECT (module: $MODULE) ==="

# Add lean-graph dependency if not already in lakefile
if ! grep -q "lean-graph" lakefile.toml 2>/dev/null && ! grep -q "lean-graph" lakefile.lean 2>/dev/null; then
    echo "--- Adding lean-graph dependency ---"
    if [ -f lakefile.toml ]; then
        echo -e '\n[[require]]\nname = "lean-graph"\ngit = "https://github.com/aurasoph/lean-graph"\nrev = "main"' >> lakefile.toml
    else
        echo 'require «lean-graph» from git "https://github.com/aurasoph/lean-graph" @ "main"' >> lakefile.lean
    fi
fi

# Update manifest — tolerate cache download failures (HYAK OpenSSL 3.0.8
# can't connect to Mathlib cache server; the manifest is written before
# the post-update hook fires, so lean-graph is still registered)
echo "--- Updating manifest ---"
lake update lean-graph 2>&1 || echo "  (lake update exited non-zero — expected if Mathlib cache hook failed)"

echo "--- Building graph executable ---"
lake build graph 2>&1

echo "--- Extracting graph ---"
lake exe graph --mode unified --to "$MODULE" "$OUT_DIR/${PROJECT}.ndjson" 2>&1 || true

echo "--- Extracting statements ---"
lake exe export_statements -- --to "$MODULE" --pretty --output "$OUT_DIR/${PROJECT}_statements.jsonl" 2>&1 || true

echo "=== Result ==="
wc -l "$OUT_DIR/${PROJECT}.ndjson" 2>/dev/null || echo "No graph output"
wc -l "$OUT_DIR/${PROJECT}_statements.jsonl" 2>/dev/null || echo "No statement output"
