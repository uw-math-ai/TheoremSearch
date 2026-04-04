#!/bin/bash
#SBATCH --job-name=mathlib-rebuild
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/rebuild_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/rebuild_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail

module load foster/python/miniconda/3.8

WORK_DIR="/gscratch/amath/simku22/TheoremSearch"

python3 -m pip install loguru tqdm --quiet

echo "=== Rebuilding DB ==="
cd "$WORK_DIR"
python3 -m formalized_graph.ingestion.rebuild

echo "=== Done. DB at: $WORK_DIR/formalized_graph/data/generated/global_corpus.db ==="
