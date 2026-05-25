/-
Candidate A — aesop baseline arm.

Pure tactic-based attempt with no LLM, no graph context, no Aristotle
search. The only proof attempted is `by aesop`. We submit this through
Aristotle anyway so that:
  (a) the elaborator confirms the file's type signature is valid,
  (b) Aristotle's own search isn't invoked (the prompt asks
      "verify-only — don't modify the file"),
  (c) we get a clean "Aesop closed it" or "Aesop failed" signal
      comparable to the no_graph / with_graph runs.

If Aesop closes this, the candidate falls to trivial automation and
the graph-helps claim wouldn't matter here. Expected: Aesop fails on
this kind of iff (substantive measure-theoretic argument), but worth
checking — surprise outcomes are themselves data.
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
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P := by aesop

end ProbabilityTheory
