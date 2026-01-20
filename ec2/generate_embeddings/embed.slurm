#!/bin/bash
#SBATCH --job-name=embed_qwen8b
#SBATCH --account=krishna
#SBATCH --partition=gpu-l40s
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --time=3:00:00
#SBATCH --array=0-99
#SBATCH --output=logs/%x_%N_%A_%a.out

set -euo pipefail

CHUNK_SIZE=100000
BASE_START=140437

START_ID=$((BASE_START + SLURM_ARRAY_TASK_ID * CHUNK_SIZE))
END_ID=$((START_ID + CHUNK_SIZE))

source /gscratch/amath/vilin/conda/etc/profile.d/conda.sh
conda activate thm-search

python3.11 -m ec2.generate_embeddings \
  --embedder qwen8b \
  --batch-size 64 \
  --page-size 128 \
  --condition "slogan_id >= ${START_ID} AND slogan_id < ${END_ID} AND prompt_id = 'body-only-v1' AND model = 'DeepSeek-V3.1'"
