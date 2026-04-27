# TheoremSearch failure modes — investigation report

**Date:** 2026‑04‑27
**API:** `https://api.theoremsearch.com/search` (Qwen3‑Embedding‑8B + HNSW + cosine rerank)
**Total queries probed:** 946 (batches A/B/C) + 80 follow-up probes (batch D) = **1,026**
**Judge:** GPT‑5.4‑mini scoring top-5 retrieved slogans against the query intent on a −2..+2 scale (see below). Original triage with GPT‑4o‑mini into `{good, partial, bad}` is preserved in §1.

The full per-query CSV (score, judgement, top‑3 slogans) is at `failure_modes.csv`. Raw retrievals and judged JSONL live under `results/` and are gitignored — regenerate with `run_search.py` then `judge.py` / `judge_csv.py`. The query bank is in `data/` (A/B/C/D, also gitignored).

### Score distribution (−2..+2 pass via `judge_csv.py`, gpt‑5.4‑mini, n = 1,026)

| Score | Meaning | Count | Share |
|------:|---------|------:|------:|
|  +2 | top‑1 is a clear, on-target match | 792 | 77.2 % |
|  +1 | clear match in top‑3 (not at rank 1) | 113 | 11.0 % |
|   0 | tangentially related; nothing in top‑3 directly answers | 80 | 7.8 % |
|  −1 | top‑3 off-topic / wrong-named | 15 | 1.5 % |
|  −2 | meta/corrupted slogans or empty | 26 | 2.5 % |

---

## 1 · Headline numbers

| Verdict   | Count | Share |
|-----------|------:|------:|
| good      | 790   | 83.5 % |
| partial   | 108   | 11.4 % |
|  **bad**   | 48    |  5.1 % |

Most queries work. The interesting question is *which kinds* fail. Below are the failure modes I could reproduce, ordered by how clear-cut and reproducible the failure is.

> **Note on the user's example.** The original example was that *"fermat last theorem"* returns garbage and *"fermat's last theorem"* returns good results. **I could not reproduce this** on the live API today — both queries return essentially the same dominant FLT statements (top‑10 differ only in tie order; top‑1 is identical). However, *"fermat last"* (without "theorem") **does** return garbage — see §2.6. The index may have been updated since the user's observation.

---

## 2 · Failure modes (most reproducible first)

### 2.1 · Short / cryptic abbreviations (severe)

Two‑ to four‑letter abbreviations that happen to occur as substrings in many slogans collapse into accidental lexical matches.

| query | verdict | top‑1 slogan |
|-------|---------|--------------|
| **`FTA`** | **bad** | "Theorem 1 implies Theorem FPT." |
| `fundamental theorem of algebra` | good | (states FTA, picks correct theorems) |
| **`AC`** | **bad** | "The ACC Lemma and the Upper Bounds Lemma…" |
| `axiom of choice` | good | states AC and its equivalences |
| **`GRR`** | **bad** | "The theorem holds in the system G plus R-g." |
| `Grothendieck-Riemann-Roch` | good | clean GRR results |
| **`EGA`** | **bad** | unrelated affine‑scheme statements |
| **`SGA 4`** | **bad** | "lemma is labeled as lemma4" |
| `PMI` | partial | weak (induction hits) |
| `ZFC` | partial | mentions ZFC but no theorem statements |
| `RH` | good | works |
| `CLT`, `LLN`, `PNT`, `MVT`, `IVT`, `FTC`, `CRT` | good | works |
| `FLT` | partial | mentions theorems but not FLT itself |

**Variants tested for `FTA`** (`F.T.A.`, `F T A`, `(FTA)`, `the FTA`) all produced *partial* — slightly better than bare `FTA` but still not a match. **`AC axiom`** moved `AC` from bad → good.

**Hypothesis:** the embedder treats short tokens dominantly by lexical surface. "FTA" appears as a substring inside "FPT", "FRT…axiom", etc.; "AC" appears inside "ACC", "A3", "set A". A query of just three uppercase letters has too little semantic context for the embedding to disambiguate.

