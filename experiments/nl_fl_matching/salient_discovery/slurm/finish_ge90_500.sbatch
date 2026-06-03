#!/bin/bash
#SBATCH --job-name=finish500
#SBATCH --account=amath
#SBATCH --partition=ckpt
#SBATCH --cpus-per-task=10
#SBATCH --mem=10G
#SBATCH --time=2:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/simku22/logs/finish500_%j.out
# Calibration: judge EXACTLY 500 more of the >=0.90 tier (corrected, top-down by
# key-exclusion resume -> fills the 67 gaps above 0.917 first, then continues down).
set -uo pipefail
export HTTPS_PROXY=http://klone-dip1:3128
export HTTP_PROXY=http://klone-dip1:3128
export PYTHONUNBUFFERED=1
export PYTHONPATH=/gscratch/amath/simku22/TheoremSearch:/gscratch/amath/simku22/TheoremSearch/rds
export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude_oauth_token")"
export CLAUDE_CONFIG_DIR=/gscratch/amath/simku22/claude_cfg
mkdir -p "$CLAUDE_CONFIG_DIR"
cd /gscratch/amath/simku22/TheoremSearch
exec /gscratch/amath/simku22/salient_venv/bin/python \
  experiments/nl_fl_matching/salient_discovery/grade_consensus.py \
  --csv /gscratch/amath/simku22/salient_matches_full_bodied.csv \
  --out /gscratch/amath/simku22/consensus_bodied.jsonl \
  --bands 0.95-1.0,0.90-0.95 --cls all --any-source --workers 10 --limit 500
