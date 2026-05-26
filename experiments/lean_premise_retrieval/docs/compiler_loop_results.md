# Compiler-in-the-loop formalization (unfamiliar library)

**Setup.** 13 standalone theorems from `brownian-motion` (Lean v4.30, stochastic
analysis — a library the model has never seen). A Sonnet agent formalizes each
NL description into a Lean statement, with a **compiler in the loop**: it may
submit `theorem cand … := sorry` to a constrained `tc.sh` wrapper (one
`import BrownianMotion`, parses `error:`/`sorry`), up to **K=3** tries per target.
Strict sandbox — no access to the library source.

Four conditions:
- **no-RAG** — description only.
- **RAG** — description + top-15 retrieved premises (our formal retriever).
- **library** — description + grep over the full decl listing (targets removed).
- **RAG+library** — both retrieved premises and grep access.

**Metrics.** *Typecheck* = compiles against the built library (the weak metric —
a compiling statement can be the wrong proposition). *Correctness* is
hand-judged from the full statement vs the gold signature: ✓ faithful,
~ equivalent but reformulated, ✗ wrong/different.

## Results

| target | no-RAG | RAG | library | RAG+library |
|---|---|---|---|---|
| `toBilinForm_eq` | ✗ | ✗ `mk₂` reformulation | ✗ pivoted to pointwise | ✗ `toLinearMap∘f` |
| `ofFin'_succ` | ✗ | ✓ | ✓ | ✗ **castSucc≠succ** |
| `isFilteredPreBrownian` | ✗ | ✗ `sorry` in stmt | ✓ | ~ StronglyMeas. hyp |
| `isPos_def_real` | ✗ | ✓ | ✓ | ✓ |
| `toMatrix_ofMatrix` | ✗ | ✓ | ✓ | ✓ |
| `coe_sub` | ✗ | ✓ | ✓ | ✓ |
| `coe_singletonBotProd` | ✗ | ✓ | ✓ | ✓ |
| `chainingSequence_of_lt` | ✗ | ✓ | ✓ | ✓ |
| `generateFrom_eq` | ✗ | ~ MeasSpace-level | ~ | ~ |
| `coe_zero` | ✗ | ✓ | ✓ | ✓ |
| `inf'_eq` | ✗ | ✓ | ✓ | ✓ |
| `isKolmogorovProcess_preBrownian` | ✗ | ✓ | ✓ | ✓ |
| `brownian_ae_eq_preBrownian` | ✗ | ✓ | ✓ | ✓ |
| **typecheck** | **0/13** | **13/13** | **13/13** | **13/13** |
| **strict-correct ✓** | **0/13 (0%)** | **10/13 (77%)** | **11/13 (85%)** | **9/13 (69%)** |
| **tool calls** | 42 | 52 | **118** | 50 |
| **output tokens** | 9.9k | 17.7k | 25.1k | 14.3k |
| **harness total_tokens** | — | — | 146k | 78k |

(`output tokens` = model generation; `tool calls` = `tc.sh`/grep invocations.
Both exact and comparable across conditions. `harness total_tokens` was only
captured at completion for the last two agents.)

## Findings

1. **The compiler loop guarantees well-formedness, not correctness.** It drove
   every grounded method to 13/13 *typecheck*, but correctness tops out at 85%.
   The gap is the compiles-but-wrong failure mode: RAG+library emitted
   `I.ofFin' i.castSucc = I.ofFin' i.succ` for `ofFin'_succ` — clean compile,
   wrong proposition.

2. **No-RAG collapses to 0 even with the compiler.** The loop reports that a
   name is unknown but cannot supply it; the model substitutes hallucinated
   names (`wienerMeasure`, `preBrownianGaussianLimit`, `infimumPoint`) that never
   resolve. Grounding closes the gap, not iteration.

3. **RAG+library (69%) < library alone (85%) < — the anchoring effect.** The
   tool-call counts are the tell: RAG+library did **50** calls, library-access
   **118**. Retrieved premises made the agent feel done sooner — it stopped
   grepping and iterating, then shipped a plausible-but-unverified statement.
   Library-access, with no prior to anchor on, searched 2.4× harder and kept
   landing on the correct forms. RAG primes *premature convergence* in a strong
   model that could otherwise search.

4. **RAG alone (77%) < library alone (85%) — recall is the lever.** RAG's fixed
   top-15 has imperfect recall (~0.28); when the signature-defining decl isn't
   retrieved (e.g. `Filtration.natural`), the model hand-rolls a wrong statement
   (it even embedded a `sorry`). On-demand search has unbounded recall and finds
   it. The bottleneck is retrieval recall, not iteration.

5. **One target (`toBilinForm_eq`) defeated all four** — a coercion-heavy
   equality everyone restated in a compiling-but-non-gold form. A
   retrieval/grounding ceiling.

## Comparison to the no-iteration run

| | no-RAG | RAG | library | RAG+library |
|---|---|---|---|---|
| no compiler (correctness) | 0% | 50% | 78% | 78% |
| K=3 compiler loop (correctness) | 0% | **77%** | 85% | 69% |

The compiler loop mainly lifts **RAG** (50%→77%) by letting it repair malformed
attempts; library stays ~flat (78%→85%). The loop is most valuable exactly when
retrieval recall is imperfect — it lets RAG recover. But combining RAG with
search (RAG+library) *regressed* (78%→69%): the loop can't undo a confidently
wrong-but-compiling statement that the agent stopped iterating on.
