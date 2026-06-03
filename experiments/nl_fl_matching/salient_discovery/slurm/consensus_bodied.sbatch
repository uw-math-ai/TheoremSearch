#!/bin/bash
#SBATCH --job-name=consensus_bodied
#SBATCH --account=amath
#SBATCH --partition=ckpt
#SBATCH --cpus-per-task=10
#SBATCH --mem=10G
#SBATCH --time=12:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/simku22/logs/consensus_bodied_%j.out
# Corrected top-down re-judge: same 2-rater Opus consensus but with recovered
# Lean signatures backfilled (salient_matches_full_bodied.csv). Sorted high->low
# sim by grade_consensus, so whatever completes = the source-judged prefix.
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
  --bands 0.95-1.0,0.90-0.95,0.85-0.90 --cls all --any-source --workers 10
