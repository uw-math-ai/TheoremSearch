#!/bin/bash
#SBATCH --job-name=consensus_v2_all
#SBATCH --account=amath
#SBATCH --partition=ckpt
#SBATCH --cpus-per-task=6
#SBATCH --mem=8G
#SBATCH --time=12:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/simku22/logs/consensus_v2_all_%j.out
# Complete the >=0.90 tier: judge ALL classes/sources (the 805 non-mathlib-arxiv edges
# excluded by the earlier default). Seeded with the 7,217 mathlib->arXiv v2 results.
set -uo pipefail
export HTTPS_PROXY=http://klone-dip1:3128
export HTTP_PROXY=http://klone-dip1:3128
export PYTHONUNBUFFERED=1
export PYTHONPATH=/gscratch/amath/simku22/TheoremSearch:/gscratch/amath/simku22/TheoremSearch/rds
export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude_oauth_token")"
export CLAUDE_CONFIG_DIR=/gscratch/amath/simku22/claude_cfg
mkdir -p "$CLAUDE_CONFIG_DIR"
# seed once (requeue-safe: don't clobber in-progress output)
[ -f /gscratch/amath/simku22/consensus_ge90_v2_all.jsonl ] || \
  cp /gscratch/amath/simku22/consensus_ge90_v2.jsonl /gscratch/amath/simku22/consensus_ge90_v2_all.jsonl
cd /gscratch/amath/simku22/TheoremSearch
exec /gscratch/amath/simku22/salient_venv/bin/python \
  experiments/nl_fl_matching/salient_discovery/grade_consensus.py \
  --csv /gscratch/amath/simku22/salient_matches_full.csv \
  --out /gscratch/amath/simku22/consensus_ge90_v2_all.jsonl \
  --bands 0.95-1.0,0.90-0.95 --cls all --any-source --workers 5
