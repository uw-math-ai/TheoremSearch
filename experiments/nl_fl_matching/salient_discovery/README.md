# salient_discovery — saliency-aware formal→informal matching

Subfolder of the graph-matching experiment (`experiments/nl_fl_matching/`).
Journal-style state doc. Terse.

## Why
Blueprint-gold pairs (1,595) are too sparse to unite the informal (arXiv,
11.7M) and formal (Lean, 388k) graphs. To infer cross-graph edges at scale:
sweep formal decls → informal graph and keep the meaningful matches.
**Goal = discovery-first**: the most meaningful new Mathlib↔arXiv edges.
Scope = Mathlib (351,397) + projects (36,708). No fixed filter size — the
saliency↔match-quality tradeoff sets the operating point.

## Core reframe (from data + literature + adversarial review, all verified)
The ~40% of paper-worthy theorems that have **no docstring and ~zero reuse**
("score-starved capstones", verified 637/1,577 gold = 40.4%) are invisible to
cheap structural saliency. The signal that finds them is **the slogan-embedding
match to the arXiv corpus itself** — i.e. *the match is the saliency signal*.
⇒ Do NOT hard-filter to a small set (loses them). Gate out only compiler
artifacts, **sweep broadly in saliency-prior order, let match-confidence +
a light prior decide** what's meaningful.

## Verified data findings (calibrated on 1,577 gold formals; from `data/saliency_features.csv`)
- gold split: **274 Mathlib / 1,303 project** (83% project) vs corpus 90.5%
  Mathlib — inverted label distribution (selection bias; see Risks).
- **out-degree (proof depth)** separates: AUROC 0.79 vs Mathlib (gold med 64 vs 19).
- **in-degree is the trap**: 76% of gold has ZERO sig-in-degree; gold mean
  (10.32) == pop (10.36); top-15 sig-in-degree are pure plumbing (Eq=184k,
  Nat=79k, instOfNatNat=38k, instHAdd=29k…). Use only as a saturating NEGATIVE
  tail term, never positive, never a gate.
- **docstring** real but confounded + partial: gold 53.3% non-empty vs Mathlib
  12.9% / project 33.2% (cohort-normalize within stratum); absent on 47% of gold;
  core plumbing (Nat.add, Eq.trans, id) also carries (longer) docstrings.
- gold kind mix: theorem 1096 / definition 338 / instance 76 / structure 45 /
  class 21 / inductive 1. **instances can't be hard-dropped** (4.8% of gold).
- data hygiene: `kind` has dual spellings (thm/theorem,def/definition,…) —
  normalize first; `edge_type` has SIX values (sig 4.0M, proof 6.0M, def 1.2M,
  docref 51k, field 11.7k, extends 1.6k); `docstring` is ''-not-NULL for
  undocumented (test emptiness); `insufficient_context` is unusable as a gate
  (all-false on the only full-coverage slogan config 'formal'/qwen3-235b).

## Methodology (two-layer; adversarially hardened)
**Layer 1 — compiler-artifact GATE (binary, honest scope: NOT a plumbing filter;
drops ~0.65%, 100% gold recall; Nat.add/Eq.symm/instHAdd PASS):**
- normalized `kind` ∈ {theorem,definition,instance,structure,class,inductive,
  opaque,axiom}; drop constructor/ctor (2,424, 0 gold). (no 'lemma'/'abbrev'
  kinds exist here.)
- drop compiler-internal names ONLY: leading-underscore segment; final segment
  `match_`/`proof_`; autogen suffixes `injEq|sizeOf_spec|noConfusion|brecOn|
  ndrec|toCtorIdx`. (REMOVED from draft: numeric-segment clause = 0 hits dead
  code; `eq_` rule hit real gold `eq_pow_prime_of_unit_of_congruent`; bare
  `rec/recOn/casesOn` over-matched hand-written Quot.rec/Quotient.rec.)

**Layer 2 — saliency PRIOR (continuous; orders the sweep, NOT a hard cut; weights
LEARNED by logistic regression under leave-one-repo-out CV, not hand-set):**
- `doc_present_cohortnorm` — docstring presence minus stratum base rate.
- `semantic_quality` — max cosine of decl's slogan-embedding to the arXiv corpus
  (the NL↔FL space itself); rescues the 40.4% score-starved gold. **This is the
  match signal doubling as saliency.**
