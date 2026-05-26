# Local pipeline stages. GPU steps (generation/embedding) run on klone — see klone/README.md.
# Requires: pip install -r requirements.txt ; a filled-in .env ; LPR_MATHLIB_DIR / LPR_LIB_DIR for typecheck.
PY ?= python

.PHONY: help index split retrieval formalize-data score typecheck-selftest clean

help:
	@echo "Targets: index split retrieval formalize-data score typecheck-selftest"
	@echo "GPU generation/embedding run on klone (see klone/README.md)."

index:                 ## pull 388k formal slogan embeddings from v2 -> cache/
	$(PY) scripts/build_formal_index.py

split:                 ## module-held-out train/val/test + premise-frequency tables
	$(PY) scripts/build_split.py

retrieval: index split ## retrieval baselines + supervised head + controls
	$(PY) scripts/eval_similarity_baseline.py
	$(PY) scripts/eval_frequency_prior.py
	$(PY) scripts/train_supervised_full.py
	$(PY) scripts/eval_query_shuffle.py

formalize-data:        ## build the formalization eval set + retrieval context (then generate on klone)
	$(PY) scripts/build_formalization_eval.py
	$(PY) scripts/build_rag_context.py

score:                 ## typecheck + premise-grounding, RAG vs no-RAG (after klone generation)
	$(PY) scripts/score_formalization.py --completions cache/out.json --eval cache/formalization_eval_rag.pkl

typecheck-selftest:    ## verify the Lean+Mathlib typecheck harness (needs LPR_MATHLIB_DIR)
	$(PY) scripts/run_typecheck.py --selftest

clean:                 ## remove regenerable artifacts (keeps nothing private)
	rm -rf cache __pycache__ scripts/__pycache__
