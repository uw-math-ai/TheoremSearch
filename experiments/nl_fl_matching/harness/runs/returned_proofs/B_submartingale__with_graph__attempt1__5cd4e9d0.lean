/-
Candidate B — with-graph arm.
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

/-
Helper: When τ(ω) > t, the stopped process at time t equals the indicator times X t
-/
private lemma stoppedProcess_eq_of_lt_tau {τ : Ω → WithTop ι} {t : ι} {ω : Ω}
    (ht : (t : WithTop ι) < τ ω) :
    stoppedProcess (fun i ↦ {ω | ⊥ < τ ω}.indicator (X i)) τ t ω = X t ω := by
  simp +decide [ stoppedProcess, ht.le ];
  aesop

/-
Helper: integrability from ClassDL
-/
private lemma integrable_of_classDL (hDL : ClassDL X 𝓕 P) (t : ι) :
    Integrable (X t) P := by
  rcases hDL with ⟨ h1, h2 ⟩;
  have := h2 t;
  obtain ⟨ h3, h4 ⟩ := this;
  convert h4.2.choose_spec ⟨ fun _ => ↑t, ?_, ?_ ⟩ using 1 <;> norm_num;
  · constructor <;> intro h <;> rw [ eLpNorm_one_eq_lintegral_enorm ] at *;
    · convert h4.2.choose_spec ⟨ fun _ => ↑t, ?_, ?_ ⟩ using 1 <;> norm_num;
      · simp +decide [ eLpNorm_one_eq_lintegral_enorm ];
      · exact?;
    · refine' ⟨ _, _ ⟩;
      · convert h3 ⟨ fun _ => ↑t, ?_, ?_ ⟩ using 1 <;> norm_num;
        exact?;
      · convert h.trans_lt ( ENNReal.coe_lt_top ) using 1;
  · exact?

-- Helper: condexp inequality from localizing sequence
private lemma condexp_mono_of_localSubmartingale_classDL
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hDL : ClassDL X 𝓕 P)
    (i j : ι) (hij : i ≤ j) :
    X i ≤ᵐ[P] P[X j | 𝓕 i] := by
  sorry

-- Helper: prog measurable from submartingale + local submartingale
private lemma progMeasurable_of_submartingale_localSubmartingale
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω)
    (hSub : Submartingale X 𝓕 P) :
    ProgMeasurable 𝓕 X := by
  sorry

-- Helper: uniform integrability from submartingale + nonneg + local submartingale
private lemma uniformIntegrable_stoppedValue_of_submartingale
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω)
    (hSub : Submartingale X 𝓕 P) (t : ι) :
    UniformIntegrable
      (fun (τ : {T : Ω → WithTop ι | IsStoppingTime 𝓕 T ∧ ∀ ω, T ω ≤ t}) ↦
        stoppedValue X τ.1) 1 P := by
  sorry

/-- Forward: submartingale → ClassDL -/
private lemma submartingale_to_classDL
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω)
    (hSub : Submartingale X 𝓕 P) :
    ClassDL X 𝓕 P :=
  ⟨progMeasurable_of_submartingale_localSubmartingale hX hX_nonneg hSub,
   uniformIntegrable_stoppedValue_of_submartingale hX hX_nonneg hSub⟩

/-- Backward: ClassDL → Submartingale -/
private lemma classDL_to_submartingale
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω)
    (hDL : ClassDL X 𝓕 P) :
    Submartingale X 𝓕 P :=
  ⟨hDL.progMeasurable.stronglyAdapted,
   fun i j hij ↦ condexp_mono_of_localSubmartingale_classDL hX hDL i j hij,
   integrable_of_classDL hDL⟩

/-- A nonnegative local submartingale is a cadlag submartingale if and
only if it is of class DL. -/
theorem IsLocalSubmartingale.submartingale_iff_classDL_of_nonnegative
    (hX : IsLocalSubmartingale X 𝓕 P)
    (hX_nonneg : ∀ t ω, 0 ≤ X t ω) :
    Submartingale X 𝓕 P ↔ ClassDL X 𝓕 P :=
  ⟨submartingale_to_classDL hX hX_nonneg, classDL_to_submartingale hX hX_nonneg⟩

end ProbabilityTheory