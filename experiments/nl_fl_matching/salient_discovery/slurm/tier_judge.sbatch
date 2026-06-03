#!/bin/bash
#SBATCH --job-name=tier_judge
#SBATCH --account=amath
#SBATCH --partition=ckpt
#SBATCH --cpus-per-task=10
#SBATCH --mem=8G
#SBATCH --time=2:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/simku22/logs/tier_judge_%j.out
# Judge ONE similarity tier of the guarded n=150 random sample (body-backfilled).
# BAND passed via --export. Shared checkpointed output -> safe to run tiers sequentially.
set -uo pipefail
export HTTPS_PROXY=http://klone-dip1:3128
export HTTP_PROXY=http://klone-dip1:3128
export PYTHONUNBUFFERED=1
export PYTHONPATH=/gscratch/amath/simku22/TheoremSearch:/gscratch/amath/simku22/TheoremSearch/rds
export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude_oauth_token")"
export CLAUDE_CONFIG_DIR=/gscratch/amath/simku22/claude_cfg
mkdir -p "$CLAUDE_CONFIG_DIR"
cd /gscratch/amath/simku22/TheoremSearch
echo "=== judging tier: $BAND ==="
exec /gscratch/amath/simku22/salient_venv/bin/python \
  experiments/nl_fl_matching/salient_discovery/grade_consensus.py \
  --csv /gscratch/amath/simku22/tier_sample150.csv \
  --out /gscratch/amath/simku22/tier_sample150_judged.jsonl \
  --bands $BAND --cls all --any-source --workers 10
