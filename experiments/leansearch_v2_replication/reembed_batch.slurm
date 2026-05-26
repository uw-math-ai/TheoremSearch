#!/bin/bash
#SBATCH --job-name=reembed-augmin
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=06:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/reembed_batch_%j.out

set -euo pipefail
export PYTHONUNBUFFERED=1

module load coenv/python/3.13.11
module load coenv/aws/2.17.32
cd /gscratch/amath/simku22/TheoremSearch
set -a; source .env; set +a
export RDS_HOST=localhost
export RDS_PORT=15600

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
timeout 5 bash -c "</dev/tcp/127.0.0.1/${RDS_PORT} && echo 'tunnel up on ${RDS_PORT}'"

# Nebius API + 8 internal worker threads. Resume-aware (skips slogan_ids
# that already have a row under embedding_model='qwen3-8b-augminimal').
python3 experiments/leansearch_v2_replication/reembed_augminimal.py \
    --shard 0 --n-shards 1 \
    --batch-size 200 --device nebius --parallel 8
