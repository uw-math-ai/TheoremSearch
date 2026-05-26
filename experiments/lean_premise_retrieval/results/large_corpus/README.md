# Large-corpus experiment artifacts

Inputs, retrieved context, and outputs for the post-cutoff formalization run.
Full write-up: [`../../docs/large_corpus_results.md`](../../docs/large_corpus_results.md).
Big regenerable binaries (embeddings, full name±sig listings, query head) are **not** here —
they stay in `cache/` (gitignored); regenerate via the scripts below.

| file | what |
|---|---|
| `ml_run_targets.json` | the 60 stratified candidate targets (name, module, sig, gold premises) |
| `ml_targets_informal.json` | back-translated NL prompt + query info per target |
| `ml30_targets.json` | the 24-target subset actually run (2 per topic) |
| `ml30_idmap.json` | anonymized id → real declaration name |
| `ml30_refs.json` | gold: id → real declaration signature (the answer key) |
| `ml30_norag.json`, `ml30_rag.json` | per-condition agent inputs (informal; +premises for RAG) |
| `ml30_out_{norag,rag,libsearch,both}.json` | per-condition formalizer outputs (`theorem cand … := sorry`) |

## How it was produced (Lean-only graph rule respected)

1. `lean/dump_ml_names.lean`, `lean/extract_new_targets.lean`, `lean/extract_sigs.lean` —
   diff v4.30 vs the old corpus, pick novel solvable targets, dump the `name :: sig` listing.
2. `klone/backtrans_targets.py` (`klone/run_targets.sbatch`) — back-translate signatures → NL,
   embed queries (L40S).
3. `scripts/retrieve_novel_targets.py` — apply the learned query head, retrieve premises.
4. Sonnet subagents formalize under four conditions, using `lean/tc_ml.sh` as the compiler
   loop (typecheck vs built v4.30 Mathlib).

Note: the Lean/shell scripts carry absolute paths from the original run; adjust for your machine.
