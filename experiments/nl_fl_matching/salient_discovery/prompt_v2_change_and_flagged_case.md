# Grader prompt change (v1 → v2) + the flagged edge case

Date: 2026-05-31. For Simon's review **before** re-running the ≥0.90 tier under v2.

Context: the ≥0.90 Mathlib→arXiv tier was graded by 2-rater blind Opus consensus
(+ 3rd-Opus tie-break on disagreement). Simon flagged one row where a single rater
named a real difference yet still labelled it `exact`. That motivates a prompt guard
and a **re-run of the same portion** (not just applying the guard to ungraded rows).

---

## 1. Original prompt (v1) — used for all 2,636 graded rows

Verbatim template from `grade_consensus.py` (placeholders `{…}` filled per candidate).

```
You are verifying a candidate link between a FORMAL Lean declaration and an INFORMAL mathematical statement from an arXiv paper. Decide whether they state the SAME mathematical result.

Judge the actual MATHEMATICAL CONTENT — the hypotheses, the conclusion, the object being defined — NOT surface word overlap. Lexically similar slogans about DIFFERENT theorems are common in this data; do not be fooled by shared vocabulary.

FORMAL (Lean):
  decl_name: {formal_decl}
  slogan: {formal_slogan}
  Lean signature/source:
{formal_body}

INFORMAL (arXiv {arxiv_id} {paper_title}; ref {informal_ref}):
  slogan: {informal_slogan}
  statement (LaTeX):
{informal_body}

Choose exactly ONE label using this operational test:
  exact   - They state the SAME proposition. A mathematician would cite the Lean decl as THE formalization of this exact informal statement with NO caveat. Any difference is only notation/formalization syntax (symbols vs words, an iff spelled _iff, a definition unfolded, argument order).
  inexact - They concern the SAME underlying result but are NOT identical: one is a generalization, a special case, ONE direction of an iff, or a sub-component of the other; linking them needs a caveat or a small step.
  wrong   - They state DIFFERENT theorems or define DIFFERENT objects, even if in the same area or sharing words. Whenever the core object or the claim differs, this is wrong.
  unjudgeable - One side's text is genuinely missing or too vague to determine its content. Use ONLY then.

Decision rules:
- Do NOT default to `inexact` when unsure. If the two state genuinely different theorems, label `wrong`.
- `inexact` requires that it is provably the SAME result up to a generalization/specialization/one-direction caveat — not merely the same topic.
- `unjudgeable` is not a hedge; use it only for missing/empty text.

Output ONLY a JSON object, no prose and no tool use:
{"label":"exact|inexact|wrong|unjudgeable","reason":"one short sentence naming the key matching content, or the specific mismatch"}
```

## 2. The change (v2) — exactly one bullet added

A new **first** bullet inserted at the top of the `Decision rules:` block. Nothing else
changed (definitions, structure, output format all identical).

```diff
 Decision rules:
+- SELF-CONSISTENCY GUARD: `exact` allows ZERO caveat. If your own one-sentence reason names ANY difference in a hypothesis, premise, or conclusion (wording like "differs", "but the formal has", "special case", "only one direction", "sub-component", "generalization", "stronger/weaker"), you MUST label `inexact` or `wrong` — NEVER `exact`.
 - Do NOT default to `inexact` when unsure. If the two state genuinely different theorems, label `wrong`.
 - `inexact` requires that it is provably the SAME result up to a generalization/specialization/one-direction caveat — not merely the same topic.
 - `unjudgeable` is not a hedge; use it only for missing/empty text.
```

**Why this and only this:** the failure mode is *internal contradiction* — a rater
writes a reason that names a difference, then labels `exact` anyway. The guard makes the
reason text gate the label. It does not change the exact/inexact/wrong definitions or bias
toward any label; it only forbids the contradictory `exact`.

---

## 3. The flagged edge case

**Formal decl:** `Eq.trans_ge`  ·  **sim** 0.9688  ·  **band** 0.95–1.0
**arXiv informal:** transitivity of ≥

### Slogans
- **Formal slogan:** "If a equals b and b is greater than or equal to c, then a is greater than or equal to c."
- **Informal slogan:** "If a is greater than or equal to b, and b is greater than or equal to c, then a is greater than or equal to c."

### The actual difference
| | first hypothesis | second hypothesis | conclusion |
|---|---|---|---|
| **Formal** `Eq.trans_ge` | a **=** b | b ≥ c | a ≥ c |
| **Informal** (≥-transitivity) | a **≥** b | b ≥ c | a ≥ c |

The formal lemma's first premise is **equality** (a = b); the informal's is **inequality**
(a ≥ b). Since a = b ⟹ a ≥ b, the formal is a **special case** of the informal general
transitivity — *related but not the same proposition*.

### Rater decisions (v1, blind, independent)
| rater | label | verbatim reason |
|---|---|---|
| rater1 | **wrong** | "Lean decl is Eq.trans_ge (a=b and b≥c ⟹ a≥c), but the informal statement is transitivity of ≥ (a≥b and b≥c ⟹ a≥c); the first hypothesis differs (equality vs inequality)." |
| rater2 | **exact** | "Both state transitivity: a≥b and b≥c implies a≥c (the formal Eq.trans_ge differs—it has a=b, not a≥b)." |
| rater3 (tie-break) | **wrong** | "Lean decl's first hypothesis is a=b (equality), while the informal statement uses a≥b; these are different propositions (Eq.trans_ge vs transitivity of ≥)." |

