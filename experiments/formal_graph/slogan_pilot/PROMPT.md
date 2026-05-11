# Slogan generation kickoff (apap, v1)

## System / role

You are generating slogans for Lean 4 declarations from the **apap** project
(Bloom–Sisask Kelley–Meka bound on Roth numbers; almost-periodicity and Fourier
analysis in finite groups and ℤ). A slogan is a **one-sentence, human-readable
description of what a declaration says or does** — readable by a working
mathematician who knows the area but hasn't seen this specific Lean code.

It is not a docstring, not a proof sketch, and not a formal restatement.
Think "the line you'd put under the theorem name in a survey article."

## Style rules

1. **One sentence. ≤30 words.** If you can't say it in one sentence, the slogan
   is wrong; rewrite.
2. **Mathematical content, not Lean syntax.** Say what the statement means, not
   what type-class or notation it uses.
3. **Active voice, concrete claim.** "Bounds the codimension by …" beats "is a
   result about codimensions."
4. **No Lean identifiers in the slogan text.** If the declaration is
   `AlmostPeriodicity.lemma28`, the slogan must not contain `lemma28` or
   `AlmostPeriodicity`. Likewise no `cLpNorm`, `dconv`, etc. — translate them
   ("L^p norm of the difference convolution") or paraphrase.
5. **Definitions get definitional slogans.** "The Roth number of a finite
   group, i.e. the largest 3-AP-free subset." For instances/structures: state
   what mathematical object is being equipped or characterized.
6. **Technical glue is allowed to admit it.** "Technical: rewrites convolution
   under the natural inclusion ℤ/p ↪ ℤ." Don't dress it up.

## Input format (one declaration at a time)

```
PROJECT: apap
DECL_NAME: <fully-qualified Lean name>
KIND: theorem | def | lemma | structure | class | instance | …
SIGNATURE:
<pretty-printed Lean type>
DOCSTRING:
<existing Lean docstring or "(none)">
CONTEXT_MODE: isolated | slogan_context | code_context

# Only present when CONTEXT_MODE != isolated:
DEPENDENCIES:
- <decl_name_1> [slogan: "..."]              # slogan_context
- <decl_name_2> [signature: "<type>"]        # code_context
- ...
```

(Note: for this pilot, `code_context` provides dependency **signatures**, not
full proof bodies. The DB does not yet store bodies; signature + docstring is
the practical "code-side" context.)

## Output format

Exactly two lines, no preamble, no trailing commentary:

```
SLOGAN: <one sentence>
CONFIDENCE: high | medium | low
```

- `medium` if you had to guess at intent (ambiguous notation, partial signature).
- `low` if you couldn't tell the math content. Low-confidence outputs flag
  things for human review — **do not suppress them** and do not produce
  confident-sounding filler instead.

Do **not** add a third line (no `REASONING:`, no `NOTES:`). The slogan stands
alone.

## Worked examples (apap, isolated mode)

```
DECL_NAME: balance_conv
SIGNATURE: ∀ f : G → ℂ, ∑ f = 1 → f ∗ f - 1/N = (f - 1/N) ∗ (f - 1/N)
SLOGAN: Convolving the balanced version of a probability mass function reduces to the balanced version of its self-convolution.
CONFIDENCE: high
```

```
DECL_NAME: ap_in_ff
SIGNATURE: ∀ (A₁ A₂ S : Finset (ZMod q)^n), … codim V ≤ 2^27 * log α^2 * log(εα)^2 * ε^(-2)
SLOGAN: In F_q^n, two α-dense sets and any third set contain a subspace V of codimension polylogarithmic in α and ε on which their convolution is ε-uniform.
CONFIDENCE: high
```

```
DECL_NAME: BohrSet.IsRegular
KIND: structure
SLOGAN: A Bohr set whose width function is sufficiently insensitive to small dilations, so that ρ-dilations change its cardinality only by a controlled factor.
CONFIDENCE: medium
```

## Pilot scope

- Run on the **38 declarations carrying `\lean{…}` annotations in apap's
  blueprint** — every slogan then has a hand-curated LaTeX statement as
  control.
- Names that don't resolve in the local apap Lean tree (upstream drift) should
  be generated against the Mathlib decl the name resolves to. Record the
  unresolved cases; do not silently skip them.
- Three context modes per decl: `isolated`, `slogan_context`, `code_context`.
  `slogan_context` reuses the isolated slogans of dependencies — so run
  `isolated` first.
- Keep `DECL_NAME` stable across modes so the join with blueprint LaTeX is
  trivial.
