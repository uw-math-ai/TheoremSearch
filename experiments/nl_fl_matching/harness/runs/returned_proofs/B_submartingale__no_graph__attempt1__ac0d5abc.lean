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
  constructor
  · -- Forward: Submartingale → ClassDL
    intro hSub
    constructor
    · -- ProgMeasurable: from the localizing sequence, stopped processes are prog-measurable.
      -- As n → ∞, they converge to X pointwise a.e.
      -- Combined with StronglyAdapted from Submartingale, this gives ProgMeasurable.
      sorry
    · -- UniformIntegrable for each t: from the submartingale property + nonneg + local cadlag,
      -- stopped values at times ≤ t are dominated by condExp of X_t.
      intro t
      sorry
  · -- Backward: ClassDL → Submartingale
    intro hDL
    refine ⟨hDL.progMeasurable.stronglyAdapted, ?_, ?_⟩
    · -- condExp inequality: X i ≤ᵐ P[X j | 𝓕 i]
      -- From IsLocalSubmartingale, stopped processes satisfy this.
      -- ClassDL gives L¹ convergence of stopped processes to X.
      -- Pass inequality to limit.
      intro i j hij
      -- Extract localizing sequence
      obtain ⟨τ, hτ_seq, hτ_prop⟩ := hX
      -- For each n, stopped process is submartingale
      -- On {ω : τ_n(ω) > j, ⊥ < τ_n(ω)}, stopped process agrees with X at times i and j
      -- As n → ∞, this set covers a.e. ω
      -- The submartingale inequality for stopped process + convergence → inequality for X
      sorry
    · -- Integrable at each time
      intro t
      -- From ClassDL, the constant stopping time at t gives X t in the UI family
      have hUI := hDL.uniformIntegrable t
      have : stoppedValue X (fun _ ↦ (t : WithTop ι)) = X t := by
        ext ω; simp [stoppedValue]
      have hmem := hUI.memLp ⟨fun _ ↦ (t : WithTop ι), isStoppingTime_const 𝓕 t, fun _ ↦ le_rfl⟩
      rw [this] at hmem
      exact memLp_one_iff_integrable.mp hmem

end ProbabilityTheory