### Resolution
- Votes: `wrong` · `exact` · `wrong` → majority → **status = tiebroken, final = `wrong`, edge = FALSE.**
- **The consensus rejected it.** rater2 was the outlier (out-voted 2–1) so the row is **not** in the claimed edge set.

### What went wrong, and what the guard does
rater2's reason *names the difference* ("the formal differs—it has a=b, not a≥b") yet
labels it `exact`. That is exactly the internal contradiction the **v2 guard** forbids —
under v2, naming "differs" mandates `inexact` or `wrong`, never `exact`. (Arguably the
rubric-correct label here is `inexact`, since the formal is a special case; the v1 consensus
landed on `wrong`, which is harsh but still correctly **not-edge**.)

Net effect on this row: final outcome would not flip (it was already `wrong`/not-edge), but
the guard removes the lenient individual vote — which **does** matter on borderline rows
where the lenient rater is *not* out-voted.

---

## 4. Broader context — the `_of_eq_of_` family is graded inconsistently

The same shape (`a = b, b R c ⟹ a R c` vs informal "R is transitive") recurs and v1 graded
near-identical cases differently:

| formal decl | structure | v1 verdict | in edge set? |
|---|---|---|---|
| `Set.mem_of_eq_of_mem` | a=b, d∈a ⟹ d∈b | confirmed **exact** | ✅ (informal *is* the eq-substitution → correct) |
| `le_of_eq_of_le` | a=b, b≤c ⟹ a≤c | confirmed **inexact** | ✅ edge |
| `lt_of_eq_of_lt` | a=b, b<c ⟹ a<c | confirmed **wrong** | ❌ |
| `Eq.trans_ge` | a=b, b≥c ⟹ a≥c | tiebroken **wrong** | ❌ |

`le` and `lt` are structurally identical yet split inexact/wrong. The error concentrates in
the fuzzy **exact↔inexact↔wrong boundary** (the `inexact` tier), on trivial
equality-substitution "plumbing" lemmas that only matched because the arXiv side states
generic transitivity.

---

## 5. Re-run plan (pending Simon's review of this doc)

1. Keep v1 output (`consensus_ge90.jsonl`, 2,636 rows) **untouched** for comparison.
2. Re-grade the **entire ≥0.90 tier (7,217)** under the v2 prompt into a **new** file
   (`consensus_ge90_v2.jsonl`) — same 2-rater + tie-break consensus.
3. Report the **delta**: how many v1 `exact` → v2 `inexact`/`wrong`, net change to the
   confirmed-edge count, and any rows whose final flips.
4. Then extend to the 0.85–0.90 band decision as before.

(Open: the re-run vehicle — the prior klone run hit config-corruption/token issues; the
infra path (fix klone vs. run via local Opus workflows) is decided separately before launch.)

---

## 6. Pilot against blueprint gold (2026-06-01) — does context bias the grader?

Question: Simon's intuition was that extra context (decl name, bodies) might *bias* the
graders vs. focusing on slogans. We tested it against ground truth instead of arguing.

**Setup** (`build_gold_pilot.py`, `score_gold_pilot.py`): 100 pairs from `_gold_cache.json` —
50 real blueprint-gold pairs (truth = EDGE; they're formalizations) + 50 **hard negatives**
(a gold formal × a *different* informal from the SAME blueprint paper → topically close,
different theorem → truth = NOT-EDGE). Two prompt arms, single Opus each, both with the guard:
- **A = slogan-only** (`/tmp/pilot_A`: formal_slogan + informal_slogan)
- **B = slogan + decl-name** (`/tmp/pilot_B`: + formal_decl)

| arm | edge-recall (gold +) | exact-rate | reject-rate (hard neg −) | balanced acc | clean-gold recall* |
|---|---|---|---|---|---|
| A slogan-only | 78% (39/50) | 26% | 100% (50/50) | 89.0% | 93% (39/42) |
| **B slogan+decl-name** | **84%** (42/50) | **40%** | **100%** (50/50) | **92.0%** | **100% (42/42)** |

\* excluding 8 noisy-gold positives both arms independently rejected.

Per-pair: B strictly dominates (correct 92 vs 89; B-right/A-wrong = 3, A-right/B-wrong = 0).

**Result REVERSES the a-priori intuition.** The decl-name does NOT bias toward false edges —
both arms reject **100%** of hard negatives. Instead the name *helps*: slogan-only's failures
are **false NEGATIVES on gold** — the qwen formal slogan is sometimes lossy/ambiguous, so the
bare-slogan grader hedges to `inexact` or wrongly says `wrong`. The name disambiguates the
formal object. All 15 A↔B disagreements are on gold positives; the name corrects A's
`inexact`→`exact` and *rescues* 3 that A called `wrong` (e.g. `OneJetSec.localize`,
`pairwiseDisjoint_L0'`, `ProbabilityTheory.SimpleProcess` integral).

**Byproduct:** the grader caught **~16% label noise in the blueprint gold** (8/50 positives
where the annotated informal genuinely mismatches the formal) — so gold is not a perfect oracle,
and the grader is strict enough to surface that.

### ⇒ DECISION (data-driven)
**Keep the grounding (decl-name + Lean body); do NOT strip to slogan-only.** Combine full
context + the SELF-CONSISTENCY GUARD (§2, which fixes the individual-rater "names a difference
yet labels exact" lapse). The production prompt's context is validated; only the guard is added.

Caveats: tested name (not full body — body is strictly more grounding, expected to help further);
hard negatives were same-blueprint mismatches (lexical-sibling near-duplicates would stress
precision harder); gold has ~16% noise that caps measured recall below true.