### 2.2 · Single common nouns of math objects (severe, but easily fixed)

Bare common nouns that *are* the names of broad mathematical objects return statements that *contain* the word rather than *define* it.

| query | verdict | minimal-pair fix | verdict |
|-------|---------|------------------|---------|
| `topology` | **bad** | `topology definition` / `what is topology` / `definition of a topology` | **good** |
| `manifold` | **bad** | `smooth manifold` | **good** (`manifold definition` is partial) |
| `group` | **bad** | `definition of a group` / `group axioms` | **good** |
| `field` | **bad** | (untested fix; expect "field axioms" works) | – |
| `ring` | **bad** | (untested) | – |
| `module` | partial | – | – |
| `homotopy` | good | – | – |
| `homology`, `cohomology`, `category` | partial | – | – |

**Hypothesis:** the embedding's nearest neighbour for a single common noun is *every* slogan that uses that noun — and the corpus is dominated by results that *use* (not define) these objects. There's no single canonical "definition‑of‑X" statement and the citation/popularity prior doesn't help. Adding a discriminator like "definition" or "axioms" pulls the embedding into the right neighbourhood.

### 2.3 · Repeated single short tokens (severe)

Repeating a short query word many times degrades retrieval rather than reinforcing it.

| query | verdict |
|-------|---------|
| `Landau` | **bad** |
| `Landau Landau` | **bad** |
| `Landau Landau Landau` | **bad** |
| `Landau Landau Landau Landau` | **bad** |
| `Landau equation Landau equation` | **bad** |
| `Landau equation` | **bad** |
| `Landau equation in plasma` | good |
| `Landau-Lifshitz equation` | good |
| `Landau kinetic equation` | good |

**But:** `Riemann hypothesis Riemann hypothesis Riemann hypothesis` is **good**. So repetition is harmful only when the base query is short/ambiguous. With `Landau` the model has dozens of candidates (Landau equation in kinetics, Landau levels, Landau damping, Landau–Lifshitz, Landau symbols, …) and no signal to choose. Adding **any** modifier ("plasma", "kinetic", "Lifshitz") fixes it.

This is essentially a more extreme version of §2.2: very short queries with many polysemous interpretations have no canonical landing.

### 2.4 · Named physics laws / effects (severe, likely a coverage gap)

| query | verdict | top‑1 slogan (sim) |
|-------|---------|--------------------|
| `Pauli exclusion principle` | **bad** | "The theorem states that p is not equal to two." (0.49) |
| `Stefan-Boltzmann law` | **bad** | "The theorem is stated." (0.51) |
| `Aharonov-Bohm effect` | **bad** | "The arrow from A to B is taut…" (0.48) |
| `Wien displacement law` | **bad** | unrelated W bounds |
| `Bose-Einstein statistics` | **bad** | unrelated |
| `Fermi-Dirac statistics` | **bad** | unrelated |
| `Planck radiation formula` | **bad** | "The formula in the theorem matches…" |
| `fermions cannot share quantum state` | **good** | retrieves Pauli content |
| `Schrödinger equation` / `Schrodinger equation` / `Schroedinger equation` | good | works |
| `Einstein field equations`, `Lorentz transformation`, `Maxwell equations vacuum` | good | works |

**Hypothesis:** these phenomena are physics‑literature staples but are sparsely or absently *stated as theorems* in the arXiv math corpus the index covers. The system can't return what isn't there. Notice the smoking gun on `Pauli exclusion principle` — the top hit has a **lexical** match on the letter "p" ("p is not equal to two"), which is what you fall back to when nothing semantic is close. Same for `Aharonov-Bohm effect` matching "arrow from A to B". The embedder is doing token‑level matching in the absence of semantic signal.

