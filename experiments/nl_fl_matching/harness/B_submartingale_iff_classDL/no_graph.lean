/-
Candidate B — no-graph arm.

Blueprint (brownian-motion / local_martingales.tex:913):
  "A nonnegative local submartingale is a cadlag submartingale if and
   only if it is of class DL."

Only the project imports needed for the goal to elaborate.
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

/-- A nonnegative local submartingale is a cadlag submartingale if and
only if it is of class DL. -/
theorem IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω) :
    Submartingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry

end ProbabilityTheory
