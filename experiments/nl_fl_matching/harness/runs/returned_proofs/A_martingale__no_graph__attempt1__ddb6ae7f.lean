/-
Candidate A — no-graph arm.

Blueprint statement (brownian-motion / local_martingales.tex:902):
  "A local martingale is a cadlag martingale if and only if it is of class DL."
-/

import Mathlib
import BrownianMotion.StochasticIntegral.LocalMartingale

open MeasureTheory Filter

namespace ProbabilityTheory

variable {ι Ω E : Type*}
  [LinearOrder ι] [OrderBot ι] [TopologicalSpace ι] [OrderTopology ι]
  [MeasurableSpace ι] [BorelSpace ι]
  [NormedAddCommGroup E] [NormedSpace ℝ E] [CompleteSpace E]
  {mΩ : MeasurableSpace Ω} {P : Measure Ω}
  {X : ι → Ω → E} {𝓕 : Filtration ι mΩ}

/-- A stochastic process is of class DL. -/
structure ClassDL (X : ι → Ω → E) (𝓕 : Filtration ι mΩ) (P : Measure Ω) : Prop where
  progMeasurable : ProgMeasurable 𝓕 X
  uniformIntegrable (t : ι) : UniformIntegrable
    (fun (τ : {T : Ω → WithTop ι | IsStoppingTime 𝓕 T ∧ ∀ ω, T ω ≤ t}) ↦ stoppedValue X τ.1) 1 P

omit [TopologicalSpace ι] [OrderTopology ι] [MeasurableSpace ι] [BorelSpace ι]
  [NormedSpace ℝ E] [CompleteSpace E] in
/-- The stopped process equals X when τ > t. -/
lemma stopped_process_eq_of_lt
    {τ : Ω → WithTop ι} {t : ι} {ω : Ω}
    (hτ : (t : WithTop ι) < τ ω) :
    stoppedProcess (fun i => {ω | ⊥ < τ ω}.indicator (X i)) τ t ω = X t ω := by
  simp +decide [stoppedProcess, hτ.le]
  aesop

/-- The stopped processes converge a.e. to X. -/
lemma ae_tendsto_stopped_of_localizing
    {τ : ℕ → Ω → WithTop ι}
    (hτ_loc : IsLocalizingSequence 𝓕 τ P) (t : ι) :
    ∀ᵐ ω ∂P, ∃ N, ∀ n ≥ N,
      stoppedProcess (fun i => {ω' | ⊥ < τ n ω'}.indicator (X i)) (τ n) t ω = X t ω := by
  filter_upwards [hτ_loc.tendsto_top] with ω hω
  have := hω.eventually (lt_mem_nhds (show ⊤ > (t : WithTop ι) from WithTop.coe_lt_top t))
  exact eventually_atTop.mp this |>.imp fun N hN n hn => stopped_process_eq_of_lt (hN n hn)

/-- From ClassDL, X at any fixed time is integrable. -/
lemma ClassDL.integrable (hDL : ClassDL X 𝓕 P) (t : ι) : Integrable (X t) P := by
  have hui := hDL.uniformIntegrable t
  have hmemLp := hui.memLp (⟨fun _ => t, isStoppingTime_const 𝓕 t, fun _ => le_rfl⟩ :
    {T : Ω → WithTop ι | IsStoppingTime 𝓕 T ∧ ∀ ω, T ω ≤ t})
  rw [memLp_one_iff_integrable] at hmemLp
  convert hmemLp using 1

/-- Backward direction: A local martingale of class DL is a martingale. -/
lemma IsLocalMartingale.martingale_of_classDL
    (hX : IsLocalMartingale X 𝓕 P) (hDL : ClassDL X 𝓕 P) :
    Martingale X 𝓕 P := by
  sorry

/-- Forward direction: A martingale that is a local martingale is of class DL. -/
lemma IsLocalMartingale.classDL_of_martingale
    (hX : IsLocalMartingale X 𝓕 P) (hM : Martingale X 𝓕 P) :
    ClassDL X 𝓕 P := by
  sorry

/-- A local martingale is a cadlag martingale if and only if it is of class DL. -/
theorem IsLocalMartingale.martingale_iff_classDL
    (hX : IsLocalMartingale X 𝓕 P) :
    Martingale X 𝓕 P ↔ ClassDL X 𝓕 P :=
  ⟨fun hM => hX.classDL_of_martingale hM, fun hDL => hX.martingale_of_classDL hDL⟩

end ProbabilityTheory
