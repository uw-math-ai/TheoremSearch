#!/bin/bash
#SBATCH --job-name=reembed-augmin
#SBATCH --account=amath
#SBATCH --partition=gpu-rtx6k
#SBATCH --gres=gpu:rtx6k:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=40G
#SBATCH --time=02:00:00
#SBATCH --array=0-7
#SBATCH --output=/gscratch/amath/simku22/logs/reembed_augmin_%A_%a.out

set -euo pipefail
export PYTHONUNBUFFERED=1

module load coenv/python/3.13.11
module load coenv/aws/2.17.32
cd /gscratch/amath/simku22/TheoremSearch
set -a; source .env; set +a

# Each task uses a UNIQUE port so multiple shards on the same node don't
# fight over 5432. Use 15432 + array_index. The .env file's stale RDS_HOST
# is overridden via os.environ in db_connect (see reembed_augminimal.py).
export RDS_HOST=localhost
export RDS_PORT=$((15432 + SLURM_ARRAY_TASK_ID))

EC2_IP=$(aws ec2 describe-instances --instance-ids i-057240fcaecf18ce7 \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
RDS=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com

ssh -i ~/.ssh/mts_key.pem \
    -o StrictHostKeyChecking=accept-new \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -L "${RDS_PORT}:${RDS}:5432" -N -f "ec2-user@${EC2_IP}"
trap 'pkill -f "ssh.*-L.*${RDS_PORT}.*${EC2_IP}" || true' EXIT
sleep 2
timeout 5 bash -c "</dev/tcp/127.0.0.1/${RDS_PORT} && echo '[shard $SLURM_ARRAY_TASK_ID] tunnel up on port ${RDS_PORT}'"

# Each task processes 1/8 of the v427+v428 slogans. ~42K per shard at
# ~150-500 rows/sec on RTX 6000 (fp16) → ~2-5 min wall per shard.
python3 experiments/leansearch_v2_replication/reembed_augminimal.py \
    --shard "$SLURM_ARRAY_TASK_ID" \
    --n-shards 8 \
    --batch-size 64 \
    --device gpu