This is partly a coverage gap (physics theorems aren't in the corpus) and partly a system bug: when *no* candidate is close, the system returns generic high‑surface‑area slogans rather than declining.

### 2.5 · Naked LaTeX equations & raw arithmetic (clear failure)

| query | verdict |
|-------|---------|
| `$\int_0^1 x^2 \, dx = 1/3$` | **bad** (top‑1 is "integral of x² from 0 to 2 equals 8/3") |
| `integral from 0 to 1 of x squared equals 1/3` | **bad** (same; numerical content is ignored) |
| `antiderivative of x squared is x cubed over 3` | **bad** |
| `0 + 0 = 0` | **bad** |
| `x = x` | good (matches reflexivity statements) |
| `e^{i\pi}+1=0` / `e^(i pi) = -1` / `Euler's identity` | good |

**Hypothesis:** specific numerical content is washed out by the embedder. "Integral of x² from 0 to 1" and "integral of x² from 0 to 2" both project to roughly the same vector. For trivial identities like `0 + 0 = 0`, the embedder has no math‑specific mode and treats it as low‑content noise.

`x = x` working but `0 + 0 = 0` failing is interesting — `x = x` has a clear conceptual hook (reflexivity); `0 + 0 = 0` doesn't.

### 2.6 · Non‑English query strings (clear failure)

| query | verdict |
|-------|---------|
| `théorème de Fermat` | **bad** |
| `Théorème de Fermat` | **bad** |
| `Grand théorème de Fermat` | **bad** |
| `Hauptsatz der Algebra` | good (German worked here) |

The French case fails consistently across capitalisation. Strikingly, the corpus *contains* French slogans (e.g. the FLT top hit's body is the French "Grand Théorème de Fermat") — but the **slogans for these statements are written in English** by the indexer, so a French query has nothing to embed against. This is a slogan‑side issue, not a query‑side issue.

### 2.7 · Truncated phrases (clear failure)

Trimming a famous theorem name to its leading words can flip retrieval.

| query | verdict |
|-------|---------|
| `fermat last theorem` | good |
| `fermat last` | **bad** |
| `fermat` | partial |
| `Riemann hypothesis` | good |
| `Riemann hypoth` | partial |

**Hypothesis:** the embedder relies on having enough surface tokens of the canonical name to anchor. Drop the last word and the embedding wanders.

> Surprisingly: `fermatlasttheorem` (no spaces, no separators) is **good**, as are `RiemannHypothesis` and `BanachTarski`. The embedder seems to handle *concatenated* well — better than *truncated*. So joining is robust; chopping is not.

### 2.8 · Eponym lemma names with unconventional punctuation (specific cases)

| query | verdict |
|-------|---------|
| `Cea lemma` | **bad** |
| `Cea's lemma` | mixed (judged good; top‑1 is generic "a lemma") |
| `Céa's lemma` | good |
| `Cea's lemma finite element` | good |
| `Lions trace theorem` | **bad** |
| `Sobolev trace theorem` / `trace theorem Sobolev` | good |
| `Thue theorem` / `Thue's theorem` | **bad** |
| `Thue Diophantine approximation` | partial |

**Hypothesis:** less‑famous eponyms with short surnames (Cea, Lions, Thue) get out‑competed by lexical neighbours unless context is added. The accent in `Céa` paradoxically helps because it makes the token rarer and more distinctive. The pattern matches §2.1 — short distinctive‑looking tokens without enough semantic context get hijacked.

### 2.9 · Open conjectures / niche-named results (medium)

`Bloch-Kato conjecture` returned **zero results** (not just bad — empty). `Yang-Mills mass gap`, `Eilenberg swindle`, `Cohen-Macaulay ring`, `Auslander-Reiten theory`, `Beilinson conjectures`, `Stark conjecture`, `Khinchin constant`, `Hardy-Littlewood circle method`, `Bombieri's theorem on density of zeros`, `Mackey formula`, `Burnside p^a q^b theorem` were judged *partial* — close‑ish content but not the named result itself.

**Hypothesis:** mix of corpus coverage (some results may genuinely not be in arXiv as a clean statement) and embedding choosing related‑but‑not‑exact neighbours.

### 2.10 · Definition-style queries (medium)

| query | verdict |
|-------|---------|
| `definition of group homomorphism` | **bad** (top hits literally "the mapping is a group homomorphism" — circular) |
| `what is a group homomorphism` | partial |
| `group homomorphism` | good |
| `f(xy)=f(x)f(y)` | good |
| `definition of a topology` | good |
| `topology` | bad |

Adding "definition of" sometimes helps (topology), sometimes hurts (homomorphism). The corpus rarely contains slogans that read "X is defined as…", so prefacing with "definition of" can pull the embedder toward results whose slogan accidentally mentions "definition" or away from the cleanest statement.

### 2.11 · arXiv IDs / DOIs / paper titles (expected; document for transparency)

`/search` is a *theorem* search, not a *paper* search. Queries that look like paper identifiers fail by design:

* `2403.05555` → bad (random theorem labels)
* `10.1007/s00208-023-12345-6` → bad
* Literal paper titles (e.g. `Fermat's Last Theorem and the Dirac equation`) → partial — gets some FLT‑adjacent content but not the paper.

These should probably be routed to `/paper-search` (which does autocomplete on titles/IDs) by the UI; here, exposing only `/search` produces confusing output.

### 2.12 · Adversarial / philosophical / pure‑garbage queries (expected)

`apple`, `hello world`, `asdfghjkl`, `lol math`, `what's the point of math`, `math is fun`, `I want to learn calculus` all return *bad* — generic top hits like "The theorem is stated." with low similarity (0.4–0.5). For non‑math input this is fine; for vague math input ("math is fun", "I want to learn calculus") it's a weak UX — the system should arguably produce *something* useful or admit it can't.

A safer behaviour for the UI would be to refuse to retrieve when the top‑1 cosine similarity falls below some threshold (the bad cases here all sit around 0.4–0.5; the good cases are 0.6+).

### 2.13 · Real user queries from `experiments/failure-modes/queries.csv` (mixed)

Replaying the live user log:

| query (verbatim) | verdict |
|------------------|---------|
| `Graph` | partial |
| `vector space` | partial |
| `Sequence of triangular numbers` | partial |
| `Serre Vanishing for Quasi Projective varieties` | partial |
| `non linear sequence of function turn to linear` | partial |
| `continuous-time model convergence of anchor acceleration` | partial |
| `the jones polynomail is link invariant` | good (typo handled) |
| `apple` | bad (off‑topic input) |
| `Random projection in linear algebra` | good |
| `Every finite group of order p^2 is abelian` | good |

Most user queries do work. The user pain points cluster on the same patterns above: bare common nouns (`Graph`, `vector space`), short/under-specified queries (`planck`, `Landau equation`), and noisy paraphrase queries.

---

## 3 · Failure-mode taxonomy at a glance

| #   | Pattern | Severity | Easy fix in front-end? |
|-----|---------|----------|------------------------|
| 2.1 | Cryptic abbreviations (FTA, AC, GRR, EGA) | severe | Expand abbreviations server-side / via LLM rewrite |
| 2.2 | Bare math common nouns (topology, group, manifold) | severe | Append "definition" if query is single token |
| 2.3 | Repeated short tokens (Landau Landau Landau) | severe | Dedupe consecutive tokens; require ≥1 modifier for short eponyms |
| 2.4 | Named physics laws (Pauli, Stefan–Boltzmann, AB) | severe | Coverage gap — out of scope, but should fail loudly |
| 2.5 | LaTeX equations / raw arithmetic | clear | LaTeX → words preprocessing already weakens this |
| 2.6 | French (and possibly other non-English) | clear | Translate query, or index multilingual slogans |
| 2.7 | Truncated names (`fermat last`, `Riemann hypoth`) | clear | Add "did you mean" / spell completion |
| 2.8 | Lesser eponymous lemmas (Cea, Lions trace, Thue) | medium | Same as §2.1 |
| 2.9 | Niche conjectures (Bloch‑Kato → 0 results) | medium | Coverage |
| 2.10 | "definition of …" preface | medium | Strip "definition of" and re-embed |
| 2.11 | Paper IDs / DOIs / titles | expected | Route to `/paper-search` |
| 2.12 | Garbage / vague | expected | Threshold on top‑1 similarity (≈ 0.55) |

---

## 4 · Discoveries that surprised me

1. **Concatenation is robust, truncation is not.** `fermatlasttheorem` works; `fermat last` doesn't. So Qwen3‑Embedding handles missing whitespace better than missing words. (Probably good subword tokenization.)
2. **Triple repetition is sometimes harmful, sometimes neutral.** `Landau Landau Landau` → bad, but `Riemann hypothesis Riemann hypothesis Riemann hypothesis` → good. The repetition flips the sign only when the underlying base query is short/ambiguous. The **dampening of the embedding norm** when repeating identical tokens is presumably the cause.
3. **Lexical artifacts dominate when semantics is absent.** `Pauli exclusion principle` → "p is not equal to two" (matches the *letter* "p"); `Aharonov-Bohm effect` → "arrow from A to B is taut" (matches "from A to B"). When nothing in the corpus is semantically close, the embedding falls back to surface co-occurrence and gets it spectacularly wrong. A confidence threshold on retrieval would have prevented these from surfacing as top results.
4. **Adding any modifier rescues bare-noun queries.** `topology` (bad) → `topology definition` (good). The fix is one token. A simple front-end rewrite — "if the query is one common-noun token, append `definition`" — would substantially help bare-noun queries.
5. **"Fermat's last theorem" pair the user reported is no longer broken on this API**, but `fermat last` (truncation) is broken — possibly the user observed the truncation case.

---

## 5 · Concrete suggestions

1. **Threshold on retrieval confidence.** When the top‑1 similarity is below ~0.55 the result is almost always garbage. Either don't return, or return with a "low confidence" warning.
2. **Pre-rewrite tiny queries.** If the query is ≤3 tokens and consists of common math nouns or short uppercase abbreviations, run a cheap LLM rewrite ("FTA" → "Fundamental theorem of algebra", "topology" → "definition of a topology") before embedding. Many of the failures collapse with this single change.
3. **Index slogans bilingually.** A French‑literate user querying `théorème de Fermat` finds nothing because slogans are English‑only. The body text *contains* French; just running the slogan generator on the original language (or storing both) would close this.
4. **Route paper-shaped inputs to `/paper-search`.** A query that looks like an arXiv ID (`\d{4}\.\d{4,5}`), DOI, or a long capitalised paper title shouldn't go to `/search`.
5. **Detect repetition.** If consecutive duplicate tokens appear (e.g. `Landau Landau Landau`), collapse before embedding. (Won't fix `Landau` alone — that's §2.3 — but stops users hurting themselves.)

---

## 6 · Reproducing

```sh
cd experiments/failure-modes
python3 run_search.py        # uses data/queries.jsonl → results/raw.jsonl
python3 judge.py             # uses results/raw_all.jsonl → results/judged.jsonl
```

Batches B/C/D are run by re-pointing `run_search.QUERIES` and `run_search.OUT` (see `run_search_bc.sh` for an example).

The judge prompt is in `judge.py` — it asks GPT‑4o‑mini to look at the query, the stated intent, and the top‑5 retrieved slogans, and emit `{verdict, reason, best_rank}`.

## 7 · Caveats

- The judge is GPT‑4o‑mini, which is sometimes lenient on borderline cases. (E.g. it judged `Cea's lemma` "good" when the top hits were generic "a lemma is presented" — a manual look at §2.8 disagreed.) Numbers above are within ±a few percentage points.
- I did **not** experiment with the API's `citation_weight`, `db_top_k`, or `prompt` parameters — every test used defaults. Some failures might recover under different parameters.
- The slogans in the corpus are themselves LLM‑generated summaries. Several "bad" cases trace to a slogan being too vague (e.g. "The theorem is stated."). Improving the slogan‑generation prompt would lift the floor everywhere.
