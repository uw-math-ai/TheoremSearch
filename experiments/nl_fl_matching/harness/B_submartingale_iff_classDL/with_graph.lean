/-
Candidate B — with-graph arm.

Blueprint (brownian-motion / local_martingales.tex:913):
  "A nonnegative local submartingale is a cadlag submartingale if and
   only if it is of class DL."

Same imports + target as no_graph.lean. The Premises section below
surfaces the 35-decl premise pack predicted by the informal dependency
graph (RDS candidate_attributes / formalization_candidate_neighborhood
joined across the 3 anchors that have target B as a k=1 informal-dep
neighbor:
  - 148afe52  (anchor ProbabilityTheory.ClassDL)
  - 2ce4e288  (anchor ProbabilityTheory.IsLocalSubmartingale)
  - ff18ba56  (anchor IsCadlag)
The decls are already in scope via the project imports — the
`example := @decl` lines mark them as relevant for the prover.
-/

import Mathlib.Tactic
import BrownianMotion.StochasticIntegral.LocalMartingale
import BrownianMotion.StochasticIntegral.ClassD
import BrownianMotion.StochasticIntegral.Cadlag

open MeasureTheory

namespace ProbabilityTheory

variable {ι Ω : Type*}
  [LinearOrder ι] [OrderBot ι] [TopologicalSpace ι] [OrderTopology ι]
  [MeasurableSpace ι] [BorelSpace ι]
  {mΩ : MeasurableSpace Ω} {P : Measure Ω}
  {X : ι → Ω → ℝ} {𝓕 : Filtration ι mΩ}

-- ============================================================================
-- PREMISE PACK (informal-dep graph predicts these are relevant)
-- ============================================================================

section Premises

example := @IsCadlag
example := @ProbabilityTheory.IsLocalMartingale
example := @ProbabilityTheory.IsLocalSubmartingale
example := @ProbabilityTheory.IsLocalSubmartingale.doob_meyer
example := @ProbabilityTheory.IsLocalSubmartingale.locally_classD
example := @ProbabilityTheory.Locally
example := @ProbabilityTheory.Locally.isCadlag
example := @ProbabilityTheory.Locally.localSeq
example := @ProbabilityTheory.IsLocalizingSequence
example := @ProbabilityTheory.isLocalizingSequence_leastGE
example := @ProbabilityTheory.Martingale.IsLocalMartingale
example := @ProbabilityTheory.IsLocalMartingale.isLocalSubmartingale_sq_norm

example := @MeasureTheory.Integrable.classDL
example := @MeasureTheory.Martingale.classDL
example := @MeasureTheory.Submartingale
example := @MeasureTheory.Submartingale.classDL
example := @MeasureTheory.Submartingale.locally_classD
example := @MeasureTheory.IsStoppingTime
example := @MeasureTheory.stoppedProcess

example := @ProbabilityTheory.ClassD.classDL
example := @ProbabilityTheory.ClassD.uniformIntegrable'
example := @ProbabilityTheory.ClassDL.hasLocallyIntegrableSup
example := @ProbabilityTheory.ClassDL.locally_classD
example := @ProbabilityTheory.classDL_iff_norm
example := @ProbabilityTheory.HasLocallyIntegrableSup.locally_classDL
example := @ProbabilityTheory.hasLocallyIntegrableSup_of_locally_classDL
example := @ProbabilityTheory.isStable_classDL
example := @ProbabilityTheory.isStable_isCadlag
example := @ProbabilityTheory.isStable_martingale
example := @ProbabilityTheory.isStable_submartingale
example := @ProbabilityTheory.locally_classD_iff_hasLocallyIntegrableSup
example := @ProbabilityTheory.locally_classD_iff_locally_classDL
example := @ProbabilityTheory.locally_classDL_iff_hasLocallyIntegrableSup
example := @ProbabilityTheory.locally_classD_of_locally_classDL

example := @isBounded_image_of_isCadlag_of_isCompact

end Premises

-- ============================================================================
-- TARGET
-- ============================================================================

/-- A nonnegative local submartingale is a cadlag submartingale if and
only if it is of class DL. -/
theorem IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω) :
    Submartingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry

end ProbabilityTheory
