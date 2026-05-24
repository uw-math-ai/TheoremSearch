# Prover Comparison Harness (proof-only, Aristotle)

**Goal.** For each smoke-test target ([`smoke_test_candidates.md`](./smoke_test_candidates.md)),
run the same Lean goal through Aristotle in two arms:
- **(no-graph)** Lean file = project imports + target with `sorry`.
- **(with-graph)** same file + a curated **premise pack** listing the
  resolved k=1 informal-dep siblings (decl_name + type signature, pulled
  from the project's `*.lean` source).

If with-graph succeeds materially more often than no-graph on a fixed
budget, the cross-graph dependency context demonstrably helps the prover.

Scope is intentionally narrow: **proof only.** We hand-write the Lean
type signature for both arms; the only thing that varies is the ambient
context around the goal.

## Why this isolates the graph's contribution

Aristotle has Mathlib in scope by default and runs its own
search/retrieval internally. The **with-graph** arm doesn't supply more
*Lean knowledge* — it supplies the **exact subset of project lemmas the
informal dependency graph predicts are relevant**. If our graph-derived
shortlist beats Aristotle's internal search, then the cross-graph
dependency edges carry real signal a generic prover can't recover on
its own.

This matches the unexplored gap identified in the lit sweep: Aria,
ProofFlow, DDR, CRAMF all derive premises from the **target statement
alone**; none use a pre-built cross-paper informal graph
([[reference-autoformalization-litsweep-2026-05]] for the bibliography).

## File template

Each candidate ships as two `.lean` files in
`experiments/nl_fl_matching/harness/<candidate-id>/`:

```
no_graph.lean       -- minimal: imports + target + sorry
with_graph.lean     -- imports + premise pack + target + sorry
```

### `no_graph.lean` shape

```lean
import <project_root_module>
-- import only the files transitively needed for the target's types

open MeasureTheory ProbabilityTheory

namespace BrownianMotion  -- or pfr

variable {ι Ω E : Type*} [PartialOrder ι] {mΩ : MeasurableSpace Ω}
  [NormedAddCommGroup E] [NormedSpace ℝ E] [CompleteSpace E]
  {X : ι → Ω → E} {𝓕 : Filtration ι mΩ} {P : Measure Ω}

/-- {target's LaTeX statement as a docstring} -/
theorem <target_name> :
    <target type> := by
  sorry

end BrownianMotion
```

### `with_graph.lean` shape

```lean
import <project_root_module>

open MeasureTheory ProbabilityTheory

namespace BrownianMotion

variable ...  -- same as no_graph.lean

-- Premise pack: k=1 resolved siblings from the informal dep graph.
-- (These are already in scope via `import` — listed here only to mark
--  them as RELEVANT to the goal below.)
example : ∀ X 𝓕 P, IsLocalMartingale X 𝓕 P → ... := IsLocalMartingale.locally_progMeasurable
example := @ClassDL.classD
example := @Submartingale.classDL
-- (etc., one line per resolved k=1 sibling)

/-- {target's LaTeX statement} -/
theorem <target_name> :
    <target type> := by
  sorry

end BrownianMotion
```

The `example := @decl` form is enough to tell Aristotle "this lemma
matters" without re-proving it — Aristotle can dereference and inspect
the signature.

## The 3 targets (draft Lean signatures)

The signatures below are **first-pass translations from the blueprint
LaTeX**. They will need adjustment against the project's actual variable
conventions; treat as starting points.

### A — `IsLocalMartingale.martingale_iff_classDL`

```lean
import BrownianMotion.StochasticIntegral.LocalMartingale
import BrownianMotion.StochasticIntegral.ClassD
import BrownianMotion.StochasticIntegral.Cadlag

open MeasureTheory ProbabilityTheory

variable {ι Ω E : Type*} [PartialOrder ι] {mΩ : MeasurableSpace Ω}
  [NormedAddCommGroup E] [NormedSpace ℝ E] [CompleteSpace E]
  {X : ι → Ω → E} {𝓕 : Filtration ι mΩ} {P : Measure Ω}

/-- A local martingale is a cadlag martingale iff it is of class DL. -/
theorem IsLocalMartingale.martingale_iff_classDL
    (hX_loc : IsLocalMartingale X 𝓕 P)
    (hX_cadlag : ∀ ω, IsCadlag (X · ω)) :
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry
```

Premise pack (resolved k=1 siblings, exact decl names pulled from
`formalization_candidate_neighborhood` rows where
`anchor_statement_id = ff18ba56...` and `status = 'resolved'`):
- `BrownianMotion.IsLocalMartingale` (the def)
- `BrownianMotion.IsCadlag` (the structure)
- `BrownianMotion.ClassDL` (the structure)
- `MeasureTheory.Submartingale.classDL`
- `MeasureTheory.Martingale.classDL`
- `BrownianMotion.ClassDL.classD`
- `BrownianMotion.locally_classD_of_locally_classDL`
- … (full list in the harness output)

### B — `IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative`

```lean
/-- A nonnegative local submartingale is a cadlag submartingale iff it
is of class DL. -/
theorem IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative
    (hX_loc : IsLocalSubmartingale X 𝓕 P)
    (hX_cadlag : ∀ ω, IsCadlag (X · ω))
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω) :
    Submartingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry
```

Premise pack overlaps heavily with A. Run B second to amortize the
ambient cache.

### F — `eta := 1/9` (control)

```lean
namespace PFR

/-- η := 1/9 (Polynomial Freiman-Ruzsa parameter choice). -/
noncomputable def eta : ℝ := 1 / 9

end PFR
```

Trivial. Both arms should succeed instantly. If either fails, the
harness has a bug.

## Aristotle wiring

We don't run Aristotle locally — it's a hosted prover at
`aristotle.harmonic.fun`. Two access patterns:

1. **MCP server** ([`septract/lean-aristotle-mcp`](https://github.com/septract/lean-aristotle-mcp)).
   Submit a `.lean` file with `sorry`s; Aristotle returns the same file
   with `sorry`s replaced (or failure). Lets us inject arbitrary
   imports/lemmas — fits our harness directly.
2. **Direct API.** Same payload shape, just no MCP wrapper.

Either way, each candidate gets:
- 1 attempt per arm at a fixed compute budget (start with the API's
  default; record wall-time + token usage).
- 3 repetitions per (candidate, arm) to estimate run-to-run variance.

## Success metrics

For each (candidate, arm, repetition):

| metric | meaning |
|---|---|
| `compiles` | Lean accepts the returned file with no errors. **Hard requirement.** |
| `sorry_free` | No `sorry` remains in the target's proof body. |
| `axiom_free` | `#print axioms <target>` shows only the standard Lean axioms (no `sorryAx`, no `Classical.choice` beyond what's already in deps). |
| `wall_time_s` | End-to-end time including any internal search. |
| `tokens_used` | If exposed by the API. |

The headline number is `% of arms where (compiles ∧ sorry_free ∧ axiom_free) = True`.

**Bonus metric (qualitative):** if both arms succeed, compare the
returned proofs against each other and against the blueprint's intended
proof (when available). Does the with-graph arm use the supplied
premises explicitly, or does it find its own path? This informs the
paper's discussion of *why* the graph helps (premise hint vs. search-space
narrowing).

## Budget envelope

| step | cost |
|---|---|
| 3 candidates × 2 arms × 3 reps = 18 Aristotle calls | Aristotle is closed-source; assume ~$0.50–$2 / call. Worst case ~$36. |
| File preparation (manual signature drafting) | ~1 hour wall to refine the 3 signatures against the project's actual variable conventions. |
| Result analysis | ~1 hour. |

Cheap. Run it.

## What this does NOT measure (deferred)

- **Full autoformalization** (LaTeX → Lean statement). Our scope is
  proof-only; the user can supply the signature. Folded in for cycle 2.
- **k=2 graph context.** Only k=1 premises in the smoke test. If
  with-graph wins clearly, the next ablation is k=1 vs k=2 vs k=1+k=2.
- **Different prover.** Aristotle only; LeanDojo-v2 / Kimina / COPRA
  comparisons are paper-table material, not smoke-test.
- **arXiv anchors.** Smoke test stays within blueprint pool. Cycle 2
  extends to arXiv anchors whose informal deps land in Mathlib.

## Files to create when running

- `experiments/nl_fl_matching/harness/A_martingale_iff_classDL/{no_graph,with_graph}.lean`
- `experiments/nl_fl_matching/harness/B_submartingale_iff_classDL/{no_graph,with_graph}.lean`
- `experiments/nl_fl_matching/harness/F_eta_def/{no_graph,with_graph}.lean`
- `experiments/nl_fl_matching/harness/run_aristotle.py` — orchestrator that submits each file, records results to RDS table `prover_run` (DDL TBD).
- `experiments/nl_fl_matching/harness/results.md` — human-readable summary after the run.
