#!/bin/bash
#SBATCH --job-name=v2-ingest
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/ingest_v2_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/ingest_v2_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Ingests all extracted .ndjson + .jsonl files into corpus_v2.db.
# Run this AFTER all extraction jobs have completed.
#
# Usage:
#   sbatch run_ingest.sh

set -euo pipefail

module load foster/python/miniconda/3.8

WORK_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2"
NDJSON_DIR="$WORK_DIR/data/generated/ndjson"
DB_PATH="$WORK_DIR/data/generated/corpus_v2.db"

cd "/gscratch/amath/simku22/TheoremSearch"

# Remove old DB to do a clean rebuild
rm -f "$DB_PATH"

echo "=== Ingesting all projects into corpus_v2.db ==="

# Ingest Mathlib first (base layer — all other projects resolve targets here)
if [ -f "$NDJSON_DIR/Mathlib.ndjson" ]; then
    echo "--- Ingesting Mathlib ---"
    python3 -m formalized_graph_v2.ingestion.ingest_ndjson \
        --graph "$NDJSON_DIR/Mathlib.ndjson" \
        --statements "$NDJSON_DIR/Mathlib_statements.jsonl" \
        --project Mathlib \
        --url https://github.com/leanprover-community/mathlib4 \
        --toolchain v4.29.0 \
        --db "$DB_PATH"
fi

# Ingest all other projects (alphabetical order)
for ndjson in "$NDJSON_DIR"/*.ndjson; do
    name=$(basename "$ndjson" .ndjson)
    [ "$name" = "Mathlib" ] && continue

    stmts="$NDJSON_DIR/${name}_statements.jsonl"
    stmts_flag=""
    [ -f "$stmts" ] && stmts_flag="--statements $stmts"

    echo "--- Ingesting $name ---"
    python3 -m formalized_graph_v2.ingestion.ingest_ndjson \
        --graph "$ndjson" \
        $stmts_flag \
        --project "$name" \
        --toolchain v4.29.0 \
        --db "$DB_PATH"
done

echo "=== Ingestion complete ==="
echo "DB: $DB_PATH"
echo "Size: $(du -sh "$DB_PATH" | cut -f1)"