- `self_containment_selective` — ≥2 distinct gate-passing non-plumbing refs over
  sig+extends+field edges (vs frozen plumbing-hub blacklist). Validate AUC before
  weighting (draft's binary version fired on 99.2%).
- `kind_prior` — theorem/def high; **struct/class LOWERED** (they match worst
  downstream per §6a: structure recall@10 0.379 vs theorem 0.711).
- `glue_penalty` (negative) — `is_instance ∧ ¬doc`, extreme-tail sig-in-degree,
  glue-suffix name ∧ ¬doc. This is where semantic plumbing (Nat.add-class) is
  demoted; in-degree enters ONLY here, saturating-negative.

**Operating point** = constrained optimization: θ = LARGEST threshold s.t.
cross-validated gold recall ≥ R_floor (start 0.95, capped at the ~12-27% gold-noise
ceiling). Headline = SURVIVOR FRACTION at θ (reduction ratio), per stratum. Recall
is a CONSTRAINT, not the objective (a remove-filter trivially maxes recall by
keeping everything).

## Evaluation (the discovery payoff + rigor)
- **Negative/plumbing oracle** (draft had none): top sig-in-degree hubs; undocumented
  glue instances; glue-suffix lemmas; decls with no arXiv neighbor above the
  validated sim≥0.85 band. Report plumbing-LEAKAGE at θ.
- Per-stratum (Mathlib vs project) + leave-one-repo-out CV (cluster-bootstrap CI
  over the 16 repos, matching existing tooling). Report recall on the 40.4%
  score-starved slice separately.
- Mathlib transfer: independent positive set (100-theorems / Freek list /
  arXiv-cited Mathlib) since blueprint gold barely covers Mathlib.
- **Dual-rater precision audit** (Sonnet 4.5 + Haiku 4.5) on sampled high-cosine
  matches across saliency/class bands → precision vs saliency (the §6 n=45 protocol).

## Verified citations (read-first; full corpus in workflow `wqjio0273`)
| source | grounds |
|---|---|
| LeanSearch v2 (arXiv:2605.13137) | kind whitelist / OUTPUT_KINDS, is_internal, keep-instance-soft |
| loogle + doc-gen4 isBlackListed (github.com/nomeata/loogle) | compiler-internal name filter; gate is cleanup not plumbing |
| The Network Structure of Mathlib (arXiv:2604.24797) | in-degree dominated by Eq.refl/Nat plumbing → centrality trap |
| Milestone papers / time-balanced centrality (arXiv:1608.08414) | citation-PageRank age bias; raw in-degree biased to old/foundational |
| Entity salience (arXiv:2309.07990) | human-attention (docstring/abstract-presence) is the strongest cheap feature |
| Learning-assisted ATP w/ millions of lemmas (PMC4599631) | depends-on-prior-results (U/D recursion) = content signal |
| Blocking/filtering for entity resolution (arXiv:1905.06167) | recall-as-CONSTRAINT, PC/RR, accept false-negatives for reduction |
| Semantic Search over 9M theorems (arXiv:2602.05216, our prior) | slogan/embedding as content/popularity score |
| premise selection: LeanDojo (2306.15626), Magnushammer (2303.04488), LeanHammer (2506.07477) | "usefulness as premise" ≠ paper-worthiness (the trap import) |

## Must-remember
- RDS strictly READ-ONLY (`SET default_transaction_read_only=on`); results →
  gscratch/local JSONL only. `statement_formalization` (empty) is the intended
  NL↔FL edge home — DO NOT write it.
- klone compute nodes reach RDS (verified n3263) — query pgvector directly, no
  tunnel, no embedding download. `/usr/bin/python3.12` (system py3=3.6.8); no
  numpy/faiss → gscratch venv. ckpt partition (preemptible, unlimited walltime) —
  checkpoint/resume (skip done query-ids).
- RDS load: a few-hours / ~8–16 worker sweep is fine — design for truth, monitor,
  reevaluate (NOT minimal-load-at-all-costs).
- Subagent "live-DB" numbers are partially unreliable (contradicted each other) —
  re-verify every adopted number from `data/saliency_features.csv` or direct query.
- Reuse: `topk.embedding_topk` (read-only), `gold.load_gold`; SLURM template
  `experiments/leansearch_v2_replication/run_a1_batch.slurm`. Avoid `store.py` (writes RDS).

## Status
- [x] P0 access + reachability + graph characterization
- [x] P1 literature synthesis (read-first, citation-verified, adversarial) — `wqjio0273`
- [x] P2 saliency methodology designed + every adopted number re-verified from CSV
- [ ] P3 build: saliency-prior scorer (gate + composite ordering) + sweep worker
      (RDS-read → gscratch JSONL, saliency-ordered, checkpoint/resume) + ckpt SLURM
- [ ] P4 salloc single-shard validation → launch broad sweep (~383k, few hours)
- [ ] P5 evaluation: constrained-θ, negative-oracle precision, per-stratum, LORO,
      dual-rater audit, meaningful-match analysis

## Open Qs
- semantic_quality: chicken-and-egg — it needs the match (cosine to arXiv), so the
  sweep produces it. Use a cheap first pass (max top-1 cosine from the sweep) as the
  saliency feature, computed FROM sweep results, not before. ⇒ sweep is the
  primary compute; saliency prior for ordering uses only doc+kind+out-degree.
- K per query (10? 20?) — richer discovery vs output size.
- Worker count vs RDS health — start ~8, watch, scale toward 16.
