# Formal ↔ Informal Matching — code & data map (paper-current)

Entry point for reviewing the matching pipeline behind the EMNLP paper's
"Bridging the corpora" section. This branch (`matching`) contains the **code on
the critical path** for the results we report; large data/results are **not
committed** — pointers to them are below.

## What this contributes to the paper
Cross-graph "semantic restatement" edges linking Lean formal declarations to
informal arXiv/blueprint statements, validated by an LLM-judge consensus.

### Headline numbers (current version)
| result | value | produced by |
|---|---|---|
| Compiler-artifact gate | 388,105 → **385,657** swept (2,448 removed, 0.63%) | `saliency_prior.py` |
| Retrieval (f→i, HNSW ann_k=50) | candidate for **53.5%** of nodes | `run_salient_sweep.py` |
| ≥0.90 candidate tier | **8,022** edges | `recompute_sweep_bins.py` (Table 4/5) |
| Corrected judging (Opus 4.8 + recovered Lean signature) | **5,650/8,022 (70%)** source-verified; **87.5% match** (3,046 exact + 1,870 inexact) | `grade_consensus.py`, `build_rejudge.py` |
| Yield curve (random ~150/bin) | ≥0.90 **85%** · 0.80–0.90 **48%** · 0.70–0.80 **15%** · 0.60–0.70 **4%** | `sample_tiers_guarded.py` |
| Body-fix finding | recovering missing Lean signatures flipped ~9% of empty-body verdicts to non-match (vs 2.9% re-judge noise floor) | `build_rejudge.py` + `grade_consensus.py` |
| Blueprint validation | 100% hard-neg rejection, 100% clean-gold recall (n=50+50) | `build_gold_pilot.py`, `score_gold_pilot.py` |
| Depth probe (ann_k 500/1000) | deeper search max sim 0.852 — below the judged band | `false_empty_probe.py` |

Judge model: **Claude Opus 4.8** (`claude-opus-4-8`), 2-rater consensus + tie-break.

### A note on saliency (honest scoping)
The project name is historical. The saliency *score* (out-degree etc., in
`saliency_features.py` + the prior in `saliency_prior.py`) only set sweep
**order**; because the **entire** gate-surviving set (385,657) was swept, it had
**no effect on which matches were found**. Only the **gate** (filter) in
`saliency_prior.py` is load-bearing. Saliency is an explored-but-non-load-bearing
ordering heuristic, not a result.

## Critical-path code (in this branch)
```
experiments/nl_fl_matching/
  topk.py, pools.py                      # retrieval + Stmt helpers (deps)
  salient_discovery/
    saliency_prior.py                    # compiler-artifact GATE (+ moot ordering prior)
    saliency_features.py                 # per-node features (feeds the gate's kind field)
    run_salient_sweep.py                 # f→i HNSW sweep over RDS pgvector
    export_matches_csv.py                # hydrate slogans/bodies from RDS → content CSV
    grade_consensus.py                   # *** the judge: 2-rater Opus consensus + tie-break
    build_rejudge.py                     # recover Lean signatures (body fix) + paired arms
    sample_tiers_guarded.py              # guarded random yield-curve sampler
    recompute_sweep_bins.py              # Table 4/5 (sim-bin × module distribution)
    false_empty_probe.py                 # ann_k depth-limitation probe
    build_gold_pilot.py, score_gold_pilot.py   # blueprint-gold validation
    export_judge_results.py              # review workbook + summary tables
    slurm/                               # the sbatch files everything was launched with (klone)
    verify/                              # scripts that independently recompute every reported number
    RUNS.md, prompt_v2_change_and_flagged_case.md, MISSING_FORMAL_BODY_DIAGNOSIS.md, ...
```
**Excluded as exploratory/superseded** (not in the reported results):
`run_band_filter.py` (abandoned Haiku band run), `sample_bins_build.py`,
`analyze_*.py`, `rerank_band.py`, `audit_sample.py`, `build_grader_eval.py`,
`build_review_html.py`, `score_grader.py`, `run_claude_audit.py`,
`append_chunk.py`, `export_corrected.py`.

## Where the data & results live (NOT in git)
### klone — primary, `/gscratch/amath/simku22/`
- `salient_sweep/`, `salient_sweep_bottom/` — raw f→i sweep shards (385,657 nodes)
- `salient_matches_full.csv` — ≥0.85 content (original; ~60% empty Lean body — the bug)
- `salient_matches_full_bodied.csv` — same, with **recovered** Lean signatures
- `consensus_ge90_v2_all.jsonl` — original ≥0.90 judge verdicts (8,022, slogan-only-ish)
- `consensus_bodied.jsonl` — **corrected** verdicts (5,650, with signatures) ← current results
- `tier_sample150.csv`, `tier_sample150_keys.json`, `tier_sample150_judged.jsonl` — yield curve
- `corpus_v3_fixed/corpus_v3 (corrected ingestion order).db` — source of recovered signatures
- `_gold_cache.json` (also local at `experiments/nl_fl_matching/_gold_cache.json`) — blueprint gold pairs
### local — `experiments/nl_fl_matching/salient_discovery/data/`
- Snapshots of the above (may lag klone; the fresh 5,650-edge `consensus_bodied.jsonl` is on klone).
### RDS (read-only) — `v2` on `theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com`
- Embeddings (pgvector HNSW), slogans, `formal_metadata`, `statement`, `paper`, etc. — the source of truth queried by the sweep/hydration scripts.

## How to reproduce a number
Each `verify/` script reads the judge-output JSONL directly and recomputes a
reported figure (match rate, body-effect flips, filter counts, per-tier yield).
Run from repo root with `PYTHONPATH=$PWD:$PWD/rds`.
