#!/bin/bash
#SBATCH --job-name=embed_gemma
#SBATCH --account=krishna
#SBATCH --partition=gpu-a40
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=1
#SBATCH --mem=40G
#SBATCH --time=8:00:00
#SBATCH --array=240-280
#SBATCH --output=logs/%x_%N_%A_%a.out

set -euo pipefail

CHUNK_SIZE=100000
BASE_START=0

START_ID=$((BASE_START + SLURM_ARRAY_TASK_ID * CHUNK_SIZE))
END_ID=$((START_ID + CHUNK_SIZE))

source /gscratch/amath/vilin/conda/etc/profile.d/conda.sh
conda activate thm-search

python3.11 -m ec2.generate_embeddings \
  --embedder gemma \
  --batch-size 64 \
  --page-size 128 \
  --condition "theorem_id >= ${START_ID} AND theorem_id < ${END_ID}" \
  --raw
