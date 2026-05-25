# Formalization Candidate Dataset

Output of the bidirectional NL↔FL matching pilot. Intended consumer:
**an agent looking for low-hanging fruit to formalize.** Every row is a
ranked (query, candidate) pair surfaced by qwen3-8b embedding cosine
over the blueprint-gold-pair subset.

## What's in this dataset

Three views, all in `experiments/nl_fl_matching/data/`:

| file | rows | what it is | committed |
|---|---:|---|---|
| `matches_all.jsonl` | 27,065 | every (query, rank≤10) row from both directions, fully hydrated | ❌ (63 MB, gitignored) |
| `top_formalization_candidates.csv` | 500 | top-500 **rank-1** i→f pairs sorted by similarity desc | ✅ |
| `top_validation_candidates.csv` | 500 | top-500 **rank-1** f→i pairs sorted by similarity desc | ✅ |
| `sample_formalization_candidates.csv` | 5 | smallest sanity-check slice, easy to eyeball | ✅ |
| `mutual_rank1_pairs.csv` | 400 | mutual rank-1 (top-1 in both f→i and i→f) | ✅ |
| `mutual_rank1_hydrated.csv` | 400 | mutual + slogans + decl_name + paper context | ✅ |
| `mutual_rank1_nongold.csv` | 45 | mutuals **not** flagged as blueprint gold — strongest backfill | ✅ |

To regenerate the JSONL + CSVs:
```bash
python -m experiments.nl_fl_matching.analysis.export_matches \
    --out experiments/nl_fl_matching/data/matches_all.jsonl
python -m experiments.nl_fl_matching.analysis.curate_for_formalization
```

Or query the canonical store directly:
```sql
-- top rank-1 i→f matches that the blueprint didn't already pair
SELECT m.query_statement_id, m.candidate_statement_id, m.similarity
  FROM nl_fl_match_pilot m
 WHERE m.direction = 'i2f'
   AND m.rank = 1
   AND m.pool_descriptor = 'gold_subset_i2f'
 ORDER BY m.similarity DESC
 LIMIT 100;
```

## Row schema (per CSV / JSONL line)

| column | meaning |
|---|---|
| `rank` | 1 = top match; ≤ 10 |
| `similarity` | cosine of qwen3-8b slogan embeddings (0–1) |
| `direction` | `f2i` (formal → closest informal) or `i2f` (informal → closest formal) |
| `is_blueprint_gold` | `True` if (informal, formal) appears in `informal_metadata.lean`-derived gold pairs |
| `q_*` / `c_*` | symmetric blocks for the query and candidate sides |
| `*_formality` | `formal` or `informal` |
| `*_kind` | `theorem`, `lemma`, `definition`, etc. |
| `*_source` | `Lean Repo` / `Lean Community` / `arXiv` / `Stacks Project` / ... |
| `*_paper_title`, `*_paper_external_id`, `*_paper_url` | paper context |
| `*_decl_name`, `*_module`, `*_file_path` | populated for the formal side |
| `*_ref`, `*_lean_annotation` | populated for the informal side |
| `*_slogan` | qwen3-235b natural-language slogan used for retrieval |

The full JSONL also includes raw `q_body` / `c_body` (LaTeX for informal,
Lean source for formal). The CSVs drop these to stay scannable.

## Recommended slice for "low-hanging fruit"

```python
import json, csv

# Lean-side already exists; arxiv-side might be a formalization opportunity.
# Filter: high-sim i2f pair NOT in the blueprint gold set.
candidates = []
with open("experiments/nl_fl_matching/data/matches_all.jsonl") as fh:
    for line in fh:
        r = json.loads(line)
        if r["direction"] != "i2f": continue
        if r["rank"] != 1: continue
        if r["is_blueprint_gold"]: continue       # already known
        if r["similarity"] < 0.85: continue       # threshold for "really close"
        candidates.append(r)

# Sort by similarity desc — start at the top.
candidates.sort(key=lambda r: -r["similarity"])
```

