#!/bin/bash
# Template SLURM script that runs run_eval_v2.py with whatever flags are passed
# via the $EVAL_FLAGS env var. Each row of our ablation table submits with a
# different EVAL_FLAGS string.
#
# Required env vars (--export):
#   EVAL_FLAGS  e.g. "--dedupe --ann-k 1000 --hybrid-trigram --hyde ensemble"
#   ROW_LABEL   human label for the log, e.g. "row3-all-levers"

#SBATCH --job-name=eval-row
#SBATCH --account=amath
#SBATCH --partition=cpu-g2
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=14:00:00
#SBATCH --output=/gscratch/amath/simku22/logs/eval_row_%j.out

set -euo pipefail
export PYTHONUNBUFFERED=1

module load coenv/python/3.13.11
module load coenv/aws/2.17.32
cd /gscratch/amath/simku22/TheoremSearch
set -a; source .env; set +a
export RDS_HOST=localhost
# Per-job random-ish port to avoid collisions if multiple rows land on same node
export RDS_PORT=$((15700 + (SLURM_JOB_ID % 100)))

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
timeout 5 bash -c "</dev/tcp/127.0.0.1/${RDS_PORT} && echo '[${ROW_LABEL}] tunnel up on ${RDS_PORT}'"

echo "[${ROW_LABEL}] launching: python3 run_eval_v2.py ${EVAL_FLAGS}"
python3 experiments/leansearch_v2_replication/run_eval_v2.py ${EVAL_FLAGS}
