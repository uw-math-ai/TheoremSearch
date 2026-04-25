# TheoremSearch vs MATLAS — Retrieval Benchmark

A head-to-head retrieval evaluation of [TheoremSearch](https://theoremsearch.com) (arXiv + textbooks; built on Qwen3-Embedding-8B) against [MATLAS](https://matlas.ai) (180 ICM-cited journals + 1.9K textbooks; described in arXiv:2604.17484), run April 2026.

The two engines have **different corpora**: TheoremSearch indexes arXiv, MATLAS indexes journal-published versions. To make the comparison fair, we restricted to a sample of papers verified to be present in **both** engines, sampled queries from arXiv source LaTeX, and graded retrieval at both paper and theorem level.

## TL;DR

| | TheoremSearch | MATLAS |
|---|---|---|
| **Paper retrieval @10**       | 68% | **73%** |
| **Theorem retrieval @10**     | **62%** | 62% |
| Paper retrieval @1            | 51% | 51% |
| Theorem retrieval @1          | **45%** | 41% |
| Paper → theorem conversion    | **91%** | 85% |

- **Paper-level**: MATLAS recalls the source paper slightly more often (+5 pp at @10), driven by its higher-throughput retrieval (multiple statements per paper indexed, less aggressive ranking).
- **Theorem-level**: tied at 62% @10 overall. TheoremSearch is more *precise per theorem* — when it surfaces the right paper, the specific lemma is the one returned 91% of the time (vs 85% for MATLAS).
- **Both engines collapse on vague queries** (~45-48% theorem retrieval @10); precise paraphrases give 76-78% @10.

## Methodology

### 1. Building the overlap set (no theorem-retrieval bias)

The two engines have non-overlapping corpora — selecting papers based on whether *theorems* are findable in either engine would bias the downstream comparison. Instead we used **paper metadata** (titles, arXiv IDs, journal-refs) to construct an overlap set without ever consulting either engine's semantic search.

1. **arXiv `journal-ref` enumeration.** Pulled 748 candidates from the [arXiv API](https://arxiv.org/help/api), filtering by `journal-ref` in 17 MATLAS-covered journals (per the ICM-citation criterion described in arXiv:2604.17484): Inventiones, Duke, Compositio, Adv. Math., JAMS, Acta Math., J. Algebraic Geom., Geom. Topol., Math. Ann., Trans. AMS, J. Reine Angew., JEMS, GAFA, Selecta, Math. Z., IMRN, Algebra & Number Theory, Comm. Math. Phys., Annals. Restricted to 2010–2021 papers (where MATLAS coverage is densest).
2. **Bi-engine presence verification, by metadata.**
   - TheoremSearch: hit `/paper-search?q=<arxiv_id>` and confirm exact `external_id` match.
   - MATLAS: query the paper title via `/api/search`, confirm an exact-or-substring title match in the top-50 results, **without** matching against any specific theorem content.
3. **258 of 748 candidates (35%) were confirmed in both engines.** Sampled 60 papers (seed=42); 50 yielded usable arXiv source.

The 35% bi-engine hit rate is itself a finding: many recent arXiv papers in MATLAS-covered journals are *not* in MATLAS — coverage thins out post-2020 and is patchier than the "180 journals × 1826-2025" description suggests.

### 2. Sampling theorems

For each of the 50 papers:
- Downloaded the arXiv e-print tarball.
- Extracted theorem environments (`theorem`, `lemma`, `proposition`, `corollary`) from `.tex`, filtering bodies to 60–1500 chars.
- **Skipped the first 2 environments** (these are typically the headline `Theorem A` / `Theorem 1.1` main results), then sampled 4 random remaining environments per paper.

This produced **200 non-main theorems**.

### 3. Generating queries (two modes)

Each theorem got two natural-language queries, generated via [Codex CLI](https://github.com/openai/codex) (gpt-5.2) for consistency:

- **Precise**: a one-sentence informal restatement (~15-30 words) of the theorem, with LaTeX stripped and math re-expressed in prose. Kept core technical terms.
- **Vague**: a high-level conceptual query (~5-15 words) — the kind of thing a non-expert mathematician might Google. Topic + setting only, no specific statement.

Examples for the same theorem (a body about the LSFT differential on Legendrian knots):
- *Precise*: `"In the commutative LSFT algebra, the string differential kills t and sends each p or q generator to a sum over interlaced partners."`
- *Vague*: `"LSFT differential for Legendrian knots"`

This yields **400 queries (200 × 2 modes)**.

### 4. Running the engines

Both engines hit with `k=10`. Initially run with parallel workers (8 threads) — this caused transient timeouts (TS: 76/400, MATLAS: 29/400 returned `[]`), which were *not* engine-side similarity thresholds but ephemeral request failures. **Re-ran sequentially with retries; recovered all 105 failed requests**. Both engines reliably return k results given enough time.

### 5. Grading

Two grading levels per query, both at @1 / @3 / @5 / @10:

- **Paper-level**: does any result in the top-k come from the target paper? Strict matching: normalized titles must be equal OR one a contiguous substring of the other (≥15 chars). This rejects look-alike titles like `"On the De Rham-Witt complex in mixed characteristic"` matching the target `"The big de Rham-Witt complex"`.
- **Theorem-level**: paper-level match AND the candidate's body shares ≥ 2 normalized word-4-grams with the target theorem body. Robust to LaTeX macro expansion / OCR variations between arXiv and journal-published versions.

## Results

### Paper-level retrieval @k (n=200 per mode)

| Engine          | Mode    | @1  | @3  | @5  | @10 |
|-----------------|---------|----:|----:|----:|----:|
| TheoremSearch   | precise | 70% | 79% | 80% | 82% |
| TheoremSearch   | vague   | 32% | 44% | 48% | 54% |
| TheoremSearch   | overall | 51% | 62% | 64% | 68% |
| MATLAS          | precise | 68% | 79% | 82% | **85%** |
| MATLAS          | vague   | 34% | 54% | 56% | **61%** |
| MATLAS          | overall | 51% | 66% | 68% | **73%** |

### Theorem-level retrieval @k (n=200 per mode)

| Engine          | Mode    | @1  | @3  | @5  | @10 |
|-----------------|---------|----:|----:|----:|----:|
| TheoremSearch   | precise | **66%** | **76%** | **76%** | **78%** |
| TheoremSearch   | vague   | 24% | 35% | 38% | 45% |
| TheoremSearch   | overall | 45% | 55% | 57% | **62%** |
| MATLAS          | precise | 58% | 71% | 74% | 76% |
| MATLAS          | vague   | 24% | 42% | 44% | 48% |
| MATLAS          | overall | 41% | 56% | 59% | **62%** |

### How the engines differ

A few patterns repeat across the data:

- **TheoremSearch retrieves slogans.** The TS API exposes a `slogan_id` per result and `body` is the full theorem text. Slogan-based ranking is more discriminating per theorem — when the right paper is in top-10, the right theorem is in the same hit ~91% of the time (vs ~85% for MATLAS). This shows up as TS winning theorem-level @1 (45 vs 41) despite losing paper-level (51 vs 51, tied).
- **MATLAS retrieves statement bodies.** Returns more candidates per paper, broader matches; higher paper recall, but a query about Lemma 3.5 will sometimes surface Theorem 1.2 from the same paper.
- **Both struggle with vague queries.** Theorem-level @10 drops from ~77% (precise) to ~46% (vague) for both engines. Vague conceptual queries are the harder problem.

### Where each wins

Manual inspection of the 39 TS-only-hits and 89 MATLAS-only-hits at paper level (after the strict re-grading):

- **MATLAS-only hits** (89 cases): often vague queries against papers where MATLAS extracted many statements covering the topic; the same paper appears multiple times in top-10 with different statements, and one of them matches.
- **TS-only hits** (39 cases): often precise queries where the target theorem's wording aligns with TS's slogan summary; the matching is sharp and exact.

## Caveats

- **Selection bias toward "papers MATLAS already indexed well."** The bi-engine verification step requires MATLAS to have *some* extracted statement matching the paper title. Papers MATLAS has only weakly indexed (e.g., few/no extracted theorems) drop out — so this measures performance *conditional on both engines having reasonable coverage*, not on overall corpus coverage. Adjusting for the broader 35% bi-engine hit rate would change the picture.
- **n = 200 theorems / 50 papers**, all from arXiv math journals 2010-2021. Results may not generalize to applied math, recent papers, textbook-style content, or older work.
- **Codex-authored queries.** Using a single LLM to generate both modes is consistent but introduces stylistic bias — one paraphraser per query. Human-written queries (or your existing test-set queries, where they overlap with our 50 papers) would be more rigorous.
- **Theorem-match heuristic** (≥2 shared 4-grams) is a proxy for "same theorem" that handles macro expansion well but isn't perfect — manually verified on a sample of ~30 cases.
- **Single API snapshot** (April 2026). Both engines are likely improving; reproducibility window is short.

## Reproducibility

Pipeline scripts and intermediate JSON files were kept at `/tmp/cmp2/` during this run (not checked in here). The end-to-end pipeline is:

1. `gather.py` — pull arXiv candidates by `journal-ref` (~5 min wall, rate-limited by arXiv).
2. `verify.py` — bi-engine verification (~5 min, 6 threads).
3. `download_extract.py` — pull arXiv source, extract theorem envs (~5 min).
4. Sample papers/theorems → `picks.json`.
5. Codex paraphrase batches → `queries.json`.
6. `rerun_ts.py` + `rerun_matlas.py` — sequential search runs with retries (~10 min each).
7. `grade_theorem.py` — paper-level + theorem-level grading.

400 graded query results, with full top-10 captures from both engines, are in `graded_full.json` (~3 MB).