This yields informal statements (arxiv etc.) whose closest Lean decl is
not their blueprint partner — either because the blueprint annotation is
missing (system found a real match the blueprint authors didn't record)
or because the closest Lean decl semantically captures the same statement
even though the blueprint pointed at a different one. Both cases are
worth eyeballing.

The mirror slice (`direction == "f2i"`, non-gold) lets you validate
existing Lean decls against unconnected arxiv prose — "this Lean decl
looks like it formalizes results from this paper that nobody flagged."

## Headline scale numbers

- 1,308 distinct informal gold queries × top-10 = 13,080 i→f rows
- 1,562 distinct formal gold queries × top-10 = 13,985 f→i rows
- Embedding cosine range observed: ~0.40 (no match) → 0.98 (essentially
  the same statement)
- Cluster of "really close" rank-1 matches (sim ≥ 0.85, not gold): ~50-100
  candidates per direction at first pass (refresh by running the snippet
  above)

## Per-anchor dependency neighborhoods

The CSVs above give you anchor↔candidate pairs but not the *graph
context* an anchor sits in. For that we walk the
`informal_dependency` table around each of the 500 anchors and
classify every k=1 / k=2 neighbor as resolved / annotated_only /
matched_only / none. Output:

| artifact | location | rows |
|---|---|---:|
| Per-anchor aggregate (counts only) | `experiments/nl_fl_matching/data/neighborhoods.csv` | 500 |
| Per-neighbor detail (JSONL, gitignored) | `experiments/nl_fl_matching/data/neighborhoods_detail.jsonl` | 500 lines, ~9.6 MB |
| Per-neighbor detail (queryable) | RDS table `formalization_candidate_neighborhood`, db `v2` | 14,084 |
| Selection script | `experiments/nl_fl_matching/analysis/walk_neighborhoods.py` | — |
| Table DDL | `experiments/nl_fl_matching/schema_neighborhoods.sql` | — |

**Headline numbers** (gold-pool anchors, 2026-05-24):
- 500 anchors → 2,639 distinct k=1 neighbors, 11,445 k=2 (k=1 excluded)
- k=1: **91.6% resolved**, 6.9% none, 1.6% annotated_only, 0 matched_only
- k=2: 85.1% resolved, 12.8% none, 2.1% annotated_only
- **110 anchors** have ≥5 resolved k=1 siblings AND ≥1 unformalized k=1 hole — the prime "graph helps prover" candidate set
- Two repos dominate the top: `RemyDegenne/brownian-motion` and `teorth/pfr`

Concrete smoke-test slate distilled from this pool:
[`smoke_test_candidates.md`](./smoke_test_candidates.md) — 3 verified
candidates (A, B, F) selected after grepping the target repos to filter
out false negatives.

### Candidate attributes table

Per-candidate attributes live in RDS table `candidate_attributes` (one
row per of the 326 distinct unformalized candidates). Source:
`experiments/nl_fl_matching/analysis/candidate_attributes.py`. Schema:

| column | meaning |
|---|---|
| `math_category` | `text[]`: arXiv categories from `paper.categories`, with a hand-curated fallback for Lean Community blueprint repos (e.g. brownian-motion → `math.PR`). |
| `distance_undirected` | Shortest UNDIRECTED hop count on the informal-dependency graph to any interface node. |
| `distance_prereq_to_cons` | The colleague's ν_A: shortest DIRECTED hops starting at interface, traversing prerequisite → consequence (in our DB: edge `dep_id → src_id`). Tells you how many consequence-levels above the formalized foundation a candidate sits. |
| `distance_cite_to_dep` | Shortest DIRECTED hops the other way: interface → prerequisite chain (in our DB: edge `src_id → dep_id`). Tells you whether following the candidate's citation chain down reaches a formalized base. |
| `nearest_interface_id` | The interface node that achieved `distance_undirected`. |
| `nearest_interface_kind` | `'resolved_annotation'` \| `'gold_unresolved'` \| `'embedding_match'`. |
| `true_inference` | `True` if `nearest_interface_kind` is one of the gold variants (annotation-based); `False` if it's an embedding match. |
| `pass_rate`, `attempts_to_pass`, `sorry_trajectory` | NULL placeholders; populated when Aristotle runs land. See [`harness_design.md`](./harness_design.md). |
| `max_hops` | BFS cap (default 5). |

**Interface set** (union of 3 sources, priority resolved > gold_unresolved > embedding_match):

| source | count | what it is |
|---|---:|---|
| `resolved_annotation` | 1,308 | informals whose `\lean{...}` resolves to an existing `formal_metadata.decl_name` |
| `gold_unresolved` | 347 | informals with `\lean{...}` populated but not resolving (upstream/rename/aspirational) |
| `embedding_match` | 0 | informals appearing as rank-1 pilot queries at sim ≥ 0.85, excluding the above. **Empty under current pool** because the pilot was restricted to gold-pool queries. Will populate when the sweep is extended past gold. |

**Headline distributions (2026-05-24, n=326):**

| | dist=0 | dist=1 | dist=2 | dist=3+ | unreachable |
|---|---:|---:|---:|---:|---:|
| `distance_undirected` | 34 (10.4%) | 231 (70.9%) | 61 (18.7%) | 0 | 0 |
| `distance_prereq_to_cons` (ν_A) | 34 (10.4%) | 210 (64.4%) | 54 (16.6%) | 4 (1.2%) | **24 (7.4%)** |
| `distance_cite_to_dep` | 34 (10.4%) | 78 (23.9%) | 24 (7.4%) | 30 (9.2%) | **160 (49.1%)** |

**Reading the directed distances:**
- ν_A unreachable (24 candidates) = no formalized prerequisite within 5 hops up the consequence chain. These are "isolated upstream" candidates — the prover has nothing to bootstrap from on the prereq side.
- `cite_to_dep` unreachable (160) = the candidate's citation chain doesn't lead down to a formalized base. Many candidates ARE the foundational definitions, so this is expected.

**Nearest interface kind:**
- `resolved_annotation`: 274 (84.0%) — ground-truth interface link
- `gold_unresolved`: 52 (16.0%) — interface is a blueprint annotation that doesn't resolve (so we're banking on the author's intent, not a verified Lean decl)

**Math category (top, candidate-deduped):**
| category | n |
|---|---:|
| `math.PR` (probability) | 155 |
| `math.NT` (number theory) | 70 |
| `math.MG` (metric geometry) | 46 |
| `math.AG` (algebraic geometry) | 36 |
| `math.CO` (combinatorics) | 22 |
| `cs.CC` | 5 |
| `math.CA` | 2 |
| `math.GT` | 1 |

**Per-anchor-repo breakdown of unformalized neighbors (top 5; candidate-instances not deduped — most candidates appear in multiple anchor neighborhoods):**

| repo | dist=1 (undirected) | dist=2 |
|---|---:|---:|
| `RemyDegenne/brownian-motion` | 1,198 | 48 |
| `thefundamentaltheor3m/Sphere-Packing-Lean` | 183 | 4 |
| `YaelDillies/toric` | 157 | 22 |
| `kbuzzard/ClassFieldTheory` | 147 | 15 |
| `teorth/pfr` | 63 | 0 |

Reproduce / extend:
```bash
RDS_HOST=theorem-search.cluster-cx0ei6kq0qcn.us-west-2.rds.amazonaws.com \
    python3 -m experiments.nl_fl_matching.analysis.candidate_attributes
```
Bump `MAX_HOPS` for longer paths (caps the RDS column; default 5).
Bump `EMBEDDING_MATCH_SIM_THRESHOLD` to broaden/tighten the
embedding-derived interface contribution.

**Formal definition** (from a teammate's note, 2026-05-24): given
informal DAG $G_A$ and formal DAG $G_B$ with bidirectional connections
between some nodes, the *interface set* $I_A \subseteq V_A$ is the
set of $A$-nodes connected to any $B$-node, and
$\nu_A(v) = \min_{i \in I_A} d_A(i, v)$
where $d_A$ is shortest directed-path length in $A$. Our
`distance_prereq_to_cons` realizes this with $d_A$ = path length
following prereq→consequence edges (orienting $A$ so that a node's
predecessors are its prerequisites).

## Caveats for the next agent

1. **Slogans, not raw text.** Embeddings were computed on LLM-generated
   English slogans (qwen3-235b), not on raw LaTeX or Lean source. Two
   statements with near-identical slogans may still differ in
   formalization detail (e.g., one is "for all rings" and the other is
   "for all commutative rings"). Always cross-check the raw `*_body`
   before declaring a match.
2. **Mutual nearest-neighbours: lower precision than the 88.8% gold-overlap
   number suggests.** 400 mutual rank-1 pairs; 88.8% overlap gold. The 45
   non-gold mutuals at `mutual_rank1_nongold.csv` were audited dual-rater
   (Bedrock Claude Sonnet 4.5 + Haiku 4.5, 2026-05-24): **3/45 (6.7%)
   both 'correct'**, **11/45 (24.4%) 'correct or partial'**, **33/45
   (73%) at least one rater flags 'wrong'**. Most are topical near-misses
   not backfill candidates. Use this CSV for *exploration*, not as a
   curated backfill queue. See
   [`bidirectional_matching.md`](./bidirectional_matching.md)
   §mutual-NN-precision for the noise-adjusted bounds.
   Regenerate via
   `python -m experiments.nl_fl_matching.analysis.mutual_nn`,
   `python -m experiments.nl_fl_matching.analysis.mutual_hydrated`, then
   `python -m experiments.nl_fl_matching.analysis.audit_pairs_from_csv \
       --in experiments/nl_fl_matching/data/mutual_rank1_nongold.csv \
       --out-csv experiments/nl_fl_matching/data/mutual_nongold_audit.csv \
       --out-json experiments/nl_fl_matching/data/mutual_nongold_audit.json`.
3. **`is_blueprint_gold=False` ≠ "needs formalization".** The blueprint
   gold set is the union of `\lean{...}` annotations. Many statements
   not in this set may already be formalized — their authors just didn't
   add the annotation, or the lemma was upstreamed to Mathlib. The
   formal side of every row is a real Lean decl that exists in the
   corpus today.
4. **Pool restriction.** The current sweep is restricted to
   `gold_subset_f2i` / `gold_subset_i2f` — i.e., only queries that have
   at least one blueprint-gold partner. Expanding to non-gold queries
   (the deferred E/F/G items in [`bidirectional_matching.md`](./bidirectional_matching.md))
   would scale the dataset to ~36k formal queries × 11.7M informals.

## Sample rows (top 5 i→f matches, sorted by similarity)

```
sim   q (informal arxiv-side)                                 →  c (formal Lean-side)
0.977 PFR Blueprint Lemma 10.3 "BSG" (high additive energy)   →  add-combi: BSG_self'
0.974 PFR Blueprint Lemma 2.17 mutualInfo nonneg              →  pfr: ProbabilityTheory.measureMutualInfo_nonneg
0.... (see sample_formalization_candidates.csv for the rest)
```

The top-5 are all clearly the same statement on both sides, mostly from
PFR — the densest blueprint-annotated repo. These specific pairs are
flagged `is_blueprint_gold=False` despite being correct matches, which
means the **blueprint `\lean{...}` field was empty for these statements**
even though the formalization exists. So one immediate use of this data
is **backfilling missing blueprint annotations**.
