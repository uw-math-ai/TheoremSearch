# graph_prover — compiler-in-the-loop, graph-conditioned premise selection

**Claim under test:** compiler-conditioned graph traversal (typed-edge expansion +
informal→formal jumps, retrieval *mutated* across retries on compile outcomes) closes
more held-out Lean theorems at a fixed budget than static semantic top-K.

Motivation: the Google proof-search agent (arXiv 2605.22763) has no premise
retrieval at all, and its own discussion pins success on library maturity +
decomposability; our static retrieval tuning demonstrably does not transfer to
premise retrieval (MathlibMPR 0.190 → 0.142 with more levers), and our earlier
compiler-loop experiment showed a *static* premise pool primes premature convergence
(`../lean_premise_retrieval/docs/compiler_loop_results.md`, finding #3). The missing
piece is retrieval that reacts to the compiler.

This package is a THIN experiment layer: it reuses `../lean_premise_retrieval/`
(FormalRetriever, frozen splits, gold labels, typecheck harness, RDS credential path)
and copies three battle-tested pieces from `../leansearch_v2_replication/eval_mpr.py`
(GRAPH_EXPAND_SQL, TRIGRAM_SQL, the Nebius query-embedding path) with attribution
headers. Nothing outside this directory is modified.

## Arms

| arm | retrieval | premise pool across the K=6 attempts |
|---|---|---|
| A | semantic top-30 (target's own slogan vector) | static |
| B | A + typed one-hop graph expansion, RRF-fused | static |
| C | B + informal→formal `graph_pack` (INTEGRATION.md spec) | static |
| D | C, then one compiler-conditioned mutation per retry | mutated |
| E | C, then one 4-wide beam round (each mutation a branch) + 1 final | beam |
| A-shuffled | A premises from a *different* task | negative control |

Mutations (priority order): `trigram-repair` (unknown identifiers → pg_trgm name
search), `error-requery` (embed error text + sketch), `forbid-tried` (offered ≥2
failed attempts, never used → excluded), `seed-swap` (cosine ranks 16–30 + toggled
edge set).

Budget: **6 compile attempts per task per arm** (E: 1+4+1). Reward is proof-level
only: compiles / sorry-free (`#print axioms`, permitted {propext, Quot.sound,
Classical.choice}) / kernel used-constants self-citation gate / error count / $.

Primary metric: **sorry-free proof rate per dollar**. Secondary: compile rate,
premise recall@30 vs gold `proof`-edge deps, fraction of used premises first surfaced
via a graph path, McNemar pairwise.

## Data & environment prerequisites (researcher machine / Hyak — NOT a bare clone)

- `../lean_premise_retrieval/cache/`: `formal_emb.f16.npy` (~3.2 GB), `formal_ids.json`,
  `decl_names.json`, `slogans.pkl`, `split.json`, `ml429_namesigs.tsv`
  (rebuildable via `make index split` + `build_metadata.py` there, or scp)
- `../lean_premise_retrieval/.env`: AWS keys + `RDS_SECRET_ARN` + `RDS_HOST`
  (+ `NEBIUS_API_KEY`)
- `LPR_MATHLIB_DIR`: a **built** Lean project with `import Mathlib`
- `ANTHROPIC_API_KEY`; prover model via `GP_PROVER_MODEL`
  (default `claude-sonnet-4-6`, matching the lean_premise_retrieval formalization
  experiment for comparability)
- `GP_EDGE_TYPES`: set from the edge-census spike result (default `sig,extends,field`)

## Run order

```bash
# 0. spikes — these DECIDE parameters, run them first
python -m experiments.graph_prover.spikes.edge_census
python -m experiments.graph_prover.retrieval.graph_pack --pilot   # arm C coverage

# selftests (masking + parsing are pure-python; check_proof needs the Mathlib build)
python -m experiments.graph_prover.scripts.build_tasks --selftest
python -m experiments.graph_prover.prover.attempt --selftest
python -m experiments.graph_prover.retrieval.mutations --selftest
python -m experiments.graph_prover.compile.check_proof --selftest

# 1. task mining (val first)
python -m experiments.graph_prover.scripts.build_tasks --split val
python -m experiments.graph_prover.scripts.build_forbidden --split val

# 2. smoke: one task through arm A end-to-end
python -m experiments.graph_prover.spikes.smoke_arm_a

# 3. calibrate on val (arm A + shuffled control first, then the ladder)
python -m experiments.graph_prover.scripts.run_experiment --split val \
    --arms A,A-shuffled --limit 30 --run-id val-cal
python -m experiments.graph_prover.scripts.run_experiment --split val \
    --arms A,B,C,D,E --run-id val0

# 4. score
python -m experiments.graph_prover.scripts.score --run-id val0

# 5. frozen test run (once, after val calibration)
python -m experiments.graph_prover.scripts.build_tasks --split test
python -m experiments.graph_prover.scripts.build_forbidden --split test
python -m experiments.graph_prover.scripts.run_experiment --split test \
    --arms A,B,C,D,E --run-id test0
python -m experiments.graph_prover.scripts.score --run-id test0
```

Runs are resumable: `run_experiment` skips (task, arm) pairs already present in the
run directory's JSONL.

## Verification gates (approved plan)

- hard assert at retrieval time: no pool candidate in the forbidden set
  (`retrieval/arms.py::_assert_no_leak`), plus the offline audit column in `score.py`
- kernel used-constants **self-citation gate** in `compile/check_proof.py` — a proof
  citing the masked target or its reverse-deps is not "solved"; selftest case 4 is the
  canary (`exact Nat.add_zero` with `Nat.add_zero` forbidden must be rejected)
- **shuffled-premise control**: if A-shuffled ≈ A on solve rate, the prover ignores
  premises and the arm contrast is void
- mining gate: every masked statement must typecheck with `sorry` at mining time

## Known risks / fallbacks (from the approved plan)

1. `extends`/`field` empty in live RDS → `GP_EDGE_TYPES=sig,proof` (spike decides).
2. `formalization_candidate_neighborhood` coverage thin for random Mathlib targets →
   graph_pack pilot detects; fallback = blueprint `informal_metadata.lean` bridges;
   report C on the covered subset, headline on B/D/E.
3. Tasks too hard at K=6 → tighten `--max-proof-lines`; per-dollar metric tolerates
   low absolute rates if the contrast is significant.
4. `run_cmd` used-constants probe fails on the pinned toolchain → automatic
   string-match fallback (recorded as `used_constants_source="string-match"`), and ban
   on `exact?`/`apply?` in the prover prompt is the degraded defense.
5. D < A on val (premature convergence recurs even with churn) → that is itself a
   paper-relevant negative result; report it.

## Phase two (later, in autoformalizing-benchmarks)

Thin CLI `formalization-workflow/scripts/premise_search.py` wrapping arms B/C/D;
adopted premises register through `register_overlay.py` (already a compiler-verified
premise gate); demo on 20–50 unformalized FormalLemmaBench lines with full provenance
traces. See the approved plan for details.
