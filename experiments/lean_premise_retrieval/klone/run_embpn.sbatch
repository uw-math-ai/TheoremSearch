#!/bin/bash
#SBATCH --job-name=embpn
#SBATCH -p ckpt-g2
#SBATCH -A amath-ckpt
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=0:40:00
#SBATCH --requeue
#SBATCH --exclude=g3110
#SBATCH --output=/gscratch/amath/aurasoph/formalize_rag/%x-%j.log
SIF=${LPR_SIF:-/gscratch/amath/slszeto/vllm-qwen3-4b_latest.sif}
export APPTAINERENV_HF_HOME=/gscratch/amath/eol05/hf_cache APPTAINERENV_HF_HUB_OFFLINE=1 APPTAINERENV_TRANSFORMERS_OFFLINE=1
apptainer exec --nv --bind /gscratch "$SIF" python3 /gscratch/amath/aurasoph/formalize_rag/embed_generic.py proofnet_sample.json live_proofnet.npy
echo EMBPN_DONE
