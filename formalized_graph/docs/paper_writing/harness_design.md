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

## Agent-driven harness (revised 2026-05-24)

The original design (one-shot `aristotle submit` per arm, recorded as
pass/fail) has been superseded by a **subagent-driven** harness. For each
(candidate, arm), a Claude subagent (`claude-sonnet-4-6`) drives the
proof via a tool-use loop:

```
   read_target_file → [optional] lean_typecheck → aristotle_submit
       ↓ (if PARTIAL/FAILED)
   write_target_file (adjust hint) OR aristotle_ask → aristotle_submit
       ↓
   report_final (status + summary)
```

The full conversation — every tool call, every tool result, every
Aristotle stdout line — is appended to a JSONL trajectory file. **The
trajectory is the experimental data**, not just the binary pass/fail.

**Code lives at `experiments/nl_fl_matching/harness/`:**
- `subagent.py` — the per-arm agent loop (Anthropic SDK)
- `orchestrator.py` — sweeps the agent across (candidate, arm) pairs
- `tools.py` — Python wrappers around the aristotle CLI + local file IO
- `promote.py` — post-run: filter "good" trajectories and write digests to RDS `prover_run`
- `prover_run_schema.sql` — RDS DDL for the results table

**Per-(candidate, arm) budget enforced in `subagent.py`:**
- `MAX_ARISTOTLE_SUBMITS = 2`
- `MAX_ARISTOTLE_ASKS = 1`
- `MAX_TURNS = 25` (Claude turns; safety cap against loops)

The Aristotle CLI itself exposes no client-side cost / time / iteration
caps — we'll measure empirically and tighten if needed.

**Why subagent-driven, not one-shot:**
- Captures *trajectory* as data — premise picks, hint adjustments,
  retry counts — not just terminal status.
- Validates the actual "Claude prompts Aristotle" production pattern
  recommended by Harmonic.
- Lets the same harness scale from 3 smoke-test candidates to all 326
  in `candidate_attributes` without human intervention.

The "no_graph vs with_graph" comparison stays clean because the only
input that differs between arms is the staged `.lean` file. The agent
loop, system prompt, budget, and tool set are identical. Don't try to
make the agent "help" the with-graph arm by injecting extra premises
mid-loop — the premise pack is fixed at staging time.

## Aristotle wiring (CLI surface — for reference)

Hosted prover at `aristotle.harmonic.fun`. Public docs sit behind Auth0;
the design below is grounded in `aristotlelib` 2.0.0 (PyPI 2026-05-14),
the [`septract/lean-aristotle-mcp`](https://github.com/septract/lean-aristotle-mcp)
community server, the [Aristotle paper](https://arxiv.org/html/2510.01346v1),
and the [harmonic-ai/IMO2025](https://github.com/harmonic-ai/IMO2025) repo.

**Two surfaces, both used:**

1. **MCP server** for Claude-orchestrated runs. `claude mcp add aristotle …`
   exposes 6 tools (`prove`, `prove_file`, `formalize`, `check_*`). Good
   for the per-candidate orchestration loop.
2. **`aristotlelib` CLI** (`aristotle submit "Fill the sorry" --project-dir <path> --wait`)
   for **non-Mathlib Lake projects** — our target imports `BrownianMotion.*`,
   and MCP `prove_file` doesn't accept an external `--project-dir`. The CLI
   does. Claude can shell out to it.

**Submission model — important constraints:**

- Aristotle attacks **every `sorry`** in the submitted file. So the target
  must live in a minimal file with exactly one `sorry`. Our `no_graph.lean`
  / `with_graph.lean` already meet this.
- The status enum is `queued | in_progress | proved | partial | failed | error`.
  `partial` means some sorries closed — relevant if we ever submit a
  sketch with intermediate `have … := by sorry` lemmas.
- **No premise-list API exists.** `context_files` (extra Lean files made
  available as imports) and a free-text `hint` string are the only structured
  channels. The `example := @decl` lines in `with_graph.lean` are the
  right pattern — confirmed by §2.2.1 of the paper, which notes the
  proof-search model benefits from background results placed in the
  initial code block.
- **Auth:** `ARISTOTLE_API_KEY` env var, generated in Dashboard → API Keys.
- **Latency:** "few minutes to several hours" per job. MCP server warns
  against tight polling — use `wait=False` + `check_prove_file` on a
  slow cadence.

**Per-candidate plan:**
- 1 attempt per arm at the API's default budget (record wall-time, status,
  returned source).
- 3 repetitions per (candidate, arm) to estimate run-to-run variance.

## Toolchain risk

Our targets pin `leanprover/lean4:v4.29.0`. Harmonic's most recent public
artifact (IMO2025) is on `v4.20.0-rc5` — ~9 minor releases behind. The
proof-search models are trained on tactic surface as of mid-2025;
expect possible tactic-drift on `v4.29.0`.

**Mitigations, in order:**
1. Just try v4.29.0 first. May work fine; tactic surface hasn't churned
   that hard.
2. If results look noisy, stand up a parallel v4.20.x sandbox (downgrade
   the brownian-motion checkout — `git checkout` an earlier tag) and run
   candidate A there to A/B the toolchain effect.
3. The MCP server instructions explicitly require `import Mathlib.Tactic`
   at the top of the file — added to both arms in our `.lean` files.

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

- `experiments/nl_fl_matching/harness/A_martingale_iff_classDL/{no_graph,with_graph}.lean` ✅ landed.
- `experiments/nl_fl_matching/harness/B_submartingale_iff_classDL/{no_graph,with_graph}.lean`
- `experiments/nl_fl_matching/harness/F_eta_def/{no_graph,with_graph}.lean`
- `experiments/nl_fl_matching/harness/run_aristotle.py` — orchestrator that submits each file, records results to RDS table `prover_run` (DDL TBD).
- `experiments/nl_fl_matching/harness/results.md` — human-readable summary after the run.

## Operator setup (one-time)

```bash
# 1. API key
export ARISTOTLE_API_KEY=…   # from Dashboard → API Keys

# 2. CLI sanity check
uvx --from aristotlelib@latest aristotle --version

# 3. MCP wiring for Claude
claude mcp add aristotle \
    -e ARISTOTLE_API_KEY=$ARISTOTLE_API_KEY \
    -- uvx --from git+https://github.com/septract/lean-aristotle-mcp aristotle-mcp
claude mcp list   # confirm aristotle is registered

# 4. Warm the brownian-motion build cache (once)
cd /tmp/simku22/repos/brownian-motion
lake build
```

For the v4.20 compatibility sandbox (if needed):
```bash
git -C /tmp/simku22/repos/brownian-motion checkout <earlier-v4.20-tag>
lake build
```
