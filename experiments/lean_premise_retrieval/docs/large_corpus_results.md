# Large-corpus, post-cutoff formalization (old corpus / v4.30 targets)

**Setup.** Targets = 24 theorems added in the Mathlib v4.30 cycle (after the model's
cutoff), stratified across 12 topic areas, filtered so all signature-premises exist in the
older corpus. The model has not seen these declarations. Retrieval corpus = the **team's
`v2` corpus** (our slogans + lean-graph dependency edges, embedded with Qwen3-Embedding-8B;
~295–388k decls). NL prompt per target = back-translation of the signature (name blanked).
Typecheck = against built v4.30 Mathlib.

> **Provenance / version — to confirm.** The premise *labels* (`sig`/`extends`/`field`
> edges) are lean-graph's; the *slogans* are the team's own (the `v2` RDS), not the published
> LeanSearch-v2 corpus (LeanSearch-v2 is the external benchmark we compare against, not a data
> source here). The exact Mathlib rev the `v2` corpus was built on is recorded in the
> ingestion provenance (`projects.mathlib_rev` / `lean_graph_commit`) and should be pinned;
> the target diff used a v4.29 decl listing as the "old" baseline, which should be re-aligned
> to the actual embedded-corpus rev before the "solvable-from-corpus / never-seen" claim is
> formalized. (One target, `PiLp.linearIndependent_single`, was nominally in the corpus — a
> symptom of this misalignment — but it was never retrieved and failed in all conditions.)

Four conditions, Sonnet subagent + `tc_ml.sh` compiler loop, **hard cap 3 tc calls/item**
(no-RAG ran uncapped — see caveat):
- **no-RAG** — informal description only.
- **RAG** — description + top-15 retrieved premises (learned query head over the corpus).
- **library-search** — description + `grep` over the full 292k-line `name :: signature` listing.
- **RAG+library** — both retrieved premises and grep access.

**Metric.** Typecheck is a gate, not the signal (it is trivially gamed by retrying). The
result is **correctness vs the real Mathlib declaration**, hand-judged: **exact ✓** (same
proposition) plus **high-confidence-equivalent** (a restatement we are fairly sure is
logically equivalent — e.g. `p ∈ primesLE n` ≡ `p.Prime ∧ p ≤ n`). Analogous-but-different
statements (metric↔emetric, EReal↔ENNReal, additive↔multiplicative, different endpoints) do
**not** count. Typecheck rates independently verified in one batched `import Mathlib` pass.

## Results (n=24)

| condition | typecheck (verified) | exact ✓ | + hi-confidence equivalent | compute |
|---|---|---|---|---|
| no-RAG | 22/24 | 4 | **5** | 276 calls / 49 min |
| RAG | 20/24 | 6 | **8** | 68 calls / 11 min |
| library-search | 23/24 | 5 | **6** | 275 calls / 25 min |
| RAG+library | 24/24 | 7 | **8** | 188 calls / 17 min |

Retrieval recall (gold sig-premises): raw cosine R@15 = 0.018; **learned query head
R@15 = 0.161 (9× lift)**; 78% of targets have ≥1 gold premise in the head's top-15.

## Findings

1. **Typecheck anti-correlates with correctness.** no-RAG has nearly the highest typecheck
   (22/24) and the lowest correctness (5); RAG the lowest typecheck (20/24) and higher
   correctness (8). The condition that compiles most is the worst — typecheck doesn't just
   fail to inform, it misleads. (no-RAG ran uncapped at 276 calls, which inflates its
   typecheck/cost but not its correctness — it can't retry its way to the right names.)

2. **Grounding lifts correctness ~60%** (no-RAG 5 → RAG/RAG+library 8).

3. **Corpus-size crossover.** In the brownian experiment (1.1k-decl, enumerable library)
   library-search beat RAG decisively (78% vs 50%). Here at large scale, **RAG beats
   library-search** (8 vs 6) — *and* at ~40% the token cost (14k vs 52k). When the library
   can't be grep-enumerated, search loses its edge and learned retrieval wins. RAG+library
   ties RAG at 8 (it proved 10 statements outright). Qualitatively, library-search's misses
   are mostly the *wrong nearby object* (the EReal version, the abstract cylinder) — grep
   lands on a relative; embedding retrieval lands more on-target.

4. **Informalization-loss floor.** 10 targets (t01, t03, t06, t07, t08, t09, t10, t11, t12,
   t13) failed in every grounded condition — the back-translation dropped load-bearing detail
   (`SemiSimplex`→`Simplex`, `ℕ∞`→`ℕ`, the specific `g • I`, `PiLp.single`, the PS→MvPS
   direction). No retrieval recovers what the NL already destroyed; this caps all conditions
   equally, so absolute scores are floored by **informalizer quality**, not retrieval.

5. **The methods are complementary, not interchangeable.** The three grounded conditions
   share a 9-target core and each adds different items (RAG: the `∀ᶠ` continuity form;
   library: the exact-named `IsEdgeReachable 2`; RAG+library: the `ℕ∞` decl). An earlier
   lenient metric scored all three at 11 — that was a coincidence of count, which is why we
   adopted the stricter high-confidence-equivalent metric above.

## Caveats

- **n=24**: differences are small; report paired **McNemar** for significance. Robust claims:
  (1) grounding > no-RAG, (2) typecheck anti-correlates with correctness, (3) RAG ≥
  library-search at large corpus and lower cost.
- **Query/corpus style mismatch**: query is a Qwen3-8B back-translation; corpus is the team's
  own slogans (a different generator). Models the real "user writes NL" scenario; shared by
  all conditions so the comparison is clean, but caps absolute recall.
- **Self-imposed difficulty**: the decl name was blanked in the back-translation (anti-leakage)
  and targets are obscure post-cutoff research-level lemmas, so absolute correctness is low by
  construction — the experiment's point is the delta between conditions, not the absolute rate.
- **No leakage**: 23/24 targets absent from the corpus (the 1 nominal hit never surfaced),
  0/24 in the library listing, and the formalizer was sandboxed (NL + retrieved name/sig +
  grep only; no Mathlib source).
