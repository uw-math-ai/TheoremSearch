# Analysis — Cycle-Consistency Pilot

n = 60 candidates (target: 60)

## Overall Judge Preference
| Condition | Count | % |
|---|---|---|
| T preferred | 49 | 81.7% |
| B preferred | 3 | 5.0% |
| Tie         | 8 | 13.3% |

## Wilcoxon Signed-Rank Test
Coded: T=+1, B=-1, tie=0

W=79.50, p=0.0000

n=60 is underpowered for subtle effects. Treat as direction-finding, not a significance claim.

## Stratified Preference Table
| In-degree stratum | Size stratum | T preferred | B preferred | Tie |
|---|---|---|---|---|
| dense | large | 10 | 0 | 0 |
| dense | small | 6 | 1 | 3 |
| medium | large | 9 | 0 | 1 |
| medium | small | 8 | 1 | 1 |
| non_dense | large | 8 | 1 | 1 |
| non_dense | small | 8 | 0 | 2 |

## Vacuous Formalization Rates
| Condition | Vacuous rate |
|---|---|
| Baseline (B) | 0.0% |
| Treatment (T) | 0.0% |

## Edit Distance Distributions (token-level Levenshtein vs. F)
| Condition | Mean | Median | Min | Max |
|---|---|---|---|---|
| B | 31.7 | 25.0 | 3 | 103 |
| T | 14.5 | 12.0 | 3 | 40 |

## What We Did NOT Control For

- **Small n**: 60 candidates is insufficient to detect small effects. Results should be treated as
  directional signals, not conclusive evidence.
- **Single judge**: One LLM judge with possible biases toward longer or more elaborate formalizations.
  No inter-annotator reliability estimate.
- **No type-checking**: Type-check signal was not wired up (too costly in the 2-hour budget).
  F_B and F_T are assessed by semantic similarity only; syntactically invalid code counts the same
  as valid code.
- **Possible leakage paths**: (a) The judge model (us.anthropic.claude-sonnet-4-5-20250929-v1:0) may have internalized Mathlib
  declarations; a "better" candidate might be recognized from training rather than inferred from
  the NL. (b) Dependency names in T's context implicitly identify the area of mathematics, which
  could hint at the target even without giving F's signature directly.
- **Model as informalizer and formalizer**: Both roles use us.anthropic.claude-haiku-4-5-20251001-v1:0. A model may have
  idiosyncratic formatting preferences that create spurious consistency within its own outputs.
- **No ablation of context quality**: T's context includes all predecessor edge types. We did not
  test whether some edge types are more or less helpful.
- **Single seed**: Results are for one random draw of 60 candidates. A different seed might yield
  different stratified results.
