/-
Candidate A — no-graph arm.

Blueprint statement (brownian-motion / local_martingales.tex:902):
  "A local martingale is a cadlag martingale if and only if it is of class DL."

We supply only the project imports needed to make the goal well-typed.
No related lemmas are surfaced.
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

/-- A local martingale is a cadlag martingale if and only if it is of class DL. -/
theorem IsLocalMartingale.martingale_iff_classDL
    (hX : IsLocalMartingale X 𝓕 P) :
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P := by
  sorry

end ProbabilityTheory
