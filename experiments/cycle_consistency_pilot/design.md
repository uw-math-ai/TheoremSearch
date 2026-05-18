# Design Document — Cycle-Consistency Pilot

## Models
| Role | Model |
|---|---|
| Informalizer | us.anthropic.claude-sonnet-4-5-20250929-v1:0 |
| Formalizer (B and T) | us.anthropic.claude-haiku-4-5-20251001-v1:0 |
| Judge | us.anthropic.claude-sonnet-4-5-20250929-v1:0 |

Note: Models accessed via AWS Bedrock (us-west-2, cross-region inference profiles).
Opus was not available on this account; Sonnet 4.5 is used as judge (stronger than Haiku formalizer).
The informalizer also uses Sonnet 4.5. This is a threat to validity noted in analysis.md.

## Strata Cutoffs (computed on filtered Mathlib population)

Total eligible candidates (Mathlib, kind ∈ {theorem, definition}, non-null signature,
full_name not starting with `_`, at least one outgoing dependency edge): **329,981**

| Stratum variable | p25 | p75 | Condition for stratum |
|---|---|---|---|
| In-degree | 0.0 | 4.0 | dense ≥ p75; non_dense ≤ p25; medium in between |
| Signature length (chars) | 124.0 | 314.0 | large ≥ p75; small ≤ p25 |

Note on `kind`: The spec listed `('thm', 'def')` but the actual DB values are `'theorem'` and
`'definition'` (the 'thm'/'def' variants account for only ~2600 total rows). We used
`('theorem', 'definition')` as the obviously intended filter and record this deviation here.

Note on edge direction: edges go `source_id → target_id` where source **uses** target.
"Predecessors of F" = dependency targets of F (outgoing edges from F).
"In-degree of F" = number of things that reference F (incoming edges to F).

## Sample Seed
`random.seed(42)`

## Per-cell Candidate Counts
| In-degree stratum | Size stratum | Sampled | Shortfall |
|---|---|---|---|
| dense | large | 10 | 0 |
| dense | small | 10 | 0 |
| medium | large | 10 | 0 |
| medium | small | 10 | 0 |
| non_dense | large | 10 | 0 |
| non_dense | small | 10 | 0 |

**Total sampled**: 60

## Pre/Post Candidate Counts
- Pre-model-calls: 60
- Post-model-calls (after any refusals/drops): 60

## Sampled Node IDs
```
[142999, 25874, 7364, 174702, 58186, 51917, 47996, 31198, 173044, 24055, 144383, 175107, 99632, 10968, 113630, 68271, 4075, 3880, 11983, 30057, 177461, 319200, 40769, 159827, 351689, 270514, 171427, 286382, 200527, 15949, 305849, 325907, 99537, 283080, 193840, 166542, 145179, 97800, 122140, 307632, 248356, 124936, 117106, 263254, 120553, 256217, 368610, 250914, 323677, 219297, 81609, 373013, 311629, 332568, 158086, 285219, 117965, 336471, 253041, 353452]
```

---

## Ablation Design

### Motivation

The pilot result (T preferred 81.7%, p≈0) is strong but the mechanism is ambiguous.
The treatment context does two things at once:

1. **Provides the API surface** — actual type signatures of F's dependencies give the
   formalizer the exact names and types it needs to write a well-typed declaration.
2. **Reveals the mathematical domain** — the names of F's predecessors identify the
   area of Mathlib (e.g. `CategoryTheory.Iso.*` names signal category theory), which
   could help the formalizer produce a plausible-sounding but structurally wrong output.

### Conditions

Four conditions total (B and T carried over from the pilot; two new):

| ID | Name | Formalizer input |
|---|---|---|
| **B** | Baseline | NL only |
| **T** | Treatment (full) | NL + predecessor `full_name : signature` blocks |
| **T-names** | Names-only | NL + predecessor `full_name` only (no signatures) |
| **T-random** | Random same-module | NL + random same-module nodes, `full_name : signature`, same count as T |

**T-random sampling**: for each candidate F, draw `dep_count(F)` nodes uniformly at
random from the same Lean module as F (i.e. nodes where `module = F.module`),
excluding F itself. Apply the same 8 000-token cap and record truncation. Use a fixed
seed (`random.seed(42 + node_id)` per candidate for reproducibility).

All new conditions reuse the **same 60 candidates and the same NL** from the pilot.
No new informalizer calls are needed.

### Comparison logic

| Comparison | What it isolates |
|---|---|
| **T vs T-names** | Do type *signatures* of deps matter, or just knowing the names/namespace? If T ≈ T-names, the effect is mostly topical (names reveal the domain). If T > T-names, the actual type information is load-bearing. |
| **T vs T-random** | Does the *predecessor relationship* matter, or does any same-module context help? If T > T-random, actual deps are better than random same-area context. If T ≈ T-random, "knowing the neighbourhood" is sufficient. |
| **T-random vs B** | Does any same-module context help over nothing? If T-random > B, even irrelevant same-area declarations provide useful topical signal. |
| **T-names vs B** | Does knowing dep names (without signatures) help over nothing? |

### Judge protocol for the ablation

Each new condition is judged **paired against T** (the strongest pilot condition):
- T vs T-names: which matches the target signature better?
- T vs T-random: which matches the target signature better?

Same judge model, same prompt structure, same A/B randomisation per item as the pilot.
Blinding map stored separately in `ablation_judge_label_map.json`.

The B vs T verdict from the pilot is **not re-run** — it is carried forward as-is.
B vs T-names and B vs T-random are derived transitively from the above pairs where
needed for the stratified analysis; direct B vs T-names and B vs T-random judgments
are not collected (to avoid judge fatigue and cost on a 60-sample pilot).

### Type-check supplement

For a subset of candidates (all 60 if feasible), we also run `lake env lean` against
a minimal `import Mathlib` project pinned to `leanprover/lean4:v4.29.0` to get a
ground-truth validity signal. This is separate from the judge and reported alongside
it. Expected runtime: ~2–5 s per candidate after the initial Mathlib .olean cache
download (~3–4 GB from the Mathlib cache server).
