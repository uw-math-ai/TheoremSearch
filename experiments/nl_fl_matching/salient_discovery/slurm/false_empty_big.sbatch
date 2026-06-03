#!/bin/bash
#SBATCH --job-name=fe_big
#SBATCH --account=amath
#SBATCH --partition=ckpt
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=3:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/simku22/logs/fe_big_annk%a_%j.out
#SBATCH --array=500,1000
set -uo pipefail
cd /gscratch/amath/simku22/TheoremSearch
set -a; source .env 2>/dev/null; set +a
export RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com
export PYTHONPATH=$PWD:$PWD/rds
exec /gscratch/amath/simku22/salient_venv/bin/python \
  experiments/nl_fl_matching/salient_discovery/false_empty_probe.py \
  --glob "/gscratch/amath/simku22/salient_sweep*/*.jsonl" \
  --manifest experiments/nl_fl_matching/salient_discovery/data/query_manifest.csv \
  --n 200 --ann-k ${SLURM_ARRAY_TASK_ID}
