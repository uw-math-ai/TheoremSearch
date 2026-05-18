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
