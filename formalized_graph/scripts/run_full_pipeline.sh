#!/bin/bash
#SBATCH --job-name=mathlib-extract
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/pipeline_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/pipeline_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail

export PATH="$HOME/.elan/bin:$PATH"
module load foster/python/miniconda/3.8

WORK_DIR="/gscratch/amath/simku22/TheoremSearch"
MATHLIB_DIR="$WORK_DIR/formalized_graph/data/mathlib/mathlib4"

mkdir -p /gscratch/amath/simku22/logs

python3 -m pip install loguru tqdm --quiet

echo "=== Step 1: lake build ==="
cd "$MATHLIB_DIR"
if [[ ! -f ".lake/build/lib/lean/Mathlib.olean" ]]; then
    lake build
else
    echo "Oleans already present, skipping build."
fi

echo "=== Step 2: Test run (50 files) ==="
cd "$WORK_DIR"
python3 formalized_graph/scripts/ingest_all.py --limit 50

echo "=== Step 3: Rebuild DB ==="
python3 -m formalized_graph.ingestion.rebuild

echo "=== Done. DB at: $WORK_DIR/formalized_graph/data/generated/global_corpus.db ==="
