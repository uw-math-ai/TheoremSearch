#!/bin/bash
#SBATCH --job-name=lean-build
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --array=0-31%8
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/build_%A_%a.out
#SBATCH --error=/gscratch/amath/simku22/logs/build_%A_%a.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail

export PATH="$HOME/.elan/bin:$PATH"

WORK_DIR="/gscratch/amath/simku22/TheoremSearch"
PROJECTS_DIR="$WORK_DIR/formalized_graph/data/formalization_projects"

# Get sorted list of project dirs, pick this task's project
PROJECT=$(ls -1 "$PROJECTS_DIR" | sort | sed -n "$((SLURM_ARRAY_TASK_ID + 1))p")

if [ -z "$PROJECT" ]; then
    echo "No project for task $SLURM_ARRAY_TASK_ID"
    exit 0
fi

echo "=== Building $PROJECT (task $SLURM_ARRAY_TASK_ID) ==="
cd "$PROJECTS_DIR/$PROJECT"

echo "--- git pull ---"
git pull --ff-only 2>&1 || echo "WARNING: git pull failed, building from existing state"

echo "--- fetching Mathlib cache ---"
lake -R exe cache get 2>&1 || echo "WARNING: cache get failed, will build from source"

echo "--- building ---"
lake -R build 2>&1

echo "=== $PROJECT done ==="
