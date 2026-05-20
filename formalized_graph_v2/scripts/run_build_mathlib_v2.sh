#!/bin/bash
#SBATCH --job-name=v2-build
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/v2_build_%j.out
#SBATCH --error=/gscratch/amath/simku22/logs/v2_build_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=simku22@uw.edu

set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"

cd /gscratch/amath/simku22/TheoremSearch/formalized_graph_v2/data/mathlib4

echo "=== Building Mathlib + LeanGraph ==="
lake build LeanGraph 2>&1
echo "=== Done ==="
