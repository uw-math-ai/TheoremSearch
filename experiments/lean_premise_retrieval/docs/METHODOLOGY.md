# Methodology & lessons

Two design corrections we made are themselves findings. Anyone extending this should respect both.

## 1. Sandbox the formalizer (don't let it read the gold)

The first unfamiliar-library run used tool-enabled agents to formalize the library's *own*
theorems. Because the library was built and importable, the agents simply **grepped the source and
read the exact gold statement** — both no-RAG and RAG hit ~100%, a meaningless tie. (Tell: they
produced exact niche names like `chainingSequence_of_lt` that no model knows parametrically; and one
renamed its theorem with a prime because the real one already existed in scope.)

Fix: the formalizer must be **sandboxed from the library source**. We enforce this two ways:
- Generation on a host that physically lacks the source (Qwen on klone), or
- A no-tools / single-Read agent whose tool-use count we audit (must not open `.lean` source, run
  `lake`/`lean`, or grep the source tree).

Only the *evaluator* (typecheck) sees the built library, after generation. The "library-access"
condition is a deliberate, separate arm — and even there we **prune** the library (below).

## 2. Mask forbidden premises (don't leak the target or circular deps)

Retrieval, and any "library-access" listing, must exclude:
- the **target itself**, and
- its **transitive reverse-dependencies** (everything downstream of it).

This is the forbidden set `forbidden(F) = {F} ∪ reverse-dep-closure(F)`, computed over the
lean-graph dependency edges. Without it, retrieval can return the target (trivial leak) or a
corollary that restates it. `src/formal_retriever.py` masks forbidden ids before top-k; the
library-access experiment prunes the same set from the searchable listing.

## 3. Leakage-controlled splits

Train/val/test are **held out by module** (whole Lean files), not by statement. A theorem and its
file-mates never straddle the split, which prevents the central leakage route (file-internal lemma
reuse). The premise corpus (the 388k decls being retrieved over) is shared across splits — that's
the search space, not the labels.

## 4. Controls that make recall numbers credible

- **Frequency prior** (return globally-popular premises, ignore the query): a strong, query-independent
  baseline. Any method must beat it, and the gap on *rare* premises (where the prior scores ~0) is the
  honest signal.
- **Rarity stratification**: report recall separately for rare (low train-frequency) vs common premises.
- **Query-shuffle**: score a target with another target's query; recall should collapse if the method
  is genuinely query-conditioned (ours: 0.55 → 0.01).

## 5. Compute accounting

For the unfamiliar-library experiment we track tokens and tool calls per condition, because the
interesting axis is **accuracy per unit compute**: retrieval vs. free library search trade accuracy
against exploration cost. Report both, not just accuracy.

## 6. Query embedding for novel inputs

For in-corpus targets the query vector is the target's stored slogan embedding (no model needed).
For novel queries (other libraries, real informal text) we embed live with Qwen3-Embedding-8B using
**last-token pooling** — validated by re-embedding known slogans and checking cosine ≈ stored vector,
and confirming live-embedding retrieval recall matches exact-vector recall (101%). Mean-pooling was
worse; the recipe must match how the index was built.
