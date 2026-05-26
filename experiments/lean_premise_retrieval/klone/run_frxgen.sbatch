#!/bin/bash
#SBATCH --job-name=frxgen
#SBATCH -p ckpt-g2
#SBATCH -A amath-ckpt
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=1:00:00
#SBATCH --requeue
#SBATCH --exclude=g3110
#SBATCH --output=/gscratch/amath/aurasoph/formalize_rag/%x-%j.log
SIF=${LPR_SIF:-/gscratch/amath/slszeto/vllm-qwen3-4b_latest.sif}
W=${LPR_WORK:-/gscratch/amath/aurasoph/formalize_rag}
export APPTAINERENV_HF_HOME=/gscratch/amath/aurasoph/hf_cache APPTAINERENV_HF_HUB_OFFLINE=1 APPTAINERENV_TRANSFORMERS_OFFLINE=1
apptainer exec --nv --bind /gscratch "$SIF" python3 "$W/formalize_gen.py" --model Qwen/Qwen3-8B --eval "$W/formalrx_eval.pkl" --out "$W/out_formalrx_8B.json"
echo FRXGEN_DONE
