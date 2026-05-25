# Cycle-1 smoke-test findings

**Status:** preliminary. N = 2 candidates × 2 arms × ≤2 attempts each (5 unique runs after dropping 2 canceled subagent retries). Not powered to detect a graph-conditioning effect; the purpose was to surface design questions for cycle 2.

## What ran

Two `iff` theorems from the brownian-motion blueprint that have no formalization yet but whose siblings exist in Mathlib + the project:

- **A** = `IsLocalMartingale.martingale_iff_classDL` (blueprint `local_martingales.tex:902`)
- **B** = `IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative` (`local_martingales.tex:913`)

Each was submitted to Aristotle under two arms:
- `no_graph`: bare `theorem … := by sorry` + project imports.
- `with_graph`: same skeleton + a "premise pack" of ~35 sibling decl names predicted relevant by the informal-dep graph (RDS table `formalization_candidate_neighborhood`).

## What came back

| run | candidate | arm | terminal | sorries init→final | what Aristotle did |
|---|---|---|---|---|---|
| `ddb6ae7f` | A | no_graph | **OUT_OF_BUDGET** | 1 → 2 | redefined `ClassDL` as a local structure, proved **3 helper lemmas** (`stopped_process_eq_of_lt`, `ae_tendsto_stopped_of_localizing` via `filter_upwards`+`WithTop`, `ClassDL.integrable` via `UniformIntegrable.memLp`), structured the iff as composition of two stubs |
| `a8214974` | A | with_graph #1 | partial | 1 → 1 | added a detailed English "## Proof sketch" docstring, no Lean change |
| `a51b745a` | A | with_graph #2 | partial | 1 → 2 | pruned premise pack slightly, structured iff as composition of `martingale_to_classDL` / `classDL_to_martingale` — both stubs |
| `ac0d5abc` | B | no_graph | partial | 1 → 3 | decomposed iff into 5 sub-goals inline, **closed 2** (`hDL.progMeasurable.stronglyAdapted` for `StronglyAdapted`; `hUI.memLp` chain for `Integrable t`), 3 sorries with substantive English direction |
| `5cd4e9d0` | B | with_graph | partial | 1 → 3 | built a 4-helper-lemma scaffold, **closed 1** (`stoppedProcess_eq_of_lt_tau` via `simp+aesop`), tried to close `integrable_of_classDL` but the body contains literal `exact?` calls (search trace, not valid Lean — hence COMPILE_WITH_ERRORS) |

CANCELED projects `12bc15a7`, `c90184df` returned the input file unmodified, so no information beyond "Aristotle saw the prompt and didn't get to work."

## Calibration findings (the actual cycle-1 takeaways)

### 1. The `sorry` count delta is a misleading top-line metric.

The B no_graph result *introduced* 2 new `sorry`s (1 → 3) by decomposing the goal into 5 sub-goals, but it also **closed 2 of those sub-goals inline** — net work is positive. Compare:

- `ClassDL` requires `ProgMeasurable ∧ ∀ t, UniformIntegrable …` (a conjunction); Aristotle proved the `Integrable t` half from `UniformIntegrable.memLp`.
- It used `hDL.progMeasurable.stronglyAdapted` directly to discharge the `StronglyAdapted` premise of `Submartingale`.

A reporting metric of "fraction of *introduced* sub-goals closed" would have caught this; `sorry` delta does not. **Action for cycle 2:** trajectory analyzer should compute (sub-goals introduced, sub-goals closed) per run, not just total sorries.

### 2. The most substantive Lean came from `no_graph`, not `with_graph`.

`ddb6ae7f` (A no_graph) hit OUT_OF_BUDGET *during* a deep proof attempt — 3 helper lemmas proved, both directions structured. The two A with_graph attempts produced English sketches and stubs. This is N=1 per cell so we can't claim graph-conditioning *hurts*, but it does mean: **the premise pack is not a free win.** Possible explanations to test in cycle 2:

  - Aristotle spent a lot of its initial budget *elaborating the premise pack*, leaving less for proof search.
  - The pack is too long (~35 decls); 5–10 with manual curation may produce different behavior.
  - The pack contains structurally-similar but mutually-redundant entries (e.g., 4 different `locally_classD*` variants), which crowds out attention.
  - With_graph's value may show up in *which* tactics Aristotle reaches for (e.g., it tried `Martingale.classDL` and `classDL_of_martingale` more often in `5cd4e9d0`) — needs a tool-call-pattern analysis we don't yet have.

### 3. Aristotle has 3 new terminal statuses we hadn't planned for.

Beyond `PROVED` / `FAILED`, real runs surface `COMPLETE_WITH_ERRORS`, `OUT_OF_BUDGET`, and `CANCELED`. The harness now maps these to `partial`, `out_of_budget`, `canceled`; the promote.py schema and any downstream analysis must accept them.

### 4. Aristotle sometimes returns search traces verbatim.

`5cd4e9d0` contains lines like `convert ... using 1 <;> norm_num; · exact?;`. The `exact?` is a Lean tactic for *interactive search* — not a valid finished proof. This appears to be Aristotle dumping a partial trace into the file when it ran out of compute. The harness should detect this (`exact?` / `apply?` / `decide?` substrings in `final_lean_source`) and report it separately from clean partial results.

### 5. /tmp is hostile to overnight runs.

Klone wiped `/tmp/simku22` overnight (warned about this; saved digests + tarballs to `/gscratch` first). Aristotle projects kept running server-side fine (30-day retention), but every local rescue process died — we lost trajectory streams for 4 of the 5 runs. `rescue.py` should write its progress log and final digest under `/gscratch/.../runs/` directly, not `/tmp/`. Lake worktrees can stay in `/tmp` (re-cloneable).

## Sample-size recommendations for cycle 2

The N=2 result is dominated by run-to-run variance: the two A with_graph attempts produced *qualitatively different* proofs (one English-only, one a stub composition), and B's with_graph used `exact?` traces while no_graph did not. Cycle 2 should:

- Same candidate × same arm, **5 attempts** (to characterize run-to-run variance).
- **5 candidates** spanning at least 3 math categories.
- **Both directions of the comparison** (premise-pack vs. minimal vs. *random* siblings) to test whether any structured premise list helps regardless of graph-derivation.

That's 5 × 5 × 3 = 75 Aristotle runs. At ~12k tokens in / 500 tokens out per subagent (observed B no_graph), well within the free preview tier's apparent capacity (we ran 7 concurrent without issue).
