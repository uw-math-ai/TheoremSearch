/-
Candidate F — with-graph arm.

Blueprint (pfr / blueprint/src/chapter/entropy_pfr.tex:3):
  $\eta := 1/9$.

Same imports + target as no_graph.lean. Premises section surfaces the
7-decl pack predicted by the informal dependency graph — these are
all DOWNSTREAM consumers of η (theorems that take `(hpη : p.η = 1/9)`
as a hypothesis), since η itself is a prerequisite-side leaf
definition with no upstream dependencies.

This shape is genuinely different from candidates A/B (whose premise
packs are upstream definitions). For F, the graph signal is "here's
what wants η to exist."

Source: RDS candidate_attributes / formalization_candidate_neighborhood
joined at anchor 2d5ab52b (entropic_PFR_conjecture).
-/

import Mathlib.Tactic
-- The actual pfr modules that define the downstream consumers, so the
-- premise references below resolve.
import PFR.EntropyPFR
import PFR.TauFunctional
import PFR.FirstEstimate
import PFR.HundredPercent
import PFR.RhoFunctional

namespace PFR

-- ============================================================================
-- PREMISE PACK (informal-dep graph: downstream consumers of η)
-- ============================================================================

section Premises

example := @exists_isUniform_of_rdist_eq_zero
example := @first_estimate
example := @PFR_conjecture_aux
example := @rdist_triangle
example := @tau_minimizer_exists
example := @tau_strictly_decreases
example := @torsion_PFR_conjecture_aux

end Premises

-- ============================================================================
-- TARGET
-- ============================================================================

/-- η := 1/9 (PFR's parameter choice for the entropy iteration). -/
noncomputable def eta : ℝ := 1 / 9

end PFR
