# salient_discovery — run log

## RUN 1 — broad formal→informal sweep, top-50% saliency-ordered
**Launched 2026-05-28.** SLURM array **`35694319`** on klone `ckpt` (preemptible).

- script: `/gscratch/amath/simku22/salient_sweep.slurm` (NOT in repo, per convention)
- code/venv on gscratch: `TheoremSearch/` (synced topk.py w/ max_scan_tuples=500k +
  `salient_discovery/`), `/gscratch/amath/simku22/salient_venv` (py3.12 + psycopg2/boto3/numpy/tqdm)
- manifest: `query_manifest_top50.csv` (192,829 rows = top 50% by saliency prior,
  covers ~90% of blueprint gold; full manifest 385,657)
- array: `0-63%16` (64 shards × ~3,013 q, **16 concurrent** = chosen worker count)
- per task: ckpt, 2 cpu, 4G, 6h walltime, `--requeue` (checkpoint/resume safe)
- worker: `run_salient_sweep.py` → `topk.embedding_topk` (binary-Hamming shortlist +
  cosine rerank, ann_k=50, max_scan_tuples=500k), exclusion=statement, k=10, RDS **read-only**
- output: `/gscratch/amath/simku22/salient_sweep/salient_sweep_shard{NNNN}.jsonl`
  (one line/query: query_sid, cls, kind, decl_name, prior, n, results[rank,cand_sid,cand_pid,sim])
- expected wall: ~7–15h (median 2.2s/q; top-prior Mathlib slower via formal-anchored starvation)
- validation (pre-launch): srun on n3263, 15 q, 0 errors, valid JSONL, RDS-from-compute OK.

### Monitor
```
ssh klone "squeue -u simku22 -o '%.14i %.8T %.10M %R' | grep 35694319 | head"
ssh klone "cat /gscratch/amath/simku22/salient_sweep/*.jsonl | wc -l"   # progress (lags 200/shard)
```

### On completion / at reassess point (user chose: stop at ~50%, then decide tail)
1. Pull JSONL back (rsync to local data/ or analyze on klone with venv).
2. **Yield-curve analysis**: empty-rate + strong-match (sim≥0.85) rate by saliency band ×
   {mathlib,project}. This is the meaningful-match-vs-saliency tradeoff = decide whether the
   bottom-50% tail is worth sweeping.
3. **False-empty probe**: re-run a sample of empties at ann_k=500 (§6 showed ~20% rescue) to
   bound true-non-matchable vs scan-horizon artifact.
4. **Precision audit**: dual-rater (Sonnet 4.5 + Haiku 4.5) on sampled high-cosine matches
   across bands → precision vs saliency (the §6 n=45 protocol).
5. **Gold check**: of the 1,577 blueprint gold formals in the swept set, recover-rate at rank-1
   and within top-10 (sanity vs §6 i→f / f→i).
6. Learn the calibrated saliency weights (logistic regression, leave-one-repo-out) from results.

### Notes / risks live
- RDS read-only enforced (`SET default_transaction_read_only=on` in worker + per-task).
- 16 concurrent pgvector scans = the agreed RDS load; reevaluate if RDS health degrades.
- shard0000.jsonl already has 15 rows from validation — resume skips them (verified mechanism).

