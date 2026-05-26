#!/bin/bash
# Stage 1 of Hail Mary 1: regenerate slogans for Mathlib v427+v428 using the
# LSv2-style prompt. Sharded for parallelism. Writes to slogan table under
# (prompt_name='lsv2-style', model_name='qwen3-235b'). Resume-safe: existing
# rows with the same key are skipped.
#
# Submit with:
#   sbatch --array=0-15 regen_lsv2_slogans.slurm
#
# Cost estimate (qwen3-235b on Nebius): ~$150 for 337K calls. Wall ~1-2h
# with 16 parallel shards × 8 worker threads = 128 concurrent LLM calls.

#SBATCH --job-name=regen-lsv2
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=08:00:00
#SBATCH --array=0-15
#SBATCH --output=/gscratch/amath/simku22/logs/regen_lsv2_%A_%a.out

set -euo pipefail
export PYTHONUNBUFFERED=1

module load coenv/python/3.13.11
module load coenv/aws/2.17.32
cd /gscratch/amath/simku22/TheoremSearch
set -a; source .env; set +a
export RDS_HOST=localhost
export RDS_PORT=$((16000 + SLURM_ARRAY_TASK_ID))

EC2_IP=$(aws ec2 describe-instances --instance-ids i-057240fcaecf18ce7 \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
RDS=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com

ssh -i ~/.ssh/mts_key.pem \
    -o StrictHostKeyChecking=accept-new \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -L "${RDS_PORT}:${RDS}:5432" -N -f "ec2-user@${EC2_IP}"
trap 'pkill -f "ssh.*-L.*${RDS_PORT}" || true' EXIT
sleep 2
timeout 5 bash -c "</dev/tcp/127.0.0.1/${RDS_PORT} && echo '[shard $SLURM_ARRAY_TASK_ID] tunnel up on ${RDS_PORT}'"

# Standalone slogan regen — generates lsv2-style slogans for Mathlib v427+v428
# only, via Nebius qwen3-235b. Writes to slogan table under
# (prompt_name='lsv2-style', model_name='qwen3-235b'). Resume-safe.
python3 experiments/leansearch_v2_replication/regen_lsv2_slogans.py \
    --shard "$SLURM_ARRAY_TASK_ID" \
    --n-shards 16 \
    --workers 8
