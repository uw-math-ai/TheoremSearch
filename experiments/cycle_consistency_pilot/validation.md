# Validation Checklist — Cycle-Consistency Pilot

- [x] **No NL → F leakage in F_B**

  Baseline prompt = NL only. full_name/signature not injected outside the NL body.

Samples:
- `stronglyMeasurable_iff_measurable_separable`: baseline user prompt (NL replaced with placeholder):
```
Informal statement:
[NL_REMOVED]

Provide the Lean 4 signature.
```
- `CategoryTheory.Iso.map_inv_hom_id_assoc`: baseline user prompt (NL replaced with placeholder):
```
Informal statement:
[NL_REMOVED]

Provide the Lean 4 signature.
```
- `CategoryTheory.ShortComplex.LeftHomologyData.descH`: baseline user prompt (NL replaced with placeholder):
```
Informal statement:
[NL_REMOVED]

Provide the Lean 4 signature.
```

- [x] **No F leakage in T's dependency context (verbatim)**

  Dependency context contains predecessors only — not F's full_name or signature body verbatim.

  **Namespace-prefix overlap (not checked above):** On average 38% of a candidate's dep names share
  its own top-level namespace prefix (e.g. deps of `CategoryTheory.Foo` are often `CategoryTheory.*`).
  17/60 candidates have >50% same-namespace deps; 4/60 have 100%. This is an implicit topical hint
  that is not removed by the verbatim check. It is acknowledged as a limitation in analysis.md and
  design.md, but this check should not be read as "zero leakage" — only "no verbatim leakage."

Samples:
- `stronglyMeasurable_iff_measurable_separable`: dep context snippet:
```
-- proof
And.intro : And.intro {a b : Prop} (left : a) (right : b) : a ∧ b

-- proof
BorelSpace.opensMeasurable : BorelSpace.opensMeasurable.{u_6} {α : Type u_6} [TopologicalSpace α] [MeasurableSpace α] [BorelSpace α] :
  OpensMeasurableSpace α

-- proof
Continuous.comp_stronglyMeasurable : Continuous.comp_stronglyMeasurable.{u_1, u_2, u_3} {α : Type u_1} {β : Type u_2} {γ : Type u_3} {x✝ : MeasurableSpace α}
  [TopologicalSpace β] [TopologicalSpace γ] {g : β → γ} {f : α → β} (hg : Continuous g)
```
- `CategoryTheory.Iso.map_inv_hom_id_assoc`: dep context snippet:
```
-- proof
CategoryTheory.Category.assoc : CategoryTheory.Category.assoc.{v, u} {obj : Type u} [self : CategoryTheory.Category.{v, u} obj] {W X Y Z : obj}
  (f : W ⟶ X) (g : X ⟶ Y) (h : Y ⟶ Z) :
  CategoryTheory.CategoryStruct.comp (CategoryTheory.CategoryStruct.comp f g) h =
    CategoryTheory.CategoryStruct.comp f (CategoryTheory.CategoryStruct.comp g h)

-- proof
CategoryTheory.Category.id_comp : CategoryTheory.Category.id_comp.{v, u} {obj : Type u} [self : CategoryTheory.Category.{v, u} obj] {
```
- `CategoryTheory.ShortComplex.LeftHomologyData.descH`: dep context snippet:
```
-- def
CategoryTheory.Category.toCategoryStruct : CategoryTheory.Category.toCategoryStruct.{v, u} {obj : Type u} [self : CategoryTheory.Category.{v, u} obj] :
  CategoryTheory.CategoryStruct.{v, u} obj

-- def
CategoryTheory.CategoryStruct.comp : CategoryTheory.CategoryStruct.comp.{v, u} {obj : Type u} [self : CategoryTheory.CategoryStruct.{v, u} obj]
  {X Y Z : obj} : (X ⟶ Y) → (Y ⟶ Z) → (X ⟶ Z)

-- def
CategoryTheory.CategoryStruct.toQuiver : CategoryTheory.CategoryStruct.toQuiver.{v, u} {obj 
```

- [x] **Judge blinding**

  A/B labels randomized per item using `random.random() < 0.5`. Mapping saved in `judge_label_map.json` (not in results.csv). Judge prompt shows only 'CANDIDATE A' and 'CANDIDATE B', no condition names.

- [x] **Same formalizer for B and T**

  Both B and T calls use `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Enforced by the single constant `FORMALIZER_MODEL` used in both `formalize_baseline()` and `formalize_treatment()`.

- [x] **No post-hoc filtering on outcome**

  Candidate set (60 nodes) was sampled before any model calls. Candidates dropped after model runs (refusals/errors): 0. All drops logged in design.md.

- [x] **Seed determinism**

  Sampler uses `random.Random(42).sample(...)` on a deterministic ORDER BY n.id query. Re-running produces identical IDs.


**All checks passed.** Proceeding to analysis.md is authorized.
