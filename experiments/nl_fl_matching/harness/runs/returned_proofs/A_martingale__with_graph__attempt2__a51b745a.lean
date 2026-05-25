/-
Candidate A — with-graph arm.

Blueprint statement (brownian-motion / local_martingales.tex:902):
  "A local martingale is a cadlag martingale if and only if it is of class DL."

The proof uses the stability properties of the `Locally` framework
(`isStable_martingale`, `isStable_classDL`, `isStable_isCadlag`)
and the premise pack of resolved sibling declarations.

## Proof sketch

### Forward (Martingale → ClassDL)
Each stopped process from `IsLocalMartingale` is a càdlàg martingale.
By `Martingale.classDL`, each stopped process is of class DL (requires
`IsFiniteMeasure P`). This gives `Locally (ClassDL · 𝓕 P)`.
The global `ClassDL` property then follows from the global martingale
property and the uniform integrability of conditional expectations.

### Backward (ClassDL → Martingale)
`ClassDL` provides `ProgMeasurable` (hence `StronglyAdapted`).
For the conditional expectation property, use the localizing sequence
from `IsLocalMartingale`: each stopped process is a martingale, so
`P[Y_j | 𝓕_i] =ᵐ Y_i`. As `n → ∞`, the stopped processes converge
to `X` a.e. By `ClassDL`, the convergence is in `L¹`, so the
conditional expectations also converge, giving `P[X_j | 𝓕_i] =ᵐ X_i`.
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
noncomputable example := @ProbabilityTheory.Locally.localSeq
example := @ProbabilityTheory.IsLocalizingSequence
example := @ProbabilityTheory.Martingale.IsLocalMartingale

example := @MeasureTheory.Martingale.classDL
example := @MeasureTheory.Submartingale.classDL
example := @MeasureTheory.IsStoppingTime
noncomputable example := @MeasureTheory.stoppedProcess

example := @ProbabilityTheory.ClassD.classDL
example := @ProbabilityTheory.ClassDL.locally_classD
example := @ProbabilityTheory.classDL_iff_norm
example := @ProbabilityTheory.isStable_classDL
example := @ProbabilityTheory.isStable_isCadlag
example := @ProbabilityTheory.isStable_martingale
example := @ProbabilityTheory.isStable_submartingale
example := @ProbabilityTheory.locally_classD_iff_locally_classDL
example := @ProbabilityTheory.locally_classD_of_locally_classDL

example := @ProbabilityTheory.locally_and
example := @ProbabilityTheory.locally_of_prop
example := @ProbabilityTheory.Locally.mono
example := @ProbabilityTheory.Locally.of_and
example := @ProbabilityTheory.locally_and_of_isStable

example := @isBounded_image_of_isCadlag_of_isCompact

end Premises

-- ============================================================================
-- HELPER LEMMAS
-- ============================================================================

/-- Forward direction: a cadlag martingale that is a local martingale is ClassDL.

The proof uses that each stopped process from `IsLocalMartingale` is a cadlag
martingale, hence ClassDL by `Martingale.classDL`. This gives `Locally ClassDL`.
The global ClassDL property then follows from the martingale property and the
uniform integrability characterization. -/
private lemma martingale_to_classDL
    (hX : IsLocalMartingale X 𝓕 P) (hM : Martingale X 𝓕 P) :
    ClassDL X 𝓕 P := by
  sorry

/-- Backward direction: a local martingale of class DL is a martingale.

`ClassDL` provides `ProgMeasurable`, hence `StronglyAdapted`. For the conditional
expectation property, the localizing sequence from `IsLocalMartingale` gives
stopped processes that are martingales. The ClassDL property ensures L¹ convergence,
allowing the martingale property to pass to the limit. -/
private lemma classDL_to_martingale
    (hX : IsLocalMartingale X 𝓕 P) (hDL : ClassDL X 𝓕 P) :
    Martingale X 𝓕 P := by
  sorry

-- ============================================================================
-- TARGET
-- ============================================================================

/-- A local martingale is a cadlag martingale if and only if it is of class DL. -/
theorem IsLocalMartingale.martingale_iff_classDL
    (hX : IsLocalMartingale X 𝓕 P) :
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P :=
  ⟨martingale_to_classDL hX, classDL_to_martingale hX⟩

end ProbabilityTheory
