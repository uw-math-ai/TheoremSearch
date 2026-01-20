#!/bin/bash
#SBATCH --job-name=embed_qwen8b_chunk0
#SBATCH --account=amath
#SBATCH --partition=gpu-rtx6k
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --array=0-0
#SBATCH --output=logs/%x_%N_%A_%a.out

set -euo pipefail

# Chunk definition
CHUNK_SIZE=100000
START_ID=140437
END_ID=$((START_ID + CHUNK_SIZE))

source /gscratch/amath/vilin/conda/etc/profile.d/conda.sh
conda activate thm-search

python3.11 -m ec2.generate_embeddings \
  --embedder qwen8b \
  --batch-size 4 \
  --page-size 16 \
  --condition "slogan_id >= ${START_ID} AND slogan_id < ${END_ID} AND prompt_id = 'body-only-v1' AND model = 'DeepSeek-V3.1'"
