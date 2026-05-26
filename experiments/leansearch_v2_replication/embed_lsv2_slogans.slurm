#!/bin/bash
# Stage 2 of Hail Mary 1: embed the lsv2-style slogans into a new
# embedding_model='qwen3-8b-lsv2slogan'. Runs after Stage 1 (regen) finishes.

#SBATCH --job-name=embed-lsv2
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --array=0-7
#SBATCH --output=/gscratch/amath/simku22/logs/embed_lsv2_%A_%a.out

set -euo pipefail
export PYTHONUNBUFFERED=1

module load coenv/python/3.13.11
module load coenv/aws/2.17.32
cd /gscratch/amath/simku22/TheoremSearch
set -a; source .env; set +a
export RDS_HOST=localhost
export RDS_PORT=$((16100 + SLURM_ARRAY_TASK_ID))

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

python3 experiments/leansearch_v2_replication/embed_slogans.py \
    --source-prompt lsv2-style \
    --source-model qwen3-235b \
    --target-embed-model qwen3-8b-lsv2slogan \
    --text-mode raw \
    --shard "$SLURM_ARRAY_TASK_ID" \
    --n-shards 8 \
    --batch-size 64 \
    --device nebius \
    --parallel 4
