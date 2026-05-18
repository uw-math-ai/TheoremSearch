#!/bin/bash
#SBATCH --job-name=v2-ingest
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/ingest_v2_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/ingest_v2_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Ingests all extracted .ndjson + .jsonl files into corpus_v2.db.
# Uses sbcast to copy data to node-local SSD (/tmp) for fast I/O,
# then writes the final DB back to gscratch.
#
# Usage:
#   sbatch run_ingest.sh

set -euo pipefail

module load foster/python/miniconda/3.8

WORK_DIR="/gscratch/amath/simku22/TheoremSearch/formalized_graph_v2"
NDJSON_DIR="$WORK_DIR/data/generated/ndjson"
DB_FINAL="$WORK_DIR/data/generated/corpus_v2.db"

# Broadcast input data to node-local SSD for fast reads
LOCAL_DIR="/tmp/ingest_$$"
mkdir -p "$LOCAL_DIR"
echo "Broadcasting NDJSON to local SSD ($LOCAL_DIR)..."
for f in "$NDJSON_DIR"/*.ndjson "$NDJSON_DIR"/*.jsonl; do
    [ ! -f "$f" ] && continue
    sbcast "$f" "$LOCAL_DIR/$(basename "$f")"
done
echo "  $(du -sh "$LOCAL_DIR" | cut -f1) on local SSD"

# Build DB on local SSD (fast writes)
DB_PATH="$LOCAL_DIR/corpus_v2.db"

cd "/gscratch/amath/simku22/TheoremSearch"

echo "=== Ingesting all projects into corpus_v2.db ==="

# Ingest Mathlib first (base layer — all other projects resolve targets here)
if [ -f "$LOCAL_DIR/Mathlib.ndjson" ]; then
    echo "--- Ingesting Mathlib ---"
    python3 -m formalized_graph_v2.ingestion.ingest_ndjson \
        --graph "$LOCAL_DIR/Mathlib.ndjson" \
        --statements "$LOCAL_DIR/Mathlib_statements.jsonl" \
        --project Mathlib \
        --url https://github.com/leanprover-community/mathlib4 \
        --toolchain v4.29.0 \
        --db "$DB_PATH"
fi

# Ingest all other projects (alphabetical order)
for ndjson in "$LOCAL_DIR"/*.ndjson; do
    [ ! -f "$ndjson" ] && continue
    name=$(basename "$ndjson" .ndjson)
    [ "$name" = "Mathlib" ] && continue

    stmts="$LOCAL_DIR/${name}_statements.jsonl"
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

# Copy final DB back to gscratch
echo "Copying DB back to gscratch..."
cp "$DB_PATH" "$DB_FINAL"
rm -rf "$LOCAL_DIR"

echo "=== Ingestion complete ==="
echo "DB: $DB_FINAL"
echo "Size: $(du -sh "$DB_FINAL" | cut -f1)"
