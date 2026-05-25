/-
Candidate A — with-graph arm.

Blueprint statement (brownian-motion / local_martingales.tex:902):
  "A local martingale is a cadlag martingale if and only if it is of class DL."

Same imports + same target as no_graph.lean. The only difference is the
PREMISE PACK section below: the 35 resolved-sibling decl names predicted
by the informal dependency graph as relevant to this goal. They are
already in scope via the imports — the `example := @decl` lines exist
only to surface them as candidate premises for the prover.

Source of the premise pack: RDS table `formalization_candidate_neighborhood`
on db v2, joined across the 3 anchors that have target A
(b8f7c652) as a k=1 informal-dep neighbor:
  - 148afe52 (anchor "ProbabilityTheory.ClassDL")
  - 3d6042b2 (anchor "ProbabilityTheory.IsLocalMartingale")
  - ff18ba56 (anchor "IsCadlag")
-/

import Mathlib.Tactic
import BrownianMotion.StochasticIntegral.LocalMartingale
import BrownianMotion.StochasticIntegral.ClassD
import BrownianMotion.StochasticIntegral.Cadlag

open MeasureTheory

namespace ProbabilityTheory

variable {ι Ω E : Type*}
  [LinearOrder ι] [OrderBot ι] [TopologicalSpace ι] [OrderTopology ι]
  [MeasurableSpace ι] [BorelSpace ι]
  [NormedAddCommGroup E] [NormedSpace ℝ E] [CompleteSpace E]
  {mΩ : MeasurableSpace Ω} {P : Measure Ω}
  {X : ι → Ω → E} {𝓕 : Filtration ι mΩ}

-- ============================================================================
-- PREMISE PACK (informal-dep graph predicts these are relevant)
-- ============================================================================

section Premises

example := @IsCadlag
example := @ProbabilityTheory.IsLocalMartingale
example := @ProbabilityTheory.IsLocalSubmartingale
example := @ProbabilityTheory.Locally
example := @ProbabilityTheory.Locally.isCadlag
example := @ProbabilityTheory.Locally.localSeq
example := @ProbabilityTheory.IsLocalizingSequence
example := @ProbabilityTheory.isLocalizingSequence_leastGE
example := @ProbabilityTheory.Martingale.IsLocalMartingale
example := @ProbabilityTheory.IsLocalMartingale.isLocalSubmartingale_sq_norm
example := @ProbabilityTheory.IsLocalSubmartingale.doob_meyer
example := @ProbabilityTheory.quadraticVariation

example := @MeasureTheory.Integrable.classDL
example := @MeasureTheory.Martingale.classDL
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

/-- A local martingale is a cadlag martingale if and only if it is of class DL. -/
theorem IsLocalMartingale.martingale_iff_classDL
    (hX : IsLocalMartingale X 𝓕 P) :
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry

end ProbabilityTheory
