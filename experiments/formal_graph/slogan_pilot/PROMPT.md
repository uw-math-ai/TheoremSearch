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

1. **1–4 sentences, plain English.** Standalone summary. Don't open with "this
   statement", "this theorem", "this definition" or similar self-reference;
   just describe the result.
2. **ASCII characters only. No LaTeX, no Unicode math symbols.** Write
   "alpha-dense" not "α-dense", "L^p norm" not "‖·‖_p", "F_q^n" not "𝔽_q^n",
   "epsilon" not "ε", "sum" not "∑", "subset of" not "⊆". No `$…$`, no
   backslashes, no `\frac`, no `\mathbb`. The goal is text that embeds well —
   pretend the reader can only see ASCII.
3. **Mathematical content, not Lean syntax.** Say what the statement means,
   not what type-class or notation it uses.
4. **Active voice, concrete claim.** "Bounds the codimension by …" beats "is
   a result about codimensions."
5. **No Lean identifiers in the slogan text.** If the declaration is
   `AlmostPeriodicity.lemma28`, the slogan must not contain `lemma28` or
   `AlmostPeriodicity`. Likewise no `cLpNorm`, `dconv`, etc. — translate them
   ("L^p norm of the difference convolution") or paraphrase.
6. **Definitions get definitional slogans.** "The Roth number of a finite
   group, i.e. the largest 3-AP-free subset." For instances/structures: state
   what mathematical object is being equipped or characterized.
7. **Technical glue is allowed to admit it.** "Technical: rewrites convolution
   under the natural inclusion of Z/p into Z." Don't dress it up.

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
SLOGAN: Balancing commutes with convolution: subtracting the mean from a probability density and then convolving the result with itself gives the same function as convolving the density with itself and then subtracting its mean.
CONFIDENCE: high
```

```
DECL_NAME: ap_in_ff
SLOGAN: Given two sets in F_q^n, each of density at least alpha, and any third set, there exists a subspace V of codimension polynomial in log(1/alpha) and 1/epsilon on which the convolution of the first two sets is epsilon-uniform relative to the third. This is the finite-field analogue of an almost-periodicity result used in additive combinatorics.
CONFIDENCE: high
```

```
DECL_NAME: BohrSet.IsRegular
KIND: structure
SLOGAN: A Bohr set is regular when small dilations of its width function change its cardinality only by a controlled multiplicative factor. This insensitivity property is the standard technical condition used to make Bohr sets behave well under iterative refinement.
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
