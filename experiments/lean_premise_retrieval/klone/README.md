# klone / L40S recipes

GPU steps run inside a vLLM apptainer image (transformers ≥4.57, torch+CUDA). These sbatch
files encode amath-partition defaults; override via env vars and edit the `#SBATCH --output`
path for your account.

## Overridable vars
- `LPR_SIF`  — apptainer image with vLLM/transformers (default: a shared amath image).
- `LPR_WORK` — work dir on `/gscratch` holding the eval pkls + scripts + outputs.
- `HF_HOME`  — HuggingFace cache holding the models (Qwen3-8B, Qwen3-Embedding-8B).

## Models
- **Qwen3-8B** (formalizer): `huggingface-cli download Qwen/Qwen3-8B` to `$HF_HOME` (on a login
  node with internet; compute nodes are offline, so set `HF_HUB_OFFLINE=1` in jobs).
- **Qwen3-Embedding-8B** (query/embedding model, last-token pooling): same.

## Jobs
- `run_frxgen.sbatch` / `run_bmgen.sbatch` → `formalize_gen.py` : no-RAG vs RAG generation.
- `run_embpn.sbatch` → `embed_generic.py` : embed a list of informal statements (novel-query retrieval).
- `run_bm.sbatch` → `backtrans_and_embed.py` : back-translate a library's decls + embed → library index.

## Flow
1. Build artifacts locally (`build_*` scripts) and `scp` the eval pkls + scripts to `$LPR_WORK`.
2. `sbatch` the relevant job (it runs the script inside the apptainer, offline).
3. `scp` outputs back; typecheck + score locally (`score_formalization.py`, `typecheck_lib_outputs.py`).
