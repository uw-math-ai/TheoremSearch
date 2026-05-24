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

## Caveats for the next agent

1. **Slogans, not raw text.** Embeddings were computed on LLM-generated
   English slogans (qwen3-235b), not on raw LaTeX or Lean source. Two
   statements with near-identical slogans may still differ in
   formalization detail (e.g., one is "for all rings" and the other is
   "for all commutative rings"). Always cross-check the raw `*_body`
   before declaring a match.
2. **Mutual nearest-neighbours = highest-confidence subset.** 400 pairs
   are rank-1 in both directions; 88.8% of these (355) are blueprint gold,
   so the 45 non-gold mutuals at `mutual_rank1_nongold.csv` are the
   strongest backfill candidates. Regenerate via
   `python -m experiments.nl_fl_matching.analysis.mutual_nn` then
   `python -m experiments.nl_fl_matching.analysis.mutual_hydrated`.
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
