# §Bridging the Corpora — revision checklist

Tracking the section rewrite against the 4-point outline + data fixes.
Status: ✅ done · ◐ partial · ✗ missing

## Outline coverage
1. **What matching is (naively)** — ◐ ¶Motivating gives scale; still no one-clause *definition* of a match (formal theorem ↔ informal restatement).
2. **What we measured** — ✅ sim-bin tables + yield curve.
3. **Validation / earlier blueprint experiments** — ◐ ablation ✅ in; blueprint open/closed-pool NOT referenced from main text; expert-analysis appendix pointer ✗.
4. **Why it matters** — ✗ absent. Natural home = empty ¶Result (extension: link papers as context → autoformalization/retrieval payoff).

## Data fixes (vs earlier drafts)
- ✅ 1,595 blueprint pairs (was ≈1,600)
- ✅ 11.75M / 388,105 / 4.56T
- ✅ filtering 2,448 (0.631%); 385,657 retained
- ✅ 53.5% of nodes (was "edges")
- ✅ Table 4 → two tables (sim-bins + Mathlib/Core Lean/Projects) — module values verified
- ✅ scoped to 4,150 / sim ≥ 0.917; 284 blueprint full / 177 in prefix — verified
- ✅ ann_k probe reworded (0.852 ceiling, 1% ≥0.85)
- ✅ blueprint-pairs defined at point of use; §2.3.1 minimal mention; citations split per tool
- ✅ LLM Judge: ref 94%, signature-where-available, 4,850/60.5%, 12.5%/249-of-310, 93.4→85.8, 2.9%, 88.8 vs 93.1 — all verified
- ✅ "9.5% net flip rate" (relabeled from "removes false matches")
- ✅ Yield table verified; 88.8-vs-85 reconciled (sample ≥0.917 = 67/76 = 88.2% ≈ census 88.8%)

## Remaining TODO
### Content
- [ ] **¶Result** — empty. Fill with: (a) corrected verdict breakdown (exact 64.1% / inexact 35.3% / split 24; consensus confirmed 85.8% / tie-broken 13.6% / edge-amb 24), and/or (b) Point-4 "why it matters" synthesis.
- [ ] **Point 4 paragraph** — downstream value (extend gold corpus; retrieval/autoformalization; cross-corpus provenance). Likely = ¶Result.
- [ ] **Validation forward-ref** — 1 line to appendix open/closed-pool (Hit@1 0.426, Gap 0.644).
- [ ] **Expert-analysis appendix pointer** — 1 line, context-caveat.
- [ ] **Match definition** — one clause in ¶Motivating.

### Typography (carryover)
- [ ] em-dashes for spaced hyphens: "(cosine ≥ 0.917)-a prefix"; "sim 0.852 - below the judged band -"; "88.8% - against 93.1%".

### Cross-file consistency
- [ ] gold → blueprint rename in blueprint-matching.tex + nl-fl-matching.tex (RENAME blueprint-pair senses; KEEP "gold signature"/"gold label" generic senses)
- [ ] duplicate content: blueprint-matching.tex ≈ nl-fl-matching.tex — pick canonical
- [ ] limitations.tex: "≈1,600 blueprint pairs" → 1,595
- [ ] §2.3.1 \label must match the \S\ref{sec:leangraph} used in Bridging
- [ ] confirm yield table denominator = body-present throughout

## Verified-number bank (for ¶Result when filled)
- corrected 4,150 (sim ≥ 0.917): match 88.8% (3,685); exact 64.1% / inexact 35.3% of matches; split 24
- consensus: confirmed 85.8% (3,560) / tie-broken 13.6% (566) / edge-amb 24
- vs slogan-only on same 4,150: 93.1%
