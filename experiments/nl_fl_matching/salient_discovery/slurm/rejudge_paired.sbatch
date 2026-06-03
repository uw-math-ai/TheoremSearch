#!/bin/bash
#SBATCH --job-name=rejudge_paired
#SBATCH --account=amath
#SBATCH --partition=ckpt
#SBATCH --cpus-per-task=6
#SBATCH --mem=8G
#SBATCH --time=4:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/simku22/logs/rejudge_paired_%j.out
# Paired empty-body validation: re-judge 150 empty-body MATCHES twice --
# Arm A slogan-only (control, isolates judge noise), Arm B with recovered signature.
set -uo pipefail
export HTTPS_PROXY=http://klone-dip1:3128
export HTTP_PROXY=http://klone-dip1:3128
export PYTHONUNBUFFERED=1
export PYTHONPATH=/gscratch/amath/simku22/TheoremSearch:/gscratch/amath/simku22/TheoremSearch/rds
export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude_oauth_token")"
export CLAUDE_CONFIG_DIR=/gscratch/amath/simku22/claude_cfg
mkdir -p "$CLAUDE_CONFIG_DIR"
cd /gscratch/amath/simku22/TheoremSearch
PY=/gscratch/amath/simku22/salient_venv/bin/python
G=experiments/nl_fl_matching/salient_discovery/grade_consensus.py
echo '=== ARM A: control (slogan-only) ==='
$PY $G --csv /gscratch/amath/simku22/rejudge_control.csv --out /gscratch/amath/simku22/rejudge_control.jsonl --bands 0.95-1.0,0.90-0.95 --cls all --any-source --workers 5
echo '=== ARM B: treatment (with recovered signature) ==='
$PY $G --csv /gscratch/amath/simku22/rejudge_treat.csv --out /gscratch/amath/simku22/rejudge_treat.jsonl --bands 0.95-1.0,0.90-0.95 --cls all --any-source --workers 5
echo '=== DONE both arms ==='
