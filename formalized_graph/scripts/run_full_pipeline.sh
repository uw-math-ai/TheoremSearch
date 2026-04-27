#!/bin/bash
#SBATCH --job-name=mathlib-extract
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --array=0-99%50
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/pipeline_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/pipeline_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail

export PATH="$HOME/.elan/bin:$PATH"
module load foster/python/miniconda/3.8

WORK_DIR="/gscratch/amath/simku22/TheoremSearch"
MATHLIB_DIR="$WORK_DIR/formalized_graph/data/mathlib/mathlib4"

mkdir -p /gscratch/amath/simku22/logs

python3 -m pip install loguru tqdm --quiet

echo "=== Step 1: lake build (task $SLURM_ARRAY_TASK_ID) ==="
cd "$MATHLIB_DIR"
if [[ ! -f ".lake/build/lib/lean/Mathlib.olean" ]]; then
    lake build
else
    echo "Oleans already present, skipping build."
fi

echo "=== Step 2: Extract (task $SLURM_ARRAY_TASK_ID / 100) ==="
cd "$WORK_DIR"
python3 formalized_graph/scripts/ingest_all.py --total-tasks 100

echo "=== Task $SLURM_ARRAY_TASK_ID done ==="
