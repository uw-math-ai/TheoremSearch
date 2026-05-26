#!/bin/bash
#SBATCH --job-name=bmbte
#SBATCH -p ckpt-g2
#SBATCH -A amath-ckpt
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=80G
#SBATCH --time=1:30:00
#SBATCH --requeue
#SBATCH --exclude=g3110
#SBATCH --output=/gscratch/amath/aurasoph/formalize_rag/%x-%j.log
SIF=${LPR_SIF:-/gscratch/amath/slszeto/vllm-qwen3-4b_latest.sif}
export APPTAINERENV_HF_HOME=/gscratch/amath/aurasoph/hf_cache APPTAINERENV_HF_HUB_OFFLINE=1 APPTAINERENV_TRANSFORMERS_OFFLINE=1
# Qwen3-8B is in aurasoph cache; Qwen3-Embedding-8B is in eol05 cache -> bind both via HF_HOME symlink trick: use eol05 as HF_HOME won't have 8B. So set HF cache to a dir with both via HF_HUB_CACHE list not supported; instead copy-less: point HF_HOME to aurasoph and add eol05 hub via HF symlink.
apptainer exec --nv --bind /gscratch "$SIF" bash -c 'export HF_HOME=/gscratch/amath/aurasoph/hf_cache; mkdir -p $HF_HOME/hub; for d in /gscratch/amath/eol05/hf_cache/hub/models--Qwen--Qwen3-Embedding-8B; do ln -sfn $d $HF_HOME/hub/$(basename $d); done; HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 /gscratch/amath/aurasoph/formalize_rag/backtrans_and_embed.py'
echo BMBTE_DONE