---
## RUN 1 RESULTS (2026-05-28, complete — 64/64 shards COMPLETED, ~couple hours wall)
ANALYSIS DONE (analyze_sweep.py). 192,829 queries (top-50% manifest).
- **18,914 strong (≥0.85) + 72,377 mid (0.75–0.85) candidate Mathlib↔arXiv edges** vs 1,595 blueprint gold.
- empty 41% (the not-matchable signal).
- **Validation:** swept gold formals (1,298) recover @rank-1 42.1% (§6 f→i 43.5%), @top-10 69.5% (§6 70%) — reproduces validated §6 retrieval.
- Saliency tradeoff (deciles of swept set): D1 empty19%/strong14% → D10 empty51%/strong9%. Prior front-loads matchability (fewer empties) but strong% plateaus ~9% (score-starved capstones spread throughout — match finds them, prior can't rank them).
- By class: mathlib 169,596 (45% empty, 10% strong ≈ 17k novel Mathlib→arXiv); project 23,233 (16% empty, 9% strong).
- ~18% of gold (279/1,577) fell in the UNSWEPT bottom-50% (lower-saliency capstones).

### Reassess decision (user chose stop-at-50%): TAIL = bottom-50% of manifest (192,828 decls)
- Extrapolating the plateau: bottom-50% would add ~another ~15-17k strong at >51% empty (more wasted scans, ~another night). NOT diminishing-to-zero — strong matches exist throughout.
- RECOMMENDATION: audit/characterize the current 18,914 strong FIRST (precision + cross-source novelty) before spending another night; sweep tail only if precision is high and maximal coverage wanted.

### Next (P5 eval, pending user call on tail):
- Dual-rater precision audit (Sonnet 4.5 + Haiku 4.5) on sampled strong matches across bands × class (§6 n=45 protocol).
- Cross-source breakdown: how many strong matches are Mathlib→arXiv (novel, corpus doesn't record) vs →blueprint (known-ish). Needs cand_pid→paper.source (RDS read-only).
- False-empty probe: sample empties, re-run ann_k=500 (§6 ~20% rescue).
- Calibrated saliency weights (logistic regression, leave-one-repo-out).

### CROSS-SOURCE NOVELTY (analyze_crosssource.py, 2026-05-28) — answers reassess Q1
Of the 18,914 strong (rank-1 sim>=0.85) matches, by query class × matched-informal source:
- **Mathlib→arXiv: 16,567** (novel — corpus records NO Mathlib↔arXiv edges) + Mathlib→blueprint 210
- project→arXiv: 1,605 + project→blueprint 532
- **TOTAL →arXiv: 18,172 (96% of strong)**; →Lean Community blueprint: 742
Sample Mathlib→arXiv (face-valid, correct): SimpleGraph.lineGraph→1409.5871 (1.000); Filter.Tendsto.cesaro→2409.06060 (1.000); Matrix.det_mul→2404.19348 (1.000); Nat.sum_four_squares→1907.01471 (0.996, Lagrange 4-square); eigenvalue_mem_ball→1302.3247 (0.991, Gershgorin); Fintype.isPrimePow_card_of_field→1509.05255 (0.991).
⇒ Discovery is real + abundant. NEXT: dual-rater precision audit on a stratified sample to put a number on it; then decide tail.

### PRECISION AUDIT (run_claude_audit.py via local `claude -p`, dual-rater sonnet+haiku, n=48, 2026-05-28)
NOTE: used local Claude Code CLI (real bin /Users/simon/.local/bin/claude; alias is `ctext wrap claude`) — local quota, no API/Bedrock.
**κ=0.627 (substantial — vs §6 gold-audit 0.30).** Overall n=48: both-correct 27%, broad(corr-or-partial) 60%, either-wrong 40%.
**Precision is band-dependent (the honest headline; raw ≥0.85 OVERSTATES):**
- sim 0.95-1.0 (pop 390):   strict 67%, **broad 100%**, wrong 0%
- sim 0.90-0.95 (pop 3,428): strict 33%, **broad 83%**, wrong 17%
- sim 0.85-0.90 (pop 12,749): strict 0%, broad 25%, **wrong 75%** (lexical-neighbor failures: group vs groupoid, p-adic val vs p^m-1|p^n-1)
- mid 0.75-0.85: broad 17%, wrong 83%
- project→arXiv strong (1,605): strict 17%, broad 50%, wrong 50%
**Verified-yield (precision-weighted) Mathlib→arXiv:** ≥0.90 ≈ 3,818 matches → ~3,200 broad-correct (~1,400 strict) novel edges; ≥0.85 bumps broad to ~6,400 but admits ~9,500 wrong.
**⇒ Operating threshold = 0.90, not 0.85.** Headline: **~3,200 high-confidence (≥0.90, ~85% audited) novel Mathlib→arXiv candidate edges** (~2× the 1,595 blueprint gold), in a new direction, with measured precision. The 0.85-0.90 band needs a reranker (the §6 sibling/lexical-hijack fix) before use.
**Tail (bottom-50%) revisited:** would add high-precision (≥0.90) edges roughly proportionally (~+3k) plus a large low-precision 0.85-0.90 mass; worth a night IF we want to ~2× the high-confidence set. Otherwise the ≥0.90 tranche we have is the deliverable.

### FALSE-EMPTY PROBE (false_empty_probe.py, n=40 empties re-run at ann_k=500, 2026-05-29)
70% of empties (28/40) find SOME informal neighbor at deeper scan, but **0/40 reach sim>=0.85**.
⇒ empties are not hiding STRONG matches — the 18,914 strong count is ~complete; the 41% "empty" =
"no strong informal partner" (correct for discovery). ~30% are isolated even at weak sim. (95% upper
bound on strong-in-empties ~7%, so a larger probe could tighten; point estimate 0%.)

### MATCHES CSV (export_matches_csv.py, 2026-05-29)
`data/salient_matches.csv` (23MB, 18,914 rank-1 matches sim>=0.85, local + gscratch). Columns:
sim, band, cls, formal_decl, formal_slogan, informal_slogan (adjacent for eye-check), informal_source,
arxiv_id, paper_title, informal_ref, formal_module, formal_body, informal_body, query_sid, cand_sid.
Bands: 0.95-1.0=475, 0.90-0.95=3,972, 0.85-0.90=14,467. cls: mathlib 16,777 / project 2,137.
Eye-check guidance: ≥0.90 (4,447 rows) is the audited ~85-100% tranche; 0.85-0.90 (14,467) is ~25%/75%-wrong
(reranker territory). Re-export other thresholds via --min-sim.

## RUN 2 — bottom-50% tail sweep (2026-05-29)
SLURM array **35700889** on ckpt, 16 concurrent. Manifest `query_manifest_bottom50.csv` (192,828 lower-saliency
formals, rows 192,830-385,657). Out: `/gscratch/amath/simku22/salient_sweep_bottom/`. Script
`/gscratch/amath/simku22/salient_sweep_bottom.slurm` (8h walltime, requeue). Same read-only worker.
Expectation (from RUN 1 deciles): higher empty-rate (>51%), larger 0.85-0.90 noise mass, ~9% strong plateau,
smaller ≥0.90 fraction than top half; slower (~10-15h). On completion: combined analysis over BOTH
salient_sweep/ + salient_sweep_bottom/ (yield curve, cross-source, gold recover), report ≥0.90 totals.
PARALLEL TRACK: 0.85-0.90 reranker on existing RUN 1 data (14,467 matches, ~25% precise) — structural
re-score (decl-name stem / kind / sibling) to rescue high-confidence edges from already-swept data.

### RERANKER ATTEMPT + BAND-PRECISION CORRECTION (rerank_band.py + claude -p audit n=54, 2026-05-29)
**Cheap structural reranker FAILED.** Rare-shared-vocab score + nshared_rare do NOT monotonically
predict correctness: by reranker tercile broad-precision = bottom 78% / mid 44% / top 72% (non-monotonic);
by nshared_rare rare0 61% / rare1 65% / rare>=2 100%(n=3). The 0.85-0.90 failures are SEMANTIC (group vs
groupoid, in the bodies), not surface-vocabulary — so a surface reranker adds nothing orthogonal to the
slogan-embedding that made the match. ⇒ the LLM judge (claude -p, κ~0.56-0.63) is the effective filter, not
a cheap structural proxy.
**CORRECTION to RUN-1 precision audit:** the better-powered n=54 audit puts the 0.85-0.90 Mathlib→arXiv band
at **~65% broad [51-77%] / ~13% strict**, NOT the 25%/0% from the first n=12 sample (that was an unlucky
low draw, 3/12). Earlier "0.85-0.90 mostly noise" RETRACTED. Revised top-half Mathlib→arXiv yield:
~11,000+ broad-useful (≥0.90 ~3,300 + 0.85-0.90 ~8,300) / ~3,000 strict. (broad leans on the squishy
'partial' label; strict ~13% is the firm floor.) ⇒ the 0.85-0.90 band is worth FILTERING (claude -p), not
discarding; and the bottom-50% tail sweep is more valuable than RUN-1 implied.

## COMBINED ANALYSIS — full 385,657 (both halves) (2026-05-29)
Tail 35700889 COMPLETE (64/64). Combined over salient_sweep/ + salient_sweep_bottom/ (glob salient_sweep*/*.jsonl).
- **35,578 strong (>=0.85)** + 134,096 mid + 179,496 empty (47%).
- **Cross-source: 32,331 Mathlib→arXiv (novel)** + 2,290 project→arXiv + 957 →blueprint. 97% of strong → arXiv.
  Mathlib→arXiv by band: >=0.95 = 703, 0.90-0.95 = 6,514, 0.85-0.90 = 25,114. **>=0.90 high-confidence = 7,217.**
- **Precision-weighted (audited rates 100/83/65% broad, 67/33/13% strict): ~22,400 broad-useful / ~5,900 strict
  Mathlib→arXiv edges.** vs 1,595 blueprint gold = ~4-14x expansion, new direction.
- **VALIDATION (full gold set): recover @rank-1 42.2% / @top-10 69.4% over all 1,577 gold formals** = reproduces
  §6 f→i (43.5% / 70%) cleanly. Strongest consistency check (full gold, not subset).
- Yield by decile: D1 25% empty/13% strong → D10 46% empty/8% strong. Strong-rate plateaus ~9% across the full
  range (confirms score-starved finding: saliency front-loads matchability/empties but NOT strong-rate; the match
  is the signal). By class: mathlib 349,384 (49% empty, 9% strong), project 36,273 (19% empty, 8% strong).
- Tail roughly DOUBLED strong Mathlib→arXiv (16,567 top-half → 32,331 combined); was worth running for raw count,
  though tail is lower-precision-per-query (more 0.85-0.90 / empties).
- Combined CSV: `data/salient_matches_full.csv` (41MB, 35,578 rows, local + gscratch /salient_matches_full.csv).

## RUN 3 — 0.85-0.90 band precision-filter via claude -p (2026-05-29)
sbatch **35720840** on ckpt (single job, network-bound, NOT array — rate-limit-bound to one Max account).
`claude -p` HAIKU over all 25,114 Mathlib→arXiv 0.85-0.90 matches, workers=5, retry/backoff (rides Max rate
limits), checkpoint/resume. Proxy HTTPS_PROXY=klone-dip1:3128. Out: /gscratch/amath/simku22/band_filter_haiku.jsonl.
Uses Claude Max subscription (NOT API key) — confirmed via login on klone.
**CRISP RUBRIC (replaces the vague correct/partial/wrong that hedged 9/10→partial):** judge same-statement via a
caveat test — exact (same proposition, notation-only diff = clean edge) / inexact (same result, NAMED caveat:
one-direction / sub-component / <= vs = / special-case) / wrong (different theorem) / unjudgeable (missing text only).
Validated n=18: exact5/inexact10/wrong3, every checkable call correct, reasons name the specific match/mismatch.
On completion: exact-rate (clean verified edges) + exact+inexact-rate (same-result edges) + wrong-rate over the full
band; then Pass 2 = sonnet confirmation on the haiku exact+inexact for dual-rater high-confidence set.

### JUDGE VALIDATION — haiku vs Opus (workflow wq1ea0f63, n=60 stratified 20/20/20, 2026-05-30)
60 Opus subagents blind-rejudged a stratified sample of haiku's band labels (same crisp rubric, haiku label hidden).
- **edge-vs-not agreement 85%; haiku's "keep"(edge) labels 90% confirmed real edges by Opus (36/40).**
- haiku WRONG: Opus agrees 75% (15/20), rescues 5 as edges → haiku errs CONSERVATIVE (undercounts edges, ~10% false-edge pass rate).
- haiku over-calls EXACT: 8/20 haiku-exact are really inexact per Opus; 1/20 a false edge. The 4 false edges are the
  "Lean lemma/instance ABOUT X vs informal DEFINITION of X" trap.
- Opus-corrected band precision (weight Opus verdicts by haiku band proportions 30/45/25): **~73% edge (vs haiku 75% — validated) / ~21% exact (vs haiku 30% — haiku over-states exact) / ~27% wrong.**
⇒ VERDICT: grind with haiku JUSTIFIED for the edge decision (rate trustworthy, errs safe); trust the EDGE count, discount the EXACT count. Refine exact-vs-inexact with a stronger model on the edges only if needed.
  **⚠ SUPERSEDED by JUDGE VALIDATION v2 below (n=251, two-Opus consensus): keep-precision is ~77% NOT 90%, and haiku errs LENIENT not conservative. The n=60 "conservative" read was a noisy 5/20 single-Opus rescue.**

### JUDGE VALIDATION v2 — haiku vs two-Opus consensus (workflows wf_78ac0e48 blind + wf_16dcc3c2 tie-break, n=251, 2026-05-30)
SUPERSEDES the n=60 verdict above. Stratified 80 exact / 80 inexact / 80 wrong / 11 unjudgeable from the 7,232 done.
Method: 251 Opus blind regrades (haiku label physically absent from per-pair content files, verified 0 leaks) +
84 second-blind Opus tie-breaks on EVERY haiku↔Opus disagreement. TRUTH = two-Opus consensus (never haiku's own
vote → non-circular). 15/251 (6%) where the two blind Opus disagreed = irreducibly ambiguous, set aside. n=236 resolved.
Artifacts: data/grader_opus_blind.json, grader_opus_tiebreak.json, grader_scored.json, grader_truth.json. Scorer: score_grader.py.
- κ(haiku, truth) = **0.57** (moderate); 4-way agreement 71%; **edge-collapse agreement 82%**.
- Confusion (haiku→truth, resolved): exact → 70% exact / 89% edge (reliable) | inexact → 68% edge, **32% actually WRONG** (weak spot, "sounds-related" dumping ground) | wrong → 91% not-edge / 9% missed real links (reliable rejections) | unjudgeable → garbage (n=10).
- haiku errs **LENIENT** (32 too-lenient vs 11 too-harsh) — REVERSES the n=60 "conservative" call.
- **Band edge keep-precision = 76.6% [69.7, 83.5]** (bootstrap, reweighted to 7,232 haiku proportions) — NOT 90%. Exact precision 70% → ~21% of band candidates are exact formalizations. ~9% of haiku-"wrong" (~166) are real links discarded.
- **CAVEAT (generalization):** the 7,232 labeled are the **high-sim HEAD** of the band (all sim ≥ 0.8785; band median 0.8680; the 17,882 unlabeled are lower-sim, median 0.8621). So full-band precision is **below 76.6%** — the measured number is the optimistic end.
⇒ **VERDICT v2:** trust haiku **exact** (89% edge) and **wrong** (91% not-edge); DO NOT trust haiku **inexact** alone (32% are different theorems). The discovery headline (~3/4 of the high-sim band are real Mathlib↔arXiv edges) survives at **~77%**, but haiku is a LENIENT, moderate gate (κ=.57), NOT "errs safe." Grinding the remaining 17,882 with haiku adds lenient-labeled coverage (worse on the low-sim tail), not a clean set. A clean edge set needs an Opus pass on the inexact bucket (or the whole high-sim band); the 251-pair Opus audit already pins the precision with CIs, so more haiku is not needed for the precision claim.

### RUN 3b — grind resumed (2026-05-30)
Driver FIXED: failed/throttled calls now SKIP (return None, not written) → retried next run, no more `ambiguous`
pollution (the 16-worker bug). Relaunched sbatch **35731674** at SAFE workers=5 (the 16-worker bump hit the Max
rate/budget window → 959 failed calls, purged). Resumes from 7,232 clean labels; ~17,882 remain. User has ~40%
weekly Max left, resets in ~8h — at budget exhaustion the fixed driver skips gracefully and resumes after reset.
**ABANDONED for the precision claim** — JUDGE VALIDATION v2 showed haiku is too lenient (κ=.57, inexact 32% wrong)
to be the authoritative grader. Pivoted to airtight Opus consensus (RUN 4). The 7,232 haiku labels are kept only as
a non-binding pre-sort / the validation substrate.

### RUN 4 — AIRTIGHT 2-rater Opus consensus (decision: stage ≥0.90 first, 2026-05-30)
**Why:** for a *claimed* matching, one model rating (even Opus) isn't airtight. `grade_consensus.py`: 2 independent
blind Opus grades per candidate → CONFIRMED if agree; 3rd-Opus tie-break if not (majority of 3); genuine 3-way split
→ ABSTAIN (we do NOT claim it). Controls FP (a fluke must fool two independent graders) AND FN (rejections are
double-graded too). Neutral rubric (no adversarial skew, which would bias FN/FP). High-sim-first ordering.
**Throughput probe (Opus `claude -p`, klone):** single call ~26s, **workers=5 → 4.4s/call, 10/10 success.** KEY FIX:
`stdin=subprocess.DEVNULL` is REQUIRED (without it the child blocks on inherited stdin over interactive ssh; sbatch
gives /dev/null so the haiku runs worked). Added to both run_band_filter.py and grade_consensus.py.
**Cost map (2-rater + tie-breaks ≈ 2.2 grades/cand @ 4.4s):** ≥0.90 tier (7,217) ~19h/~224M Max; +0.85-0.90 band
(25,114) +2.8d/~770M; full ≥0.85 (32,331) ~3.6d/~1B ≈ whole week of Max.
**Launched:** sbatch **35752091** (ckpt, --requeue, workers=5) over the ≥0.90 tier (bands 0.95-1.0 + 0.90-0.95,
Mathlib→arXiv, 7,217). Out: /gscratch/amath/simku22/consensus_ge90.jsonl. Validated n=3 (all confirmed, sim=1.0 head
= 2 exact / 1 inexact). After burn-rate is known → decide whether to extend to the 0.85-0.90 band or audit it.
**Released regardless (FN-honesty):** full RAW candidate pool (34,621 likelies, scored, ungraded) + recall note
(empty-rate 41%, ann_k=50 horizon, gold-recover 42%/69%) — we never imply the matching is complete.

Record schema (consensus_ge90.jsonl): key, query_sid, cand_sid, sim, band, formal_decl, arxiv_id, labels[2-3],
reasons[], final (fine label or null), edge (bool or null), status ∈ {confirmed, tiebroken, edge_ambiguous,
notedge_ambiguous, ambiguous}.

### RUN 5 — v2 re-grade of the ≥0.90 tier (guarded prompt, LOCAL workflows, 2026-06-01)
Prompt v2 = v1 + SELF-CONSISTENCY GUARD (forbids `exact` when the reason names any difference);
context kept (decl-name + body) — VALIDATED by the gold pilot (prompt_v2_change_and_flagged_case.md §6:
slogan+name 100% clean-gold recall + 100% hard-neg reject; slogan-only loses ~7pp to lossy slogans).
**Vehicle switched klone → LOCAL Opus workflows.** klone Max OAuth token died AGAIN (401; `.credentials.json`
2 days stale, no refresh) + `.claude.json` corrupts on every call (lingering daemon races) → klone is not viable
unattended. Local workflows have done 535 Opus grades tonight with 0 failures.
Mechanism: `ge90_v2_chunk.js` grades a chunk [start,end) of the 7,217 (high-sim first, `/tmp/ge90/<idx>.json`)
with 2 blind Opus raters + tie-break; `append_chunk.py` joins idx→manifest and appends to
`/tmp/consensus_ge90_v2.jsonl` (v1 `consensus_ge90.jsonl` kept untouched for the delta). 19 chunks of 380,
self-chained on completion. Resumable (dedupe by key). On full completion: compare v1 vs v2 (exact→inexact/wrong
shifts, net edge change, flips) + then the 0.85–0.90 band decision.

### RUN 5b — v2 re-run moved to AUTONOMOUS klone (durable token + gscratch config, 2026-06-01)
ROOT CAUSE of all the klone auth/corruption pain: **home quota full** (11G) → truncated writes →
`.claude.json` "Unexpected EOF" corruption + OAuth token couldn't refresh (401s). Fixed:
1. Freed home to 8G (cleared regenerable ~/.cache, ~/.npm/_cacache, ~/.claude caches).
2. **Durable auth:** `claude setup-token` → long-lived token in `~/.claude_oauth_token` (chmod 600),
   exported as `CLAUDE_CODE_OAUTH_TOKEN` in the sbatch (no more every-few-hours 401).
3. **`CLAUDE_CONFIG_DIR=/gscratch/amath/simku22/claude_cfg`** so claude's state writes go to gscratch,
   NOT the home quota — prevents the fill-during-run stall. (auth via env token, independent of cfg dir.)
4. `--no-session-persistence` added to grade_consensus.py's claude call.
Submitted **sbatch 35803487** (ckpt, requeue, workers=5) over the full ≥0.90 tier; out
`/gscratch/amath/simku22/consensus_ge90_v2.jsonl`, seeded with the 380 local v2 records (resumes, skips them).
slurm: `slurm/consensus_ge90_v2.sbatch`. Local self-chaining abandoned (laptop shutting down).

### RUN 5b RESULT — v2 ≥0.90 re-grade COMPLETE (job 35808783, 2026-06-01)
All **7,217** ≥0.90 Mathlib→arXiv candidates graded, guarded v2 prompt, 2-rater Opus consensus + tie-break.
Out: `data/consensus_ge90_v2.jsonl` (+gscratch). ~2.16 judges/cand (16% needed tie-break), ~27 cand/min @ workers=5.
- **status:** confirmed 6,135 / tiebroken 1,037 / edge_ambiguous(abstain) 45.
- **CONFIRMED EDGE: 6,489** (exact 4,104 + inexact 2,385) | rejected (not-edge) 683 | abstained 45.
- **edge rate 90.5%** of decided (0.95-1.0 tier: 94%, n=703; 0.90-0.95: 90%, n=6,514).
- **GUARD EFFECT (v1∩v2 overlap n=2,636):** 302 of v1-"exact" demoted (15%) — 271→inexact, 31→wrong;
  net edge count 2,518→2,507 (−11). ⇒ guard fixes exact-tier honesty WITHOUT moving the discovery count.
This is the airtight ≥0.90 confirmed edge set. v1 (`consensus_ge90.jsonl`) kept for the delta; v2 supersedes it.
NEXT (P7): decide 0.85-0.90 band — extend consensus grading (25,114, ~big) vs characterize by the n=251 audit.

### SWEEP BIN DISTRIBUTION — full recompute from raw shards (recompute_sweep_bins.py, 2026-06-02)
Authoritative, from 385,657 raw shard rows (salient_sweep + salient_sweep_bottom), rank-1 sim by class:
| bin | total | % swept | mathlib | project |
|---|---|---|---|---|
| 0.95-1.0 | 805 | 0.2% | 707 | 98 |
| 0.90-0.95 | 7,217 | 1.9% | 6,586 | 631 |
| 0.85-0.90 | 27,556 | 7.1% | 25,347 | 2,209 |
| 0.75-0.85 | 134,096 | 34.8% | 118,276 | 15,820 |
| <0.75 | 36,487 | 9.5% | 25,957 | 10,530 |
| empty | 179,496 | 46.5% | 172,511 | 6,985 |
| TOTAL | 385,657 | 100% | 349,384 | 36,273 |
- retrieved (non-empty) = 53.5%; empty = 46.5% (CORRECTS earlier "41% empty" which was top-50%-only).
- strong ≥0.85 = 35,578 (9.2%); ≥0.90 all-class = 8,022; judged Mathlib→arXiv ≥0.90 = 7,217.
- Funnel: 385,657 swept → 206,161 retrieved → 35,578 strong → 8,022 ≥0.90 → 7,217 judged → 6,534 confirmed.
- EMPTY = partly scan-horizon artifact: HNSW index is mixed formal+informal, ef_search=200/max_scan_tuples=500k;
  a formal query is surrounded by formal neighbors so informals can fall outside the horizon (n=0).
- false-empty probe (n=40, ann_k=500): 70% of empties become non-empty at deeper scan but 0% reach ≥0.85
  ⇒ more ann_k inflates the weak tail, NOT the ≥0.90 set. Bigger probe (n=150, ann_k=1000) = sbatch 35842690.

### FALSE-EMPTY PROBE v2 — bigger, deeper (n=200 @ ann_k∈{500,1000}, sbatch 35843706, 2026-06-02)
Re-ran empty (n=0 @ ann_k=50) queries at deeper search depth to test if empties hide real matches:
| ann_k | n | rescued (non-empty) | strong ≥0.85 | reaches ≥0.90 |
|---|---|---|---|---|
| 500 | 40 (orig) | 70% | 0/40 | — |
| 1000 | 150 | 86% | 0/150 | — |
| 500 | 200 | 76% | 2/200 (1%) | no (both 0.852) |
| 1000 | 200 | 85% | 2/200 (1%) | no (both 0.852) |
⇒ Deeper scan rescues more empties into WEAKER neighbors (rescue 76→85% as ann_k 500→1000) but strong
count stays at 2; the 2 are marginal (0.852, in the lowest 0.85-0.90 band) and **0/200 reach ≥0.90**.
CONCLUSION (verified, n=200): increasing ann_k does NOT expand the high-confidence (≥0.90) set; the
46.5% empty rate is an embedding/data property, not an under-tuned search budget. Runtime ~15-20 min/probe.

### RUN 6 — COMPLETE the ≥0.90 tier (judge non-mathlib-arxiv edges, job 35847003, 2026-06-02)
Found the earlier v2 run judged ONLY mathlib→arXiv (grade_consensus.py default --cls mathlib + arXiv filter) —
silently excluded 805 ≥0.90 edges: project→arXiv 521 (NOVEL, no good reason skipped), project→blueprint 208,
mathlib→blueprint 76 (overlap gold source). Fix: grade_consensus.py now supports --cls all + --any-source +
source-aware prompt. Seeded consensus_ge90_v2_all.jsonl with the 7,217 mathlib→arXiv; grading the remaining 805.
On completion: complete ≥0.90 set = 8,022 judged; per-source breakdown; regenerate review workbook. Validated n=2
(project→arXiv, both confirmed exact). The "7,217" framing in the paper draft → "8,022 ≥0.90, all judged".
