#!/bin/bash
#SBATCH --job-name=formalize_rag
#SBATCH -p ckpt-g2
#SBATCH -A amath-ckpt
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=3:00:00
#SBATCH --requeue
#SBATCH --output=/gscratch/amath/aurasoph/formalize_rag/%x-%j.log
set -e
SIF=${LPR_SIF:-/gscratch/amath/slszeto/vllm-qwen3-4b_latest.sif}
W=${LPR_WORK:-/gscratch/amath/aurasoph/formalize_rag}
export APPTAINERENV_HF_HOME=/gscratch/amath/aurasoph/hf_cache
export APPTAINERENV_HF_HUB_OFFLINE=1 APPTAINERENV_TRANSFORMERS_OFFLINE=1
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
for M in "$@"; do
  tag=$(echo "$M" | tr '/' '_')
  echo "=== generating with $M ==="
  apptainer exec --nv --bind /gscratch "$SIF" python3 "$W/formalize_gen.py" \
    --model "$M" --eval "$W/formalization_eval_rag.pkl" --out "$W/out_$tag.json"
done
echo "ALL_MODELS_DONE"
