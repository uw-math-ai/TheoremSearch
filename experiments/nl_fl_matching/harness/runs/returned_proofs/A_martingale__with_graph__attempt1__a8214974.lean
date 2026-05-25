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

noncomputable example := @IsCadlag
noncomputable example := @ProbabilityTheory.IsLocalMartingale
noncomputable example := @ProbabilityTheory.IsLocalSubmartingale
noncomputable example := @ProbabilityTheory.Locally
noncomputable example := @ProbabilityTheory.Locally.isCadlag
noncomputable example := @ProbabilityTheory.Locally.localSeq
noncomputable example := @ProbabilityTheory.IsLocalizingSequence
noncomputable example := @ProbabilityTheory.isLocalizingSequence_leastGE
noncomputable example := @ProbabilityTheory.Martingale.IsLocalMartingale

noncomputable example := @MeasureTheory.Integrable.classDL
noncomputable example := @MeasureTheory.Martingale.classDL
noncomputable example := @MeasureTheory.Submartingale.classDL
noncomputable example := @MeasureTheory.Submartingale.locally_classD
noncomputable example := @MeasureTheory.IsStoppingTime
noncomputable example := @MeasureTheory.stoppedProcess

noncomputable example := @ProbabilityTheory.ClassD.classDL
noncomputable example := @ProbabilityTheory.ClassD.uniformIntegrable'
noncomputable example := @ProbabilityTheory.ClassDL.hasLocallyIntegrableSup
noncomputable example := @ProbabilityTheory.ClassDL.locally_classD
noncomputable example := @ProbabilityTheory.classDL_iff_norm
noncomputable example := @ProbabilityTheory.HasLocallyIntegrableSup.locally_classDL
noncomputable example := @ProbabilityTheory.hasLocallyIntegrableSup_of_locally_classDL
noncomputable example := @ProbabilityTheory.isStable_classDL
noncomputable example := @ProbabilityTheory.isStable_isCadlag
noncomputable example := @ProbabilityTheory.isStable_martingale
noncomputable example := @ProbabilityTheory.isStable_submartingale
noncomputable example := @ProbabilityTheory.locally_classD_iff_hasLocallyIntegrableSup
noncomputable example := @ProbabilityTheory.locally_classD_iff_locally_classDL
noncomputable example := @ProbabilityTheory.locally_classDL_iff_hasLocallyIntegrableSup
noncomputable example := @ProbabilityTheory.locally_classD_of_locally_classDL

noncomputable example := @isBounded_image_of_isCadlag_of_isCompact

end Premises

-- ============================================================================
-- TARGET
-- ============================================================================

/-- A local martingale is a cadlag martingale if and only if it is of class DL.

## Proof sketch

**Forward (Martingale → ClassDL):**
From `hX : IsLocalMartingale X 𝓕 P`, the stopped processes `X^{τ_n}` are
martingale ∧ càdlàg. By `Martingale.classDL` each stopped process is ClassDL.
This gives `Locally (ClassDL · 𝓕 P) 𝓕 X P`. For any bounded stopping time
σ ≤ t and large enough n (where τ_n > t a.s.), the stopped value of X at σ
agrees with that of `X^{τ_n}`, so uniform integrability at level t transfers
from the stopped process to X. Similarly, ProgMeasurable lifts from the local
structure.

**Backward (ClassDL → Martingale):**
From `ClassDL X 𝓕 P`, we obtain `StronglyAdapted` via
`ClassDL.progMeasurable.stronglyAdapted`. For the conditional expectation
condition: by `hX`, the stopped processes `X^{τ_n}` are martingales satisfying
`E[X^{τ_n}_j | 𝓕_i] = X^{τ_n}_i` a.s. As `τ_n → ∞`, `X^{τ_n}_j → X_j`.
By ClassDL's uniform integrability the convergence is in L¹, and conditional
expectation is L¹-continuous, giving `E[X_j | 𝓕_i] = X_i` a.s.
-/
theorem IsLocalMartingale.martingale_iff_classDL
    (hX : IsLocalMartingale X 𝓕 P) :
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry

end ProbabilityTheory
