#!/bin/bash
#SBATCH --job-name=mathlib-retry
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --array=0-9
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/retry_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/retry_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

# Pass 2: re-run files that timed out or errored in the main array job.
# Uses 2 workers (vs 4) and 3600s timeout (vs 600s) since these are the
# heaviest files. More RAM per worker reduces swap pressure.

set -euo pipefail

export PATH="$HOME/.elan/bin:$PATH"
module load foster/python/miniconda/3.8

WORK_DIR="/gscratch/amath/simku22/TheoremSearch"

mkdir -p /gscratch/amath/simku22/logs

python3 -m pip install loguru tqdm --quiet

echo "=== Retry pass (task $SLURM_ARRAY_TASK_ID / 10, timeout=3600s) ==="
cd "$WORK_DIR"
python3 formalized_graph/scripts/ingest_all.py --retry --timeout 3600 --total-tasks 10

echo "=== Task $SLURM_ARRAY_TASK_ID done ==="
